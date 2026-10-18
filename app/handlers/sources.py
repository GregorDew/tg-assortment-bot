import json
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy import select

from app.filters.admin import IsAdminFilter
from app.database.database import async_session_maker
from app.database.models import DataSourceModel
from app.core.security import encrypt_secret, decrypt_secret, mask_secret
from app.core.sources.factory import create_data_source
from app.states.sources_fsm import SourceWizardFSM
from app.keyboards.sources_kb import (
    get_sources_menu_kb,
    get_source_types_kb,
    get_tracking_mode_kb,
    get_items_selection_kb,
    get_source_manage_kb,
    get_delete_confirm_kb
)
from app.keyboards.admin_kb import get_cancel_only_kb

logger = logging.getLogger(__name__)

router = Router()
router.message.filter(IsAdminFilter())
router.callback_query.filter(IsAdminFilter())


# ---------------------------------------------------------------------------
# ГОЛОВНЕ МЕНЮ ДЖЕРЕЛ ТА СПИСОК
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "menu:sources")
@router.callback_query(F.data == "src:menu")
async def show_sources_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    text = (
        "🗄 <b>Керування джерелами даних</b>\n\n"
        "Тут ви можете підключати зовнішні бази даних (PostgreSQL, MySQL, SQLite) "
        "та HTTP API для автоматичного отримання та моніторингу записів."
    )
    await callback.message.edit_text(text, reply_markup=get_sources_menu_kb(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "src:list")
async def list_sources(callback: CallbackQuery):
    async with async_session_maker() as session:
        res = await session.execute(select(DataSourceModel).order_by(DataSourceModel.id.desc()))
        sources = list(res.scalars().all())

    if not sources:
        text = "ℹ️ У вас ще немає підключених джерел даних. Натисніть «Додати джерело»."
        await callback.message.edit_text(text, reply_markup=get_sources_menu_kb(), parse_mode="HTML")
        await callback.answer()
        return

    lines = ["📋 <b>Ваші підключені джерела даних:</b>\n"]
    for s in sources:
        status_ico = "🟢 Активне" if s.is_active else "🔴 Вимкнено"
        err_note = f" (Помилка: {s.last_error[:30]}...)" if s.last_error else ""
        lines.append(
            f"• <b>#{s.id} {s.name}</b> ({s.type})\n"
            f"   Таблиця: <code>{s.selected_table or 'не вибрано'}</code> | {status_ico}{err_note}\n"
        )
    text = "\n".join(lines) + "\nОберіть джерело для керування:"

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb_rows = []
    for s in sources[:8]:
        kb_rows.append([InlineKeyboardButton(text=f"⚙️ #{s.id} {s.name[:20]}", callback_data=f"src_view:{s.id}")])
    kb_rows.append([InlineKeyboardButton(text="➕ Додати нове", callback_data="src:add")])
    kb_rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="src:menu")])

    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("src_view:"))
async def view_source_details(callback: CallbackQuery):
    source_id = int(callback.data.split(":")[1])
    async with async_session_maker() as session:
        res = await session.execute(select(DataSourceModel).where(DataSourceModel.id == source_id))
        s = res.scalar_one_or_none()

    if not s:
        await callback.answer("⚠️ Джерело не знайдено!", show_alert=True)
        return

    status_str = "🟢 Активне" if s.is_active else "🔴 Вимкнено"
    last_sync = s.last_sync_at.strftime('%Y-%m-%d %H:%M:%S') if s.last_sync_at else "Ще не виконувалось"
    err_info = f"\n⚠️ <b>Остання помилка:</b> <code>{s.last_error}</code>" if s.last_error else ""

    text = (
        f"🗄 <b>Джерело даних: {s.name}</b>\n"
        f"───────────────────────\n"
        f"• <b>Тип:</b> {s.type}\n"
        f"• <b>Таблиця:</b> <code>{s.selected_table or 'Всі'}</code>\n"
        f"• <b>PK колонка:</b> <code>{s.pk_field or 'id'}</code>\n"
        f"• <b>Режим змін:</b> <code>{s.change_tracking_mode}</code>\n"
        f"• <b>Статус:</b> {status_str}\n"
        f"• <b>Остання синхронізація:</b> {last_sync}"
        f"{err_info}"
    )
    await callback.message.edit_text(text, reply_markup=get_source_manage_kb(s.id, s.is_active), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("src_action:toggle:"))
async def toggle_source(callback: CallbackQuery):
    source_id = int(callback.data.split(":")[2])
    async with async_session_maker() as session:
        res = await session.execute(select(DataSourceModel).where(DataSourceModel.id == source_id))
        s = res.scalar_one_or_none()
        if s:
            s.is_active = not s.is_active
            await session.commit()
            st = "увімкнено" if s.is_active else "вимкнено"
            await callback.answer(f"Джерело {st}!", show_alert=True)
    await view_source_details(callback)


@router.callback_query(F.data.startswith("src_action:test:"))
async def test_existing_source(callback: CallbackQuery):
    source_id = int(callback.data.split(":")[2])
    async with async_session_maker() as session:
        res = await session.execute(select(DataSourceModel).where(DataSourceModel.id == source_id))
        s = res.scalar_one_or_none()

    if not s:
        await callback.answer("Джерело не знайдено!", show_alert=True)
        return

    await callback.answer("⏳ Перевірка з'єднання...")
    try:
        cfg = json.loads(decrypt_secret(s.config_json))
        adapter = create_data_source(s.type, cfg)
        ok, msg = await adapter.test_connection()
        if ok:
            await callback.message.answer(f"✅ <b>Тест з'єднання успішний:</b>\n{msg}", parse_mode="HTML")
        else:
            await callback.message.answer(f"❌ <b>Помилка з'єднання:</b>\n{msg}", parse_mode="HTML")
    except Exception as e:
        await callback.message.answer(f"❌ <b>Помилка тесту:</b> {e}")


@router.callback_query(F.data.startswith("src_action:sample:"))
async def sample_existing_source(callback: CallbackQuery):
    source_id = int(callback.data.split(":")[2])
    async with async_session_maker() as session:
        res = await session.execute(select(DataSourceModel).where(DataSourceModel.id == source_id))
        s = res.scalar_one_or_none()

    if not s:
        await callback.answer("Джерело не знайдено!", show_alert=True)
        return

    await callback.answer("⏳ Отримання зразка даних...")
    try:
        cfg = json.loads(decrypt_secret(s.config_json))
        adapter = create_data_source(s.type, cfg)
        fields = json.loads(s.selected_fields) if s.selected_fields else []
        records = await adapter.fetch_records(
            table_name=s.selected_table or "",
            fields=fields,
            pk_field=s.pk_field or "id",
            limit=1
        )
        if records:
            sample = json.dumps(records[0].data, indent=2, ensure_ascii=False)
            await callback.message.answer(f"👁 <b>Зразок першого запису:</b>\n<pre>{sample[:1000]}</pre>", parse_mode="HTML")
        else:
            await callback.message.answer("ℹ️ Джерело підключено, але таблиця порожня (0 записів).")
    except Exception as e:
        await callback.message.answer(f"❌ <b>Помилка вибірки зразка:</b> {e}")


@router.callback_query(F.data.startswith("src_action:delete_confirm:"))
async def confirm_delete_source(callback: CallbackQuery):
    source_id = int(callback.data.split(":")[2])
    text = (
        f"⚠️ <b>Ви дійсно бажаєте видалити джерело #{source_id}?</b>\n\n"
        "Усі пов'язані правила публікації та історія будуть також видалені!"
    )
    await callback.message.edit_text(text, reply_markup=get_delete_confirm_kb("source", source_id), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("del_confirm:source:"))
async def execute_delete_source(callback: CallbackQuery):
    source_id = int(callback.data.split(":")[2])
    async with async_session_maker() as session:
        res = await session.execute(select(DataSourceModel).where(DataSourceModel.id == source_id))
        s = res.scalar_one_or_none()
        if s:
            await session.delete(s)
            await session.commit()
    await callback.answer("✅ Джерело видалено!", show_alert=True)
    await list_sources(callback)


@router.callback_query(F.data.startswith("del_cancel:source:"))
async def cancel_delete_source(callback: CallbackQuery):
    await view_source_details(callback)


# ---------------------------------------------------------------------------
# 10-ЕТАПНИЙ МАЙСТЕР СТВОРЕННЯ ДЖЕРЕЛА ДАНИХ
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "src:add")
async def wizard_step1_type(callback: CallbackQuery, state: FSMContext):
    """Крок 1: Вибір типу джерела."""
    await state.clear()
    await state.set_state(SourceWizardFSM.waiting_for_type)
    text = (
        "🧙‍♂️ <b>Майстер підключення джерела даних (Крок 1/10)</b>\n\n"
        "Оберіть тип джерела, з якого необхідно отримувати дані:"
    )
    await callback.message.edit_text(text, reply_markup=get_source_types_kb(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(SourceWizardFSM.waiting_for_type, F.data.startswith("src_type:"))
async def wizard_step2_name(callback: CallbackQuery, state: FSMContext):
    """Крок 2: Введення назви підключення."""
    src_type = callback.data.split(":")[1]
    await state.update_data(src_type=src_type)
    await state.set_state(SourceWizardFSM.waiting_for_name)

    type_names = {
        "postgres": "PostgreSQL",
        "mysql": "MySQL",
        "sqlite": "SQLite / SQL",
        "http_api": "HTTP API"
    }
    text = (
        f"Тип: <b>{type_names.get(src_type, src_type)}</b>\n\n"
        "📝 <b>Крок 2/10: Назва підключення</b>\n"
        "Введіть зрозумілу назву для цього джерела (наприклад: <code>Основний склад</code> або <code>CRM Товари</code>):"
    )
    await callback.message.answer(text, reply_markup=get_cancel_only_kb(), parse_mode="HTML")
    await callback.answer()


@router.message(SourceWizardFSM.waiting_for_name, F.text)
async def wizard_step3_params(message: Message, state: FSMContext):
    """Крок 3: Введення параметрів підключення."""
    name = message.text.strip()
    await state.update_data(src_name=name)
    data = await state.get_data()
    src_type = data.get("src_type")

    await state.set_state(SourceWizardFSM.waiting_for_params)

    if src_type in ("postgres", "mysql"):
        default_port = 5432 if src_type == "postgres" else 3306
        text = (
            f"🔌 <b>Крок 3/10: Параметри підключення {src_type.upper()}</b>\n\n"
            "Надішліть параметри у форматі:\n"
            "<code>host;port;database;user;password</code>\n\n"
            f"Приклад:\n<code>192.168.1.50;{default_port};shop_db;db_user;SuperPass123</code>\n\n"
            "<i>(Пароль зберігається у зашифрованому вигляді через Fernet)</i>"
        )
    elif src_type == "sqlite":
        text = (
            "🔌 <b>Крок 3/10: Параметри підключення SQL</b>\n\n"
            "Введіть SQLAlchemy URL до бази даних:\n"
            "Приклад для локального SQLite:\n"
            "<code>sqlite+aiosqlite:///test_data.db</code>"
        )
    else:  # http_api
        text = (
            "🔌 <b>Крок 3/10: Параметри HTTP API</b>\n\n"
            "Введіть URL кінцевої точки (Endpoint URL):\n"
            "Приклад: <code>https://dummyjson.com/products</code>\n\n"
            "<i>(Якщо потрібен Bearer токен, додайте через пробіл після URL)</i>"
        )

    await message.answer(text, reply_markup=get_cancel_only_kb(), parse_mode="HTML")


@router.message(SourceWizardFSM.waiting_for_params, F.text)
async def wizard_step4_test_and_tables(message: Message, state: FSMContext):
    """Крок 3-4: Перевірка з'єднання та отримання списку таблиць."""
    raw = message.text.strip()
    data = await state.get_data()
    src_type = data.get("src_type")

    config = {}
    if src_type in ("postgres", "mysql"):
        parts = [p.strip() for p in raw.split(";")]
        if len(parts) < 5:
            await message.answer("⚠️ Неправильний формат! Потрібно 5 значень через крапку з комою: host;port;db;user;password")
            return
        config = {
            "host": parts[0],
            "port": int(parts[1]),
            "database": parts[2],
            "user": parts[3],
            "password": parts[4]
        }
    elif src_type == "sqlite":
        config = {"url": raw}
    else:  # http_api
        parts = raw.split()
        config = {"endpoint_url": parts[0], "method": "GET"}
        if len(parts) > 1:
            config["auth_token"] = parts[1]

    # Зберігаємо конфіг
    await state.update_data(src_config=config)

    # Тестуємо з'єднання
    await message.answer("⏳ <b>Крок 3/10: Перевірка з'єднання...</b>", parse_mode="HTML")
    try:
        adapter = create_data_source(src_type, config)
        ok, msg = await adapter.test_connection()
        if not ok:
            await message.answer(f"❌ <b>Помилка підключення:</b>\n{msg}\n\nСпробуйте надіслати параметри ще раз:")
            return
    except Exception as e:
        await message.answer(f"❌ <b>Помилка з'єднання:</b> {e}\n\nСпробуйте надіслати параметри ще раз:")
        return

    # Отримуємо таблиці (Крок 4)
    await message.answer("🔍 <b>Крок 4/10: Отримання доступних таблиць та views...</b>", parse_mode="HTML")
    try:
        tables = await adapter.get_tables_and_views()
        if not tables:
            await message.answer("⚠️ У базі даних не знайдено жодної таблиці. Перевірте дозволи користувача.")
            return

        await state.update_data(available_tables=tables)
        await state.set_state(SourceWizardFSM.waiting_for_table)

        text = "📋 <b>Крок 5/10: Оберіть таблицю або представлення:</b>"
        await message.answer(text, reply_markup=get_items_selection_kb(tables, "pick_tbl"), parse_mode="HTML")
    except Exception as e:
        await message.answer(f"❌ Не вдалося отримати таблиці: {e}")


@router.callback_query(SourceWizardFSM.waiting_for_table, F.data.startswith("pick_tbl:"))
async def wizard_step5_fields(callback: CallbackQuery, state: FSMContext):
    """Крок 5-6: Вибір полів таблиці."""
    table_name = callback.data.split(":", 1)[1]
    await state.update_data(selected_table=table_name)

    data = await state.get_data()
    src_type = data.get("src_type")
    config = data.get("src_config")

    adapter = create_data_source(src_type, config)
    try:
        cols = await adapter.get_table_schema(table_name)
        await state.update_data(available_columns=cols)
        await state.set_state(SourceWizardFSM.waiting_for_fields)

        text = (
            f"Таблиця: <code>{table_name}</code>\n\n"
            f"📊 <b>Крок 6/10: Вибір полів</b>\n"
            f"Знайдено стовпці: <code>{', '.join(cols)}</code>\n\n"
            "Надішліть назви потрібних полів через кому (наприклад: <code>id, title, price, photo_url</code>),\n"
            "або надішліть <code>*</code>, щоб вибрати ВСІ поля:"
        )
        await callback.message.answer(text, reply_markup=get_cancel_only_kb(), parse_mode="HTML")
        await callback.answer()
    except Exception as e:
        await callback.answer(f"Помилка схеми: {e}", show_alert=True)


@router.message(SourceWizardFSM.waiting_for_fields, F.text)
async def wizard_step6_pk(message: Message, state: FSMContext):
    """Крок 7: Визначення Primary Key."""
    raw_fields = message.text.strip()
    data = await state.get_data()
    avail_cols = data.get("available_columns", [])

    if raw_fields == "*":
        selected_fields = avail_cols
    else:
        selected_fields = [f.strip() for f in raw_fields.split(",") if f.strip()]

    await state.update_data(selected_fields=selected_fields)
    await state.set_state(SourceWizardFSM.waiting_for_pk)

    text = (
        "🔑 <b>Крок 7/10: Унікальний ідентифікатор (Primary Key)</b>\n\n"
        "Оберіть або введіть поле, яке є первинним ключем запису:"
    )
    cols_to_show = selected_fields if selected_fields else avail_cols
    await message.answer(text, reply_markup=get_items_selection_kb(cols_to_show, "pick_pk"), parse_mode="HTML")


@router.callback_query(SourceWizardFSM.waiting_for_pk, F.data.startswith("pick_pk:"))
async def wizard_step7_tracking_mode(callback: CallbackQuery, state: FSMContext):
    """Крок 8: Вибір способу виявлення змін."""
    pk_col = callback.data.split(":", 1)[1]
    await state.update_data(pk_field=pk_col)

    await state.set_state(SourceWizardFSM.waiting_for_tracking_mode)
    text = (
        f"Primary Key: <code>{pk_col}</code>\n\n"
        "🔄 <b>Крок 8/10: Спосіб виявлення змін та нових записів</b>\n"
        "Оберіть механізм відстеження:"
    )
    await callback.message.edit_text(text, reply_markup=get_tracking_mode_kb(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(SourceWizardFSM.waiting_for_tracking_mode, F.data.startswith("track_mode:"))
async def wizard_step8_tracking_field(callback: CallbackQuery, state: FSMContext):
    """Крок 9: Визначення колонки відстеження (якщо потрібно) або фінал."""
    mode = callback.data.split(":")[1]
    await state.update_data(change_tracking_mode=mode)

    data = await state.get_data()
    cols = data.get("selected_fields") or data.get("available_columns") or []

    if mode == "updated_at":
        await state.set_state(SourceWizardFSM.waiting_for_tracking_field)
        text = "🕒 <b>Крок 9/10:</b> Оберіть колонку часової мітки оновлення (наприклад, <code>updated_at</code>):"
        await callback.message.edit_text(text, reply_markup=get_items_selection_kb(cols, "pick_tr_col"), parse_mode="HTML")
        await callback.answer()
        return

    # Якщо incremental_id чи row_hash — переходимо до кроку 10
    await state.update_data(tracking_field=data.get("pk_field"))
    await finish_source_wizard(callback.message, state)
    await callback.answer()


@router.callback_query(SourceWizardFSM.waiting_for_tracking_field, F.data.startswith("pick_tr_col:"))
async def wizard_step9_final(callback: CallbackQuery, state: FSMContext):
    tr_col = callback.data.split(":", 1)[1]
    await state.update_data(tracking_field=tr_col)
    await finish_source_wizard(callback.message, state)
    await callback.answer()


async def finish_source_wizard(message: Message, state: FSMContext):
    """Крок 10: Збереження налаштувань, шифрування та тестове отримання даних."""
    data = await state.get_data()
    await state.clear()

    src_name = data.get("src_name", "Нове джерело")
    src_type = data.get("src_type")
    src_config = data.get("src_config", {})
    selected_table = data.get("selected_table")
    selected_fields = data.get("selected_fields", [])
    pk_field = data.get("pk_field", "id")
    track_mode = data.get("change_tracking_mode", "incremental_id")
    track_field = data.get("tracking_field")

    # Шифруємо конфігурацію (включаючи пароль)
    encrypted_cfg = encrypt_secret(json.dumps(src_config))

    # Зберігаємо в базі даних
    async with async_session_maker() as session:
        new_source = DataSourceModel(
            name=src_name,
            type=src_type,
            config_json=encrypted_cfg,
            selected_table=selected_table,
            selected_fields=json.dumps(selected_fields),
            pk_field=pk_field,
            change_tracking_mode=track_mode,
            tracking_field=track_field,
            is_active=True
        )
        session.add(new_source)
        await session.commit()
        await session.refresh(new_source)
        source_id = new_source.id

    # Виконуємо тестове отримання даних (Крок 10)
    sample_text = "Немає записів"
    try:
        adapter = create_data_source(src_type, src_config)
        records = await adapter.fetch_records(
            table_name=selected_table or "",
            fields=selected_fields,
            pk_field=pk_field,
            limit=1
        )
        if records:
            sample_text = json.dumps(records[0].data, indent=2, ensure_ascii=False)
    except Exception as e:
        sample_text = f"Помилка тестової вибірки: {e}"

    summary = (
        "🎉 <b>Джерело даних успішно налаштовано та збережено! (Крок 10/10)</b>\n"
        "───────────────────────\n"
        f"• <b>ID:</b> #{source_id}\n"
        f"• <b>Назва:</b> {src_name}\n"
        f"• <b>Тип:</b> {src_type}\n"
        f"• <b>Таблиця:</b> <code>{selected_table}</code>\n"
        f"• <b>Поля ({len(selected_fields)}):</b> <code>{', '.join(selected_fields[:5])}...</code>\n"
        f"• <b>Primary Key:</b> <code>{pk_field}</code>\n"
        f"• <b>Відстеження змін:</b> <code>{track_mode}</code>\n\n"
        f"👁 <b>Тестовий отриманий запис:</b>\n<pre>{sample_text[:500]}</pre>"
    )
    await message.answer(summary, reply_markup=get_source_manage_kb(source_id, True), parse_mode="HTML")
