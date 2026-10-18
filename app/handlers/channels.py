import json
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy import select

from app.filters.admin import IsAdminFilter
from app.database.database import async_session_maker
from app.database.models import PublishChannelModel
from app.core.security import encrypt_secret, decrypt_secret
from app.core.connectors.factory import create_connector
from app.states.channels_fsm import ChannelWizardFSM
from app.keyboards.channels_kb import (
    get_channels_menu_kb,
    get_channel_types_kb,
    get_channel_manage_kb
)
from app.keyboards.sources_kb import get_delete_confirm_kb
from app.keyboards.admin_kb import get_cancel_only_kb

logger = logging.getLogger(__name__)

router = Router()
router.message.filter(IsAdminFilter())
router.callback_query.filter(IsAdminFilter())


@router.callback_query(F.data == "menu:channels")
@router.callback_query(F.data == "chn:menu")
async def show_channels_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    text = (
        "📢 <b>Керування каналами публікації</b>\n\n"
        "Налаштуйте напрямки, куди система буде відправляти дані:\n"
        "• <b>Telegram</b> (канали та групи)\n"
        "• <b>Discord</b> (канали через Webhook або Bot API)\n"
        "• <b>HTTP API</b> (зовнішні вебсайти, CRM, сервери)\n"
        "• <b>Email</b> (SMTP розсилка листів покупцям або менеджерам)"
    )
    await callback.message.edit_text(text, reply_markup=get_channels_menu_kb(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "chn:list")
async def list_channels(callback: CallbackQuery):
    async with async_session_maker() as session:
        res = await session.execute(select(PublishChannelModel).order_by(PublishChannelModel.id.desc()))
        channels = list(res.scalars().all())

    if not channels:
        text = "ℹ️ Наразі немає доданих каналів. Натисніть «Додати канал»."
        await callback.message.edit_text(text, reply_markup=get_channels_menu_kb(), parse_mode="HTML")
        await callback.answer()
        return

    lines = ["📋 <b>Ваші канали публікації:</b>\n"]
    for c in channels:
        status_ico = "🟢 Активний" if c.is_active else "🔴 Вимкнено"
        lines.append(f"• <b>#{c.id} {c.name}</b> [{c.type.upper()}] — {status_ico}")
    text = "\n".join(lines) + "\n\nОберіть канал для перевірки або налаштування:"

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb_rows = []
    for c in channels[:8]:
        kb_rows.append([InlineKeyboardButton(text=f"⚙️ #{c.id} {c.name[:20]}", callback_data=f"chn_view:{c.id}")])
    kb_rows.append([InlineKeyboardButton(text="➕ Додати канал", callback_data="chn:add")])
    kb_rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="chn:menu")])

    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("chn_view:"))
async def view_channel_details(callback: CallbackQuery):
    channel_id = int(callback.data.split(":")[1])
    async with async_session_maker() as session:
        res = await session.execute(select(PublishChannelModel).where(PublishChannelModel.id == channel_id))
        c = res.scalar_one_or_none()

    if not c:
        await callback.answer("Канал не знайдено!", show_alert=True)
        return

    status_str = "🟢 Активний" if c.is_active else "🔴 Вимкнено"
    text = (
        f"📢 <b>Канал публікації: {c.name}</b>\n"
        f"───────────────────────\n"
        f"• <b>ID:</b> #{c.id}\n"
        f"• <b>Платформа:</b> {c.type.upper()}\n"
        f"• <b>Статус:</b> {status_str}\n"
        f"• <b>Створено:</b> {c.created_at.strftime('%Y-%m-%d %H:%M')}"
    )
    await callback.message.edit_text(text, reply_markup=get_channel_manage_kb(c.id, c.is_active), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("chn_action:toggle:"))
async def toggle_channel(callback: CallbackQuery):
    channel_id = int(callback.data.split(":")[2])
    async with async_session_maker() as session:
        res = await session.execute(select(PublishChannelModel).where(PublishChannelModel.id == channel_id))
        c = res.scalar_one_or_none()
        if c:
            c.is_active = not c.is_active
            await session.commit()
            st = "увімкнено" if c.is_active else "вимкнено"
            await callback.answer(f"Канал {st}!", show_alert=True)
    await view_channel_details(callback)


@router.callback_query(F.data.startswith("chn_action:test:"))
async def test_existing_channel(callback: CallbackQuery):
    channel_id = int(callback.data.split(":")[2])
    async with async_session_maker() as session:
        res = await session.execute(select(PublishChannelModel).where(PublishChannelModel.id == channel_id))
        c = res.scalar_one_or_none()

    if not c:
        await callback.answer("Канал не знайдено!", show_alert=True)
        return

    await callback.answer("⏳ Перевірка доступності каналу...")
    try:
        cfg = json.loads(decrypt_secret(c.config_json))
        connector = create_connector(c.type, cfg, bot=callback.bot)
        ok, msg = await connector.test_connection()
        if ok:
            await callback.message.answer(f"✅ <b>Тест зв'язку успішний:</b>\n{msg}", parse_mode="HTML")
        else:
            await callback.message.answer(f"❌ <b>Помилка перевірки:</b>\n{msg}", parse_mode="HTML")
    except Exception as e:
        await callback.message.answer(f"❌ <b>Помилка тесту:</b> {e}")


@router.callback_query(F.data.startswith("chn_action:delete_confirm:"))
async def confirm_delete_channel(callback: CallbackQuery):
    channel_id = int(callback.data.split(":")[2])
    text = f"⚠️ <b>Видалити канал публікації #{channel_id}?</b>"
    await callback.message.edit_text(text, reply_markup=get_delete_confirm_kb("channel", channel_id), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("del_confirm:channel:"))
async def execute_delete_channel(callback: CallbackQuery):
    channel_id = int(callback.data.split(":")[2])
    async with async_session_maker() as session:
        res = await session.execute(select(PublishChannelModel).where(PublishChannelModel.id == channel_id))
        c = res.scalar_one_or_none()
        if c:
            await session.delete(c)
            await session.commit()
    await callback.answer("✅ Канал видалено!", show_alert=True)
    await list_channels(callback)


@router.callback_query(F.data.startswith("del_cancel:channel:"))
async def cancel_delete_channel(callback: CallbackQuery):
    await view_channel_details(callback)


# ---------------------------------------------------------------------------
# СТВОРЕННЯ КАНАЛУ ПУБЛІКАЦІЇ
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "chn:add")
async def start_add_channel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(ChannelWizardFSM.waiting_for_type)
    text = "📢 <b>Додавання каналу публікації</b>\n\nОберіть платформу:"
    await callback.message.edit_text(text, reply_markup=get_channel_types_kb(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(ChannelWizardFSM.waiting_for_type, F.data.startswith("chn_type:"))
async def select_channel_type(callback: CallbackQuery, state: FSMContext):
    chn_type = callback.data.split(":")[1]
    await state.update_data(chn_type=chn_type)
    await state.set_state(ChannelWizardFSM.waiting_for_name)

    await callback.message.answer(
        f"Платформа: <b>{chn_type.upper()}</b>\n\nВведіть назву для цього каналу (наприклад: <code>Основний Discord</code>):",
        reply_markup=get_cancel_only_kb(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(ChannelWizardFSM.waiting_for_name, F.text)
async def enter_channel_name(message: Message, state: FSMContext):
    name = message.text.strip()
    await state.update_data(chn_name=name)
    data = await state.get_data()
    chn_type = data.get("chn_type")

    await state.set_state(ChannelWizardFSM.waiting_for_config)

    if chn_type == "telegram":
        text = (
            "✈️ <b>Налаштування Telegram каналу/групи</b>\n\n"
            "Введіть ID чату (наприклад: <code>-1001234567890</code>) або юзернейм каналу <code>@my_channel</code>.\n"
            "<i>(Якщо залишити пустим або відправити <code>-</code>, буде використано TARGET_CHAT_ID з .env)</i>"
        )
    elif chn_type == "discord":
        text = (
            "🎮 <b>Налаштування Discord каналу</b>\n\n"
            "Надішліть Webhook URL вашого каналу:\n"
            "<code>https://discord.com/api/webhooks/.../...</code>\n\n"
            "<i>(Або у форматі: <code>bot_token;channel_id</code>)</i>"
        )
    elif chn_type == "http_api":
        text = (
            "🌐 <b>Налаштування HTTP API</b>\n\n"
            "Введіть параметри у форматі:\n"
            "<code>endpoint_url;method;auth_type;auth_token</code>\n\n"
            "Приклад:\n<code>https://my-site.com/api/products;POST;bearer;secret_token_123</code>"
        )
    else:  # email
        text = (
            "📧 <b>Налаштування Email (SMTP)</b>\n\n"
            "Введіть параметри у форматі:\n"
            "<code>smtp_host;port;user;password;from_email;recipient1,recipient2</code>\n\n"
            "Приклад:\n<code>smtp.gmail.com;587;mybot@gmail.com;app_password;mybot@gmail.com;admin@site.com,buyer@site.com</code>"
        )

    await message.answer(text, reply_markup=get_cancel_only_kb(), parse_mode="HTML")


@router.message(ChannelWizardFSM.waiting_for_config, F.text)
async def save_channel_config(message: Message, state: FSMContext):
    raw = message.text.strip()
    data = await state.get_data()
    chn_type = data.get("chn_type")
    chn_name = data.get("chn_name", "Канал")

    config = {}
    if chn_type == "telegram":
        config = {"chat_id": raw if raw != "-" else ""}
    elif chn_type == "discord":
        if ";" in raw:
            parts = [p.strip() for p in raw.split(";")]
            config = {"bot_token": parts[0], "channel_id": parts[1]}
        else:
            config = {"webhook_url": raw}
    elif chn_type == "http_api":
        parts = [p.strip() for p in raw.split(";")]
        config = {
            "endpoint_url": parts[0],
            "method": parts[1] if len(parts) > 1 else "POST",
            "auth_type": parts[2] if len(parts) > 2 else "none",
            "auth_token": parts[3] if len(parts) > 3 else ""
        }
    else:  # email
        parts = [p.strip() for p in raw.split(";")]
        if len(parts) < 6:
            await message.answer("⚠️ Неправильний формат! Потрібно: host;port;user;password;from_email;recipients")
            return
        config = {
            "smtp_host": parts[0],
            "smtp_port": int(parts[1]),
            "smtp_user": parts[2],
            "smtp_password": parts[3],
            "from_email": parts[4],
            "recipients": parts[5]
        }

    # Тестуємо перед збереженням
    await message.answer("⏳ Тестування каналу...")
    try:
        connector = create_connector(chn_type, config, bot=message.bot)
        ok, msg = await connector.test_connection()
        if not ok:
            await message.answer(f"❌ <b>Помилка тесту підключення:</b>\n{msg}\n\nСпробуйте надіслати конфігурацію ще раз:")
            return
    except Exception as e:
        await message.answer(f"❌ <b>Помилка:</b> {e}\n\nСпробуйте ще раз:")
        return

    encrypted_cfg = encrypt_secret(json.dumps(config))
    await state.clear()

    async with async_session_maker() as session:
        new_channel = PublishChannelModel(
            name=chn_name,
            type=chn_type,
            config_json=encrypted_cfg,
            is_active=True
        )
        session.add(new_channel)
        await session.commit()
        await session.refresh(new_channel)
        channel_id = new_channel.id

    text = (
        f"✅ <b>Канал публікації успішно додано!</b>\n\n"
        f"• <b>ID:</b> #{channel_id}\n"
        f"• <b>Назва:</b> {chn_name}\n"
        f"• <b>Платформа:</b> {chn_type.upper()}\n"
        f"• <b>Статус:</b> 🟢 Активний"
    )
    await message.answer(text, reply_markup=get_channel_manage_kb(channel_id, True), parse_mode="HTML")
