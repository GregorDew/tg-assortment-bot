import json
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy import select

from app.filters.admin import IsAdminFilter
from app.database.database import async_session_maker
from app.database.models import PublishRuleModel, DataSourceModel, PublishChannelModel, TemplateModel
from app.core.rules.engine import execute_publish_rule
from app.states.rules_fsm import RuleWizardFSM
from app.keyboards.rules_kb import (
    get_rules_menu_kb,
    get_rule_mode_kb,
    get_rule_update_action_kb,
    get_rule_manage_kb
)
from app.keyboards.sources_kb import get_delete_confirm_kb
from app.keyboards.admin_kb import get_cancel_only_kb

logger = logging.getLogger(__name__)

router = Router()
router.message.filter(IsAdminFilter())
router.callback_query.filter(IsAdminFilter())


@router.callback_query(F.data == "menu:rules")
@router.callback_query(F.data == "rule:menu")
async def show_rules_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    text = (
        "🔄 <b>Правила та маршрутизація публікацій</b>\n\n"
        "Правила зв'язують <b>Джерела даних</b> із <b>Каналами публікації</b> (Telegram, Discord, HTTP, Email) "
        "та <b>Шаблонами</b>.\n\n"
        "Можна налаштувати:\n"
        "• Публікацію в 1 або відразу декілька каналів\n"
        "• Режим погодження адмінами або автоматичний автопост\n"
        "• Поведінку при зміні або видаленні записів"
    )
    await callback.message.edit_text(text, reply_markup=get_rules_menu_kb(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "rule:list")
async def list_rules(callback: CallbackQuery):
    async with async_session_maker() as session:
        res = await session.execute(select(PublishRuleModel).order_by(PublishRuleModel.id.desc()))
        rules = list(res.scalars().all())

    if not rules:
        text = "ℹ️ Наразі немає налаштованих правил. Натисніть «Створити правило»."
        await callback.message.edit_text(text, reply_markup=get_rules_menu_kb(), parse_mode="HTML")
        await callback.answer()
        return

    lines = ["📋 <b>Ваші правила публікації:</b>\n"]
    for r in rules:
        mode_ico = "📦 Погодження" if r.mode == "approval" else "⚡ Автопост"
        status_ico = "🟢" if r.is_active else "🔴"
        lines.append(f"• {status_ico} <b>#{r.id} {r.name}</b> [{mode_ico}]")
    text = "\n".join(lines) + "\n\nОберіть правило для керування:"

    kb_rows = []
    for r in rules[:8]:
        kb_rows.append([InlineKeyboardButton(text=f"⚙️ #{r.id} {r.name[:20]}", callback_data=f"rule_view:{r.id}")])
    kb_rows.append([InlineKeyboardButton(text="➕ Створити правило", callback_data="rule:add")])
    kb_rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="rule:menu")])

    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("rule_view:"))
async def view_rule_details(callback: CallbackQuery):
    rule_id = int(callback.data.split(":")[1])
    async with async_session_maker() as session:
        res = await session.execute(select(PublishRuleModel).where(PublishRuleModel.id == rule_id))
        r = res.scalar_one_or_none()

    if not r:
        await callback.answer("Правило не знайдено!", show_alert=True)
        return

    channels_count = 0
    if r.channel_ids_json:
        try:
            channels_count = len(json.loads(r.channel_ids_json))
        except Exception:
            pass

    status_str = "🟢 Працює" if r.is_active else "🔴 Зупинено"
    last_run = r.last_run_at.strftime('%Y-%m-%d %H:%M:%S') if r.last_run_at else "Ще не запускалось"

    text = (
        f"⚙️ <b>Правило: {r.name}</b>\n"
        f"───────────────────────\n"
        f"• <b>ID:</b> #{r.id}\n"
        f"• <b>Джерело даних ID:</b> #{r.data_source_id}\n"
        f"• <b>Шаблон ID:</b> #{r.template_id or 'За замовчуванням'}\n"
        f"• <b>Каналів призначення:</b> {channels_count}\n"
        f"• <b>Режим:</b> <code>{r.mode}</code>\n"
        f"• <b>Дія при зміні:</b> <code>{r.on_update_action}</code>\n"
        f"• <b>Інтервал:</b> {r.check_interval_seconds} сек.\n"
        f"• <b>Статус:</b> {status_str}\n"
        f"• <b>Останній запуск:</b> {last_run}"
    )
    await callback.message.edit_text(text, reply_markup=get_rule_manage_kb(r.id, r.is_active), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("rule_action:toggle:"))
async def toggle_rule(callback: CallbackQuery):
    rule_id = int(callback.data.split(":")[2])
    async with async_session_maker() as session:
        res = await session.execute(select(PublishRuleModel).where(PublishRuleModel.id == rule_id))
        r = res.scalar_one_or_none()
        if r:
            r.is_active = not r.is_active
            await session.commit()
            st = "активовано" if r.is_active else "зупинено"
            await callback.answer(f"Правило {st}!", show_alert=True)
    await view_rule_details(callback)


@router.callback_query(F.data.startswith("rule_action:run:"))
async def run_rule_now(callback: CallbackQuery):
    rule_id = int(callback.data.split(":")[2])
    await callback.answer("⏳ Виконання перевірки правила...")

    async with async_session_maker() as session:
        res = await session.execute(select(PublishRuleModel).where(PublishRuleModel.id == rule_id))
        r = res.scalar_one_or_none()
        if r:
            await execute_publish_rule(session, callback.bot, r)
            await callback.message.answer(f"✅ Перевірку правила #{rule_id} «{r.name}» завершено!")
        else:
            await callback.message.answer("Правило не знайдено.")


@router.callback_query(F.data.startswith("rule_action:delete_confirm:"))
async def confirm_delete_rule(callback: CallbackQuery):
    rule_id = int(callback.data.split(":")[2])
    text = f"⚠️ <b>Видалити правило #{rule_id}?</b>"
    await callback.message.edit_text(text, reply_markup=get_delete_confirm_kb("rule", rule_id), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("del_confirm:rule:"))
async def execute_delete_rule(callback: CallbackQuery):
    rule_id = int(callback.data.split(":")[2])
    async with async_session_maker() as session:
        res = await session.execute(select(PublishRuleModel).where(PublishRuleModel.id == rule_id))
        r = res.scalar_one_or_none()
        if r:
            await session.delete(r)
            await session.commit()
    await callback.answer("✅ Правило видалено!", show_alert=True)
    await list_rules(callback)


@router.callback_query(F.data.startswith("del_cancel:rule:"))
async def cancel_delete_rule(callback: CallbackQuery):
    await view_rule_details(callback)


# ---------------------------------------------------------------------------
# СТВОРЕННЯ ПРАВИЛА
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "rule:add")
async def start_add_rule(callback: CallbackQuery, state: FSMContext):
    await state.clear()

    # Перевіримо наявність джерел та каналів
    async with async_session_maker() as session:
        sources = list((await session.execute(select(DataSourceModel))).scalars().all())
        channels = list((await session.execute(select(PublishChannelModel))).scalars().all())

    if not sources:
        await callback.answer("⚠️ Спочатку додайте хоча б одне джерело даних!", show_alert=True)
        return
    if not channels:
        await callback.answer("⚠️ Спочатку додайте хоча б один канал публікації!", show_alert=True)
        return

    await state.set_state(RuleWizardFSM.waiting_for_name)
    text = "🔄 <b>Створення правила публікації</b>\n\nВведіть назву правила (наприклад: <code>Автопост нових товарів</code>):"
    await callback.message.answer(text, reply_markup=get_cancel_only_kb(), parse_mode="HTML")
    await callback.answer()


@router.message(RuleWizardFSM.waiting_for_name, F.text)
async def enter_rule_name(message: Message, state: FSMContext):
    name = message.text.strip()
    await state.update_data(rule_name=name)
    await state.set_state(RuleWizardFSM.waiting_for_source)

    async with async_session_maker() as session:
        sources = list((await session.execute(select(DataSourceModel))).scalars().all())

    kb_rows = []
    for s in sources:
        kb_rows.append([InlineKeyboardButton(text=f"🗄 #{s.id} {s.name}", callback_data=f"pick_src:{s.id}")])
    kb_rows.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="fsm:cancel")])

    text = f"Правило: <b>{name}</b>\n\nОберіть джерело даних:"
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows), parse_mode="HTML")


@router.callback_query(RuleWizardFSM.waiting_for_source, F.data.startswith("pick_src:"))
async def select_rule_source(callback: CallbackQuery, state: FSMContext):
    src_id = int(callback.data.split(":")[1])
    await state.update_data(data_source_id=src_id)
    await state.set_state(RuleWizardFSM.waiting_for_channels)

    async with async_session_maker() as session:
        channels = list((await session.execute(select(PublishChannelModel))).scalars().all())

    kb_rows = []
    for c in channels:
        kb_rows.append([InlineKeyboardButton(text=f"📢 #{c.id} {c.name} [{c.type}]", callback_data=f"pick_chn:{c.id}")])
    kb_rows.append([InlineKeyboardButton(text="🌟 Опублікувати у ВСІ канали", callback_data="pick_chn:all")])
    kb_rows.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="fsm:cancel")])

    text = "Оберіть канали публікації для цього правила:"
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows), parse_mode="HTML")
    await callback.answer()


@router.callback_query(RuleWizardFSM.waiting_for_channels, F.data.startswith("pick_chn:"))
async def select_rule_channels(callback: CallbackQuery, state: FSMContext):
    chn_val = callback.data.split(":")[1]

    async with async_session_maker() as session:
        channels = list((await session.execute(select(PublishChannelModel))).scalars().all())

    if chn_val == "all":
        selected_chn_ids = [c.id for c in channels]
    else:
        selected_chn_ids = [int(chn_val)]

    await state.update_data(channel_ids=selected_chn_ids)
    await state.set_state(RuleWizardFSM.waiting_for_template)

    async with async_session_maker() as session:
        templates = list((await session.execute(select(TemplateModel))).scalars().all())

    kb_rows = [
        [InlineKeyboardButton(text="📄 Стандартний формат (без шаблону)", callback_data="pick_tpl:0")]
    ]
    for t in templates:
        kb_rows.append([InlineKeyboardButton(text=f"📝 #{t.id} {t.name}", callback_data=f"pick_tpl:{t.id}")])
    kb_rows.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="fsm:cancel")])

    text = "Оберіть шаблон повідомлення:"
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows), parse_mode="HTML")
    await callback.answer()


@router.callback_query(RuleWizardFSM.waiting_for_template, F.data.startswith("pick_tpl:"))
async def select_rule_template(callback: CallbackQuery, state: FSMContext):
    tpl_id = int(callback.data.split(":")[1])
    await state.update_data(template_id=tpl_id if tpl_id > 0 else None)
    await state.set_state(RuleWizardFSM.waiting_for_mode)

    text = "Оберіть режим публікації для цього правила:"
    await callback.message.edit_text(text, reply_markup=get_rule_mode_kb(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(RuleWizardFSM.waiting_for_mode, F.data.startswith("rule_mode:"))
async def select_rule_mode(callback: CallbackQuery, state: FSMContext):
    mode = callback.data.split(":")[1]
    await state.update_data(rule_mode=mode)
    await state.set_state(RuleWizardFSM.waiting_for_update_action)

    text = "Оберіть дію при виявленні змін або оновленні запису:"
    await callback.message.edit_text(text, reply_markup=get_rule_update_action_kb(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(RuleWizardFSM.waiting_for_update_action, F.data.startswith("rule_upd:"))
async def select_rule_update_action(callback: CallbackQuery, state: FSMContext):
    upd_action = callback.data.split(":")[1]
    data = await state.get_data()
    await state.clear()

    rule_name = data.get("rule_name", "Нове правило")
    src_id = data.get("data_source_id")
    chn_ids = data.get("channel_ids", [])
    tpl_id = data.get("template_id")
    mode = data.get("rule_mode", "approval")

    async with async_session_maker() as session:
        new_rule = PublishRuleModel(
            name=rule_name,
            data_source_id=src_id,
            template_id=tpl_id,
            channel_ids_json=json.dumps(chn_ids),
            trigger_events=json.dumps(["new", "updated"]),
            mode=mode,
            on_update_action=upd_action,
            on_delete_action="ignore",
            check_interval_seconds=60,
            is_active=True
        )
        session.add(new_rule)
        await session.commit()
        await session.refresh(new_rule)
        rule_id = new_rule.id

    text = (
        f"🎉 <b>Правило #{rule_id} «{rule_name}» успішно створено!</b>\n\n"
        f"• Джерело: #{src_id}\n"
        f"• Каналів публікації: {len(chn_ids)}\n"
        f"• Режим: <b>{mode}</b>\n"
        f"• Дія при зміні: <code>{upd_action}</code>\n"
        f"• Інтервал перевірки: 60 сек."
    )
    await callback.message.answer(text, reply_markup=get_rule_manage_kb(rule_id, True), parse_mode="HTML")
    await callback.answer()
