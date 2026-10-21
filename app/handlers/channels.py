import json
import logging
from typing import Any, Dict, Optional, Tuple

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from app.config import settings
from app.core.connectors.factory import create_connector
from app.core.security import decrypt_secret, encrypt_secret
from app.database.database import async_session_maker
from app.database.models import PublishChannelModel
from app.filters.admin import IsAdminFilter
from app.keyboards.admin_kb import get_cancel_only_kb
from app.keyboards.channels_kb import get_channel_manage_kb, get_channel_types_kb, get_channels_menu_kb
from app.keyboards.sources_kb import get_delete_confirm_kb
from app.states.channels_fsm import ChannelWizardFSM

logger = logging.getLogger(__name__)

router = Router()
router.message.filter(IsAdminFilter())
router.callback_query.filter(IsAdminFilter())

SETUP_HINTS = {
    "telegram": (
        "✈️ <b>Telegram-канал / група</b>\n\n"
        "<b>Що зробити, інакше пост НЕ з'явиться в каналі:</b>\n"
        "1. Відкрийте канал → Адміністратори → Додати адміністратора.\n"
        "2. Знайдіть ЦЬОГО бота і додайте його.\n"
        "3. Увімкніть право <b>«Публікація повідомлень»</b>.\n"
        "4. Надішліть сюди <b>переслане повідомлення з каналу</b> "
        "(найнадійніше) АБО ID <code>-100...</code> АБО <code>@username</code>.\n\n"
        "Після збереження бот одразу надішле <b>тестовий пост</b> у канал. "
        "Якщо тесту немає — канал у боті збережено, але публікація ще не працює."
    ),
    "discord": (
        "🎮 <b>Discord</b>\n\n"
        "Окремого «бота Discord» у цьому проєкті немає. Працює через <b>Webhook</b>:\n"
        "1. Discord → ваш сервер → канал → Edit channel → Integrations → Webhooks.\n"
        "2. New Webhook → Copy Webhook URL.\n"
        "3. Вставте URL сюди (починається з <code>https://discord.com/api/webhooks/</code>).\n\n"
        "Альтернатива Bot API (якщо вже є Discord-бот):\n"
        "<code>BOT_TOKEN;CHANNEL_ID</code>\n"
        "Бот має бути запрошений на сервер з правом Send Messages."
    ),
    "http_api": (
        "🌐 <b>HTTP API</b>\n\n"
        "Цей бот сам по собі <b>не створює</b> сайт і не тримає вхідний HTTP-сервер. "
        "Йому потрібен <b>ваш</b> URL, який приймає JSON.\n\n"
        "Формат:\n"
        "<code>https://your-site.com/api/posts;POST;bearer;TOKEN</code>\n"
        "або без авторизації:\n"
        "<code>https://your-site.com/webhook;POST;none;-</code>\n\n"
        "Бот відправить JSON: title, body, photo_url, manager_button_url, extra_data.\n"
        "Методи: POST / PUT / PATCH. auth_type: none, bearer, api_key, basic."
    ),
    "email": (
        "📧 <b>Email (SMTP)</b>\n\n"
        "Потрібна поштова скринька, з якої бот надсилатиме листи. "
        "Власного поштового сервера в бота немає.\n\n"
        "Формат:\n"
        "<code>smtp_host;port;user;password;from_email;кому1,кому2</code>\n\n"
        "Gmail: увімкніть 2FA → Паролі застосунків → пароль на 16 символів.\n"
        "Приклад:\n"
        "<code>smtp.gmail.com;587;you@gmail.com;xxxx xxxx xxxx xxxx;you@gmail.com;sales@site.com</code>"
    ),
}


def _channel_type_title(channel_type: str) -> str:
    return {
        "telegram": "Telegram",
        "discord": "Discord",
        "http_api": "HTTP API",
        "email": "Email (SMTP)",
    }.get(channel_type, channel_type)


@router.callback_query(F.data == "menu:channels")
@router.callback_query(F.data == "chn:menu")
async def show_channels_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    text = (
        "📢 <b>Канали публікації</b>\n\n"
        "Сюди бот реально відправляє погоджені пости. "
        "Просто «додати канал у список» недостатньо: потрібні права на публікацію.\n\n"
        "• Telegram — бот має бути адміном каналу\n"
        "• Discord — Webhook URL з налаштувань каналу\n"
        "• HTTP API — ваш endpoint, який приймає JSON\n"
        "• Email — SMTP логін і список отримувачів"
    )
    await callback.message.edit_text(text, reply_markup=get_channels_menu_kb(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "chn:list")
async def list_channels(callback: CallbackQuery):
    async with async_session_maker() as session:
        channels = list(
            (await session.execute(select(PublishChannelModel).order_by(PublishChannelModel.id.desc()))).scalars().all()
        )

    if not channels:
        text = (
            "ℹ️ Каналів ще немає.\n\n"
            "Натисніть «Додати канал». Поки список порожній, пости можуть "
            "йти лише в TARGET_CHAT_ID з файлу .env — інші канали не отримають нічого."
        )
        await callback.message.edit_text(text, reply_markup=get_channels_menu_kb(), parse_mode="HTML")
        await callback.answer()
        return

    lines = ["📋 <b>Ваші канали публікації:</b>\n"]
    for channel in channels:
        status = "🟢" if channel.is_active else "🔴"
        lines.append(f"• {status} <b>#{channel.id} {channel.name}</b> [{channel.type}]")
    text = "\n".join(lines) + "\n\nОберіть канал, щоб перевірити ПУБЛІКАЦІЮ (не лише «чи видно чат»):"

    rows = [
        [InlineKeyboardButton(text=f"⚙️ #{c.id} {c.name[:24]}", callback_data=f"chn_view:{c.id}")]
        for c in channels[:12]
    ]
    rows.append([InlineKeyboardButton(text="➕ Додати канал", callback_data="chn:add")])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="chn:menu")])
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("chn_view:"))
async def view_channel_details(callback: CallbackQuery):
    channel_id = int(callback.data.split(":")[1])
    async with async_session_maker() as session:
        channel = (
            await session.execute(select(PublishChannelModel).where(PublishChannelModel.id == channel_id))
        ).scalar_one_or_none()

    if not channel:
        await callback.answer("Канал не знайдено", show_alert=True)
        return

    hint = ""
    if channel.type == "telegram":
        hint = (
            "\n\nЯкщо перевірка проходить, а постів немає — дивіться журнал. "
            "Бот має бути адміном з правом публікації, не просто «доданий»."
        )
    text = (
        f"📢 <b>Канал: {channel.name}</b>\n"
        f"───────────────────────\n"
        f"• <b>ID:</b> #{channel.id}\n"
        f"• <b>Платформа:</b> {_channel_type_title(channel.type)}\n"
        f"• <b>Статус:</b> {'🟢 Активний' if channel.is_active else '🔴 Вимкнено'}\n"
        f"{hint}"
    )
    await callback.message.edit_text(
        text,
        reply_markup=get_channel_manage_kb(channel.id, channel.is_active),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("chn_action:toggle:"))
async def toggle_channel(callback: CallbackQuery):
    channel_id = int(callback.data.split(":")[2])
    async with async_session_maker() as session:
        channel = (
            await session.execute(select(PublishChannelModel).where(PublishChannelModel.id == channel_id))
        ).scalar_one_or_none()
        if channel:
            channel.is_active = not channel.is_active
            await session.commit()
            await callback.answer("Увімкнено" if channel.is_active else "Вимкнено", show_alert=True)
    await view_channel_details(callback)


@router.callback_query(F.data.startswith("chn_action:test:"))
async def test_existing_channel(callback: CallbackQuery):
    channel_id = int(callback.data.split(":")[2])
    await callback.answer("Надсилаю тестовий пост...")
    async with async_session_maker() as session:
        channel = (
            await session.execute(select(PublishChannelModel).where(PublishChannelModel.id == channel_id))
        ).scalar_one_or_none()
        if not channel:
            await callback.message.answer("Канал не знайдено.")
            return
        try:
            config = json.loads(decrypt_secret(channel.config_json))
            connector = create_connector(channel.type, config, bot=callback.bot)
            ok, msg = await connector.test_connection()
        except Exception as exc:
            ok, msg = False, str(exc)
    prefix = "✅ <b>Тест успішний</b>\n" if ok else "❌ <b>Публікація НЕ працює</b>\n"
    await callback.message.answer(prefix + msg, parse_mode="HTML")


@router.callback_query(F.data.startswith("chn_action:delete_confirm:"))
async def confirm_delete_channel(callback: CallbackQuery):
    channel_id = int(callback.data.split(":")[2])
    await callback.message.edit_text(
        f"⚠️ <b>Видалити канал #{channel_id}?</b>",
        reply_markup=get_delete_confirm_kb("channel", channel_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("del_confirm:channel:"))
async def execute_delete_channel(callback: CallbackQuery):
    channel_id = int(callback.data.split(":")[2])
    async with async_session_maker() as session:
        channel = (
            await session.execute(select(PublishChannelModel).where(PublishChannelModel.id == channel_id))
        ).scalar_one_or_none()
        if channel:
            await session.delete(channel)
            await session.commit()
    await callback.answer("Канал видалено", show_alert=True)
    await list_channels(callback)


@router.callback_query(F.data.startswith("del_cancel:channel:"))
async def cancel_delete_channel(callback: CallbackQuery):
    await view_channel_details(callback)


@router.callback_query(F.data == "chn:add")
async def start_add_channel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(ChannelWizardFSM.waiting_for_type)
    await callback.message.edit_text(
        "📢 <b>Додавання каналу</b>\n\nОберіть платформу:",
        reply_markup=get_channel_types_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(ChannelWizardFSM.waiting_for_type, F.data.startswith("chn_type:"))
async def select_channel_type(callback: CallbackQuery, state: FSMContext):
    channel_type = callback.data.split(":")[1]
    await state.update_data(channel_type=channel_type)
    await state.set_state(ChannelWizardFSM.waiting_for_name)
    await callback.message.edit_text(
        f"Платформа: <b>{_channel_type_title(channel_type)}</b>\n\n"
        "Введіть коротку назву (наприклад: <code>Основний канал</code>):",
        reply_markup=get_cancel_only_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(ChannelWizardFSM.waiting_for_name, F.text)
async def enter_channel_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name:
        await message.answer("Назва не може бути порожньою.")
        return
    data = await state.get_data()
    channel_type = data.get("channel_type", "telegram")
    await state.update_data(channel_name=name)
    await state.set_state(ChannelWizardFSM.waiting_for_config)
    await message.answer(SETUP_HINTS.get(channel_type, "Надішліть параметри підключення."), parse_mode="HTML")


def _extract_telegram_chat_id(message: Message) -> Optional[str]:
    origin_chat = getattr(message, "forward_from_chat", None)
    if origin_chat is not None:
        return str(origin_chat.id)
    origin = getattr(message, "forward_origin", None)
    chat = getattr(origin, "chat", None) if origin is not None else None
    if chat is not None:
        return str(chat.id)
    text = (message.text or "").strip()
    if not text or text == "-":
        return str(settings.TARGET_CHAT_ID)
    return text


def _parse_discord_config(raw: str) -> Dict[str, Any]:
    text = raw.strip()
    if "discord.com/api/webhooks" in text or "discordapp.com/api/webhooks" in text:
        return {"webhook_url": text}
    if ";" in text:
        token, channel_id = text.split(";", 1)
        return {"bot_token": token.strip(), "channel_id": channel_id.strip()}
    raise ValueError("Потрібен Webhook URL або формат BOT_TOKEN;CHANNEL_ID")


def _parse_http_config(raw: str) -> Dict[str, Any]:
    parts = [p.strip() for p in raw.split(";")]
    if not parts or not parts[0].startswith("http"):
        raise ValueError("Першим має бути URL, наприклад https://site.com/api")
    cfg: Dict[str, Any] = {
        "endpoint_url": parts[0],
        "method": parts[1].upper() if len(parts) > 1 and parts[1] else "POST",
        "auth_type": parts[2].lower() if len(parts) > 2 and parts[2] else "none",
        "auth_token": parts[3] if len(parts) > 3 and parts[3] not in ("-", "") else "",
    }
    if cfg["auth_type"] == "basic" and len(parts) >= 5:
        cfg["auth_user"] = parts[3]
        cfg["auth_pass"] = parts[4]
        cfg["auth_token"] = ""
    return cfg


def _parse_email_config(raw: str) -> Dict[str, Any]:
    parts = [p.strip() for p in raw.split(";")]
    if len(parts) < 6:
        raise ValueError("Формат: smtp_host;port;user;password;from_email;recipient1,recipient2")
    return {
        "smtp_host": parts[0],
        "smtp_port": int(parts[1]),
        "smtp_user": parts[2],
        "smtp_password": parts[3],
        "from_email": parts[4],
        "recipients": parts[5],
        "start_tls": int(parts[1]) == 587,
        "use_tls": int(parts[1]) == 465,
    }


async def _build_config(channel_type: str, message: Message) -> Tuple[Dict[str, Any], str]:
    if channel_type == "telegram":
        chat_id = _extract_telegram_chat_id(message)
        if not chat_id:
            raise ValueError("Надішліть ID, @username або перешліть пост із каналу.")
        return {"chat_id": chat_id}, str(chat_id)
    raw = (message.text or "").strip()
    if not raw:
        raise ValueError("Надішліть текст із параметрами.")
    if channel_type == "discord":
        return _parse_discord_config(raw), raw[:80]
    if channel_type == "http_api":
        return _parse_http_config(raw), raw.split(";")[0]
    if channel_type == "email":
        return _parse_email_config(raw), raw.split(";")[0]
    raise ValueError("Невідомий тип каналу")


@router.message(ChannelWizardFSM.waiting_for_config)
async def save_channel_config(message: Message, state: FSMContext):
    data = await state.get_data()
    channel_type = data.get("channel_type", "telegram")
    channel_name = data.get("channel_name", "Канал")
    try:
        config, _preview = await _build_config(channel_type, message)
    except Exception as exc:
        await message.answer(f"⚠️ {exc}\n\nНадішліть параметри ще раз:")
        return

    wait = await message.answer("⏳ Перевіряю канал і надсилаю тестовий пост...")
    try:
        connector = create_connector(channel_type, config, bot=message.bot)
        ok, test_msg = await connector.test_connection()
    except Exception as exc:
        ok, test_msg = False, str(exc)

    if channel_type == "telegram" and config.get("chat_id"):
        try:
            chat = await message.bot.get_chat(config["chat_id"])
            config["chat_id"] = chat.id
        except Exception:
            pass

    async with async_session_maker() as session:
        channel = PublishChannelModel(
            name=channel_name,
            type=channel_type,
            config_json=encrypt_secret(json.dumps(config, ensure_ascii=False)),
            is_active=ok,
        )
        session.add(channel)
        await session.commit()
        await session.refresh(channel)
        channel_id = channel.id

    await state.clear()
    if ok:
        text = (
            f"✅ <b>Канал #{channel_id} «{channel_name}» додано і ПРОПЕРЕВІРЕНО.</b>\n\n"
            f"{test_msg}\n\n"
            "Погоджені товари тепер підуть і сюди (у всі активні канали)."
        )
    else:
        text = (
            f"⚠️ <b>Канал #{channel_id} збережено, але ВІДПРАВКА НЕ ПРАЦЮЄ.</b>\n\n"
            f"{test_msg}\n\n"
            "Канал вимкнено, щоб хибні пости не губились. Виправте права/URL "
            "і натисніть «Тест з'єднання». Поки тест червоний — у цей канал нічого не піде."
        )
    await wait.edit_text(text, parse_mode="HTML")
    await message.answer(
        "Керування каналом:",
        reply_markup=get_channel_manage_kb(channel_id, ok),
    )
