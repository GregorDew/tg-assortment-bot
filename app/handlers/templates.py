import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy import select

from app.filters.admin import IsAdminFilter
from app.database.database import async_session_maker
from app.database.models import TemplateModel
from app.core.templating import render_template, extract_template_variables
from app.states.templates_fsm import TemplateWizardFSM
from app.keyboards.templates_kb import (
    get_templates_menu_kb,
    get_template_platforms_kb,
    get_template_manage_kb
)
from app.keyboards.sources_kb import get_delete_confirm_kb
from app.keyboards.admin_kb import get_cancel_only_kb

logger = logging.getLogger(__name__)

router = Router()
router.message.filter(IsAdminFilter())
router.callback_query.filter(IsAdminFilter())


@router.callback_query(F.data == "menu:templates")
@router.callback_query(F.data == "tpl:menu")
async def show_templates_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    text = (
        "📝 <b>Конструктор шаблонів повідомлень</b>\n\n"
        "Тут ви можете створювати та редагувати шаблони для публікацій.\n"
        "Підтримуються змінні формату <code>{назва_поля}</code> та значення за замовчуванням: "
        "<code>{ціна|Договірна}</code>.\n\n"
        "<i>Виконання стороннього коду повністю заборонено задля безпеки.</i>"
    )
    await callback.message.edit_text(text, reply_markup=get_templates_menu_kb(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "tpl:list")
async def list_templates(callback: CallbackQuery):
    async with async_session_maker() as session:
        res = await session.execute(select(TemplateModel).order_by(TemplateModel.id.desc()))
        templates = list(res.scalars().all())

    if not templates:
        text = "ℹ️ Наразі немає створених шаблонів. Натисніть «Створити шаблон»."
        await callback.message.edit_text(text, reply_markup=get_templates_menu_kb(), parse_mode="HTML")
        await callback.answer()
        return

    lines = ["📋 <b>Ваші шаблони:</b>\n"]
    for t in templates:
        lines.append(f"• <b>#{t.id} {t.name}</b> [{t.platform}]")
    text = "\n".join(lines) + "\n\nОберіть шаблон для перегляду або видалення:"

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb_rows = []
    for t in templates[:8]:
        kb_rows.append([InlineKeyboardButton(text=f"📄 #{t.id} {t.name[:20]}", callback_data=f"tpl_view:{t.id}")])
    kb_rows.append([InlineKeyboardButton(text="➕ Створити шаблон", callback_data="tpl:add")])
    kb_rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="tpl:menu")])

    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("tpl_view:"))
async def view_template_details(callback: CallbackQuery):
    template_id = int(callback.data.split(":")[1])
    async with async_session_maker() as session:
        res = await session.execute(select(TemplateModel).where(TemplateModel.id == template_id))
        t = res.scalar_one_or_none()

    if not t:
        await callback.answer("Шаблон не знайдено!", show_alert=True)
        return

    vars_found = extract_template_variables((t.title_template or "") + " " + t.body_template)
    vars_str = ", ".join(vars_found) if vars_found else "статичний текст"

    text = (
        f"📄 <b>Шаблон: {t.name}</b>\n"
        f"───────────────────────\n"
        f"• <b>Платформа:</b> {t.platform}\n"
        f"• <b>Заголовок/Тема:</b> <code>{t.title_template or 'не вказано'}</code>\n"
        f"• <b>Змінні полів:</b> <code>{vars_str}</code>\n\n"
        f"<b>Тіло шаблону:</b>\n<pre>{t.body_template[:500]}</pre>"
    )
    await callback.message.edit_text(text, reply_markup=get_template_manage_kb(t.id), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("tpl_action:preview:"))
async def preview_template(callback: CallbackQuery):
    template_id = int(callback.data.split(":")[2])
    async with async_session_maker() as session:
        res = await session.execute(select(TemplateModel).where(TemplateModel.id == template_id))
        t = res.scalar_one_or_none()

    if not t:
        await callback.answer("Шаблон не знайдено!", show_alert=True)
        return

    dummy_data = {
        "id": "101",
        "title": "Ноутбук Dell XPS 15",
        "name": "Ноутбук Dell XPS 15",
        "price": "45 000 грн",
        "description": "Потужний ноутбук для професійної роботи та графіки.",
        "status": "в наявності",
        "category": "Електроніка"
    }

    rendered_body = render_template(t.body_template, dummy_data, escape_for_html=False)
    rendered_title = render_template(t.title_template or "", dummy_data, escape_for_html=False)

    msg = (
        f"👁 <b>Попередній перегляд шаблону #{t.id} з тестовими даними:</b>\n\n"
        f"📌 <b>Заголовок:</b> {rendered_title or '—'}\n\n"
        f"📄 <b>Вміст:</b>\n{rendered_body}"
    )
    await callback.message.answer(msg)
    await callback.answer()


@router.callback_query(F.data.startswith("tpl_action:delete_confirm:"))
async def confirm_delete_template(callback: CallbackQuery):
    template_id = int(callback.data.split(":")[2])
    text = f"⚠️ <b>Ви дійсно бажаєте видалити шаблон #{template_id}?</b>"
    await callback.message.edit_text(text, reply_markup=get_delete_confirm_kb("template", template_id), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("del_confirm:template:"))
async def execute_delete_template(callback: CallbackQuery):
    template_id = int(callback.data.split(":")[2])
    async with async_session_maker() as session:
        res = await session.execute(select(TemplateModel).where(TemplateModel.id == template_id))
        t = res.scalar_one_or_none()
        if t:
            await session.delete(t)
            await session.commit()
    await callback.answer("✅ Шаблон видалено!", show_alert=True)
    await list_templates(callback)


@router.callback_query(F.data.startswith("del_cancel:template:"))
async def cancel_delete_template(callback: CallbackQuery):
    await view_template_details(callback)


# ---------------------------------------------------------------------------
# СТВОРЕННЯ ШАБЛОНУ
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "tpl:add")
async def start_add_template(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(TemplateWizardFSM.waiting_for_platform)
    text = "📝 <b>Створення нового шаблону</b>\n\nОберіть цільову платформу:"
    await callback.message.edit_text(text, reply_markup=get_template_platforms_kb(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(TemplateWizardFSM.waiting_for_platform, F.data.startswith("tpl_plat:"))
async def select_template_platform(callback: CallbackQuery, state: FSMContext):
    plat = callback.data.split(":")[1]
    await state.update_data(tpl_platform=plat)
    await state.set_state(TemplateWizardFSM.waiting_for_name)

    await callback.message.answer(
        "Введіть назву для шаблону (наприклад: <code>Пост у Telegram</code> або <code>Лист покупцю</code>):",
        reply_markup=get_cancel_only_kb(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(TemplateWizardFSM.waiting_for_name, F.text)
async def enter_template_name(message: Message, state: FSMContext):
    name = message.text.strip()
    await state.update_data(tpl_name=name)
    await state.set_state(TemplateWizardFSM.waiting_for_title)

    text = (
        "📌 <b>Заголовок або тема повідомлення (Subject/Title)</b>\n\n"
        "Введіть шаблон заголовка (наприклад: <code>🔥 Новинка: {title}</code>)\n"
        "або надішліть <code>-</code>, щоб пропустити:"
    )
    await message.answer(text, reply_markup=get_cancel_only_kb(), parse_mode="HTML")


@router.message(TemplateWizardFSM.waiting_for_title, F.text)
async def enter_template_title(message: Message, state: FSMContext):
    title = message.text.strip()
    await state.update_data(tpl_title=None if title == "-" else title)
    await state.set_state(TemplateWizardFSM.waiting_for_body)

    text = (
        "📄 <b>Основний текст шаблону (Body)</b>\n\n"
        "Введіть структуру повідомлення, використовуючи поля у фігурних дужках:\n\n"
        "Приклад:\n"
        "<code>🔥 ОНОВЛЕННЯ АСОРТИМЕНТУ!\n"
        "📦 Товар: {title}\n"
        "📝 Опис: {description|Опис відсутній}\n"
        "💰 Вартість: {price}</code>"
    )
    await message.answer(text, reply_markup=get_cancel_only_kb(), parse_mode="HTML")


@router.message(TemplateWizardFSM.waiting_for_body, F.text)
async def enter_template_body(message: Message, state: FSMContext):
    body = message.text.strip()
    data = await state.get_data()
    await state.clear()

    tpl_name = data.get("tpl_name", "Шаблон")
    tpl_platform = data.get("tpl_platform", "universal")
    tpl_title = data.get("tpl_title")

    async with async_session_maker() as session:
        new_tpl = TemplateModel(
            name=tpl_name,
            platform=tpl_platform,
            title_template=tpl_title,
            body_template=body
        )
        session.add(new_tpl)
        await session.commit()
        await session.refresh(new_tpl)
        tpl_id = new_tpl.id

    text = f"✅ <b>Шаблон #{tpl_id} «{tpl_name}» успішно збережено!</b>"
    await message.answer(text, reply_markup=get_template_manage_kb(tpl_id), parse_mode="HTML")
