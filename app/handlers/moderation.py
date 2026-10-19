import html
import json
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from app.config import settings
from app.filters.admin import IsAdminFilter
from app.database.database import async_session_maker
from app.database.models import Product, PendingPublicationModel, PublishRuleModel
from app.services.product_service import ProductService
from app.services.publisher import PublisherService
from app.states.manual_post import EditProductFSM
from app.keyboards.admin_kb import (
    get_preview_moderation_kb,
    get_edit_menu_kb,
    get_cancel_edit_kb
)
from app.core.connectors.base import PreparedPost
from app.core.rules.engine import dispatch_to_channels

router = Router()
router.callback_query.filter(IsAdminFilter())
router.message.filter(IsAdminFilter())


# ---------------------------------------------------------------------------
# 1. ПУБЛІКАЦІЯ
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("mod:publish:"))
async def process_publish_decision(callback: CallbackQuery, state: FSMContext):
    """Обробка підтвердження публікації посту в цільову групу/канал."""
    await state.clear()
    item_id = int(callback.data.split(":")[2])
    admin_name = f"@{callback.from_user.username}" if callback.from_user.username else f"ID: {callback.from_user.id}"

    async with async_session_maker() as session:
        # 1. Перевіряємо, чи це універсальна публікація з правил (PendingPublicationModel)
        res_pending = await session.execute(
            select(PendingPublicationModel).where(PendingPublicationModel.id == item_id)
        )
        pending = res_pending.scalar_one_or_none()

        if pending:
            if pending.status in ("published", "rejected"):
                status_text = "опубліковано" if pending.status == "published" else "відхилено"
                await callback.answer(f"⚠️ Цей запис уже {status_text} ({pending.moderated_by or 'іншим адміном'})!", show_alert=True)
                return

            rule_res = await session.execute(select(PublishRuleModel).where(PublishRuleModel.id == pending.rule_id))
            rule = rule_res.scalar_one_or_none()
            channel_ids = json.loads(rule.channel_ids_json) if rule and rule.channel_ids_json else []

            prep_data = json.loads(pending.prepared_data_json)
            post = PreparedPost(
                title=prep_data.get("title"),
                body=prep_data.get("body", ""),
                photo_url=prep_data.get("photo_url"),
                manager_button_url=prep_data.get("manager_button_url")
            )

            await dispatch_to_channels(
                session=session,
                bot=callback.bot,
                channel_ids=channel_ids,
                post=post,
                rule_id=pending.rule_id,
                source_id=pending.source_id,
                record_id=pending.record_id,
                event_type=pending.event_type
            )

            pending.status = "published"
            pending.moderated_by = admin_name
            pending.moderated_at = datetime.utcnow()
            await session.commit()

            await callback.answer("✅ Успішно опубліковано у всі канали правила!", show_alert=True)
            status_suffix = f"\n\n━━━━━━━━━━━━━━━━━━━━\n✅ <b>ОПУБЛІКОВАНО В КАНАЛИ ПРАВИЛА</b>\n👤 Адмін: {html.escape(admin_name)}"
            new_caption = (callback.message.caption or callback.message.text or "") + status_suffix
            try:
                if callback.message.photo:
                    await callback.message.edit_caption(caption=new_caption, reply_markup=None, parse_mode="HTML")
                else:
                    await callback.message.edit_text(text=new_caption, reply_markup=None, parse_mode="HTML")
            except Exception:
                pass
            return

        # 2. Наявний товар (Product)
        product = await ProductService.get_product_by_id(session, item_id)
        if not product:
            await callback.answer("⚠️ Запис не знайдено в базі даних!", show_alert=True)
            return

        # Захист від повторної обробки різними адмінами
        if product.status in ("published", "rejected"):
            status_text = "опубліковано" if product.status == "published" else "відхилено"
            await callback.answer(
                f"⚠️ Цей пост уже був {status_text} адміністратором ({product.moderated_by or 'невідомо'})!",
                show_alert=True
            )
            return

        # Публікація в цільову групу / канал
        try:
            await PublisherService.send_product_post(
                bot=callback.bot,
                chat_id=settings.TARGET_CHAT_ID,
                product=product,
                is_preview=False
            )
        except Exception as e:
            await callback.answer(f"❌ Помилка публікації: {e}", show_alert=True)
            return

        # Оновлення статусу в базі даних
        await ProductService.update_product_status(
            session=session,
            product_id=item_id,
            status="published",
            moderated_by=admin_name
        )

    await callback.answer("✅ Пост успішно опубліковано в групу!", show_alert=True)

    status_suffix = f"\n\n━━━━━━━━━━━━━━━━━━━━\n✅ <b>ОПУБЛІКОВАНО В ГРУПУ</b>\n👤 Адміністратор: {html.escape(admin_name)}"
    new_caption = (callback.message.caption or callback.message.text or "") + status_suffix

    try:
        if callback.message.photo:
            await callback.message.edit_caption(caption=new_caption, reply_markup=None, parse_mode="HTML")
        else:
            await callback.message.edit_text(text=new_caption, reply_markup=None, parse_mode="HTML")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 2. ВІДХИЛЕННЯ
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("mod:reject:"))
async def process_reject_decision(callback: CallbackQuery, state: FSMContext):
    """Обробка відхилення публікації посту."""
    await state.clear()
    item_id = int(callback.data.split(":")[2])
    admin_name = f"@{callback.from_user.username}" if callback.from_user.username else f"ID: {callback.from_user.id}"

    async with async_session_maker() as session:
        # Перевірка PendingPublicationModel
        res_pending = await session.execute(
            select(PendingPublicationModel).where(PendingPublicationModel.id == item_id)
        )
        pending = res_pending.scalar_one_or_none()
        if pending:
            if pending.status in ("published", "rejected"):
                status_text = "опубліковано" if pending.status == "published" else "відхилено"
                await callback.answer(f"⚠️ Цей запис уже {status_text} ({pending.moderated_by or 'невідомо'})!", show_alert=True)
                return

            pending.status = "rejected"
            pending.moderated_by = admin_name
            pending.moderated_at = datetime.utcnow()
            await session.commit()
            await callback.answer("❌ Публікацію відхилено.", show_alert=True)

            status_suffix = f"\n\n━━━━━━━━━━━━━━━━━━━━\n❌ <b>ВІДХИЛЕНО</b>\n👤 Адміністратор: {html.escape(admin_name)}"
            new_caption = (callback.message.caption or callback.message.text or "") + status_suffix
            try:
                if callback.message.photo:
                    await callback.message.edit_caption(caption=new_caption, reply_markup=None, parse_mode="HTML")
                else:
                    await callback.message.edit_text(text=new_caption, reply_markup=None, parse_mode="HTML")
            except Exception:
                pass
            return

        # Наявний товар (Product)
        product = await ProductService.get_product_by_id(session, item_id)
        if not product:
            await callback.answer("⚠️ Запис не знайдено!", show_alert=True)
            return

        if product.status in ("published", "rejected"):
            status_text = "опубліковано" if product.status == "published" else "відхилено"
            await callback.answer(f"⚠️ Цей пост уже був {status_text} ({product.moderated_by or 'невідомо'})!", show_alert=True)
            return

        await ProductService.update_product_status(
            session=session,
            product_id=item_id,
            status="rejected",
            moderated_by=admin_name
        )

    await callback.answer("❌ Публікацію відхилено.", show_alert=True)

    status_suffix = f"\n\n━━━━━━━━━━━━━━━━━━━━\n❌ <b>ВІДХИЛЕНО</b>\n👤 Адміністратор: {html.escape(admin_name)}"
    new_caption = (callback.message.caption or callback.message.text or "") + status_suffix

    try:
        if callback.message.photo:
            await callback.message.edit_caption(caption=new_caption, reply_markup=None, parse_mode="HTML")
        else:
            await callback.message.edit_text(text=new_caption, reply_markup=None, parse_mode="HTML")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 3. РЕДАГУВАННЯ ПОСТА НА ЕТАПІ ПОГОДЖЕННЯ
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("mod:edit:"))
async def open_edit_menu(callback: CallbackQuery):
    """Відкриває меню вибору поля для редагування."""
    item_id = int(callback.data.split(":")[2])

    async with async_session_maker() as session:
        res_pending = await session.execute(
            select(PendingPublicationModel).where(PendingPublicationModel.id == item_id)
        )
        pending = res_pending.scalar_one_or_none()
        if pending and pending.status in ("published", "rejected"):
            await callback.answer("⚠️ Цей пост уже опубліковано або відхилено!", show_alert=True)
            return

        if not pending:
            product = await ProductService.get_product_by_id(session, item_id)
            if not product:
                await callback.answer("⚠️ Запис не знайдено!", show_alert=True)
                return
            if product.status in ("published", "rejected"):
                await callback.answer("⚠️ Цей пост уже опубліковано або відхилено!", show_alert=True)
                return

    try:
        await callback.message.edit_reply_markup(reply_markup=get_edit_menu_kb(item_id))
    except Exception:
        pass
    await callback.answer("✏️ Оберіть поле для редагування")


@router.callback_query(F.data.startswith("edit_f:back:"))
async def back_to_moderation(callback: CallbackQuery, state: FSMContext):
    """Повертає стандартну клавіатуру прев'ю з модерацією."""
    await state.clear()
    product_id = int(callback.data.split(":")[2])

    try:
        await callback.message.edit_reply_markup(
            reply_markup=get_preview_moderation_kb(product_id, settings.MANAGER_USERNAME)
        )
    except Exception:
        pass
    await callback.answer("Повернуто до погодження")


# --- Редагування назви ---
@router.callback_query(F.data.startswith("edit_f:title:"))
async def start_edit_title(callback: CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split(":")[2])
    await state.set_state(EditProductFSM.waiting_for_new_title)
    await state.update_data(editing_product_id=product_id)

    await callback.message.answer(
        "✏️ <b>Введіть нову назву товару:</b>",
        reply_markup=get_cancel_edit_kb(product_id),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(EditProductFSM.waiting_for_new_title, F.text)
async def process_new_title(message: Message, state: FSMContext):
    data = await state.get_data()
    product_id = data.get("editing_product_id")
    await state.clear()

    new_title = message.text.strip()
    async with async_session_maker() as session:
        product = await ProductService.update_product_fields(session, product_id, title=new_title)

    await message.answer("✅ Назву товару успішно змінено!")
    if product:
        await PublisherService.send_product_post(
            bot=message.bot,
            chat_id=message.chat.id,
            product=product,
            is_preview=True,
            reply_markup=get_preview_moderation_kb(product.id, settings.MANAGER_USERNAME)
        )


# --- Редагування опису ---
@router.callback_query(F.data.startswith("edit_f:desc:"))
async def start_edit_desc(callback: CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split(":")[2])
    await state.set_state(EditProductFSM.waiting_for_new_description)
    await state.update_data(editing_product_id=product_id)

    await callback.message.answer(
        "📝 <b>Введіть новий опис товару:</b>",
        reply_markup=get_cancel_edit_kb(product_id),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(EditProductFSM.waiting_for_new_description, F.text)
async def process_new_description(message: Message, state: FSMContext):
    data = await state.get_data()
    product_id = data.get("editing_product_id")
    await state.clear()

    new_desc = message.text.strip()
    async with async_session_maker() as session:
        product = await ProductService.update_product_fields(session, product_id, description=new_desc)

    await message.answer("✅ Опис товару успішно змінено!")
    if product:
        await PublisherService.send_product_post(
            bot=message.bot,
            chat_id=message.chat.id,
            product=product,
            is_preview=True,
            reply_markup=get_preview_moderation_kb(product.id, settings.MANAGER_USERNAME)
        )


# --- Редагування ціни ---
@router.callback_query(F.data.startswith("edit_f:price:"))
async def start_edit_price(callback: CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split(":")[2])
    await state.set_state(EditProductFSM.waiting_for_new_price)
    await state.update_data(editing_product_id=product_id)

    await callback.message.answer(
        "💰 <b>Введіть нову ціну товару</b> (або надішліть <code>-</code>, щоб прибрати ціну):",
        reply_markup=get_cancel_edit_kb(product_id),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(EditProductFSM.waiting_for_new_price, F.text)
async def process_new_price(message: Message, state: FSMContext):
    data = await state.get_data()
    product_id = data.get("editing_product_id")
    await state.clear()

    raw_price = message.text.strip()
    new_price = None if raw_price == "-" else raw_price

    async with async_session_maker() as session:
        product = await ProductService.update_product_fields(session, product_id, price=new_price)

    await message.answer("✅ Ціну товару успішно оновлено!")
    if product:
        await PublisherService.send_product_post(
            bot=message.bot,
            chat_id=message.chat.id,
            product=product,
            is_preview=True,
            reply_markup=get_preview_moderation_kb(product.id, settings.MANAGER_USERNAME)
        )


# --- Редагування фото ---
@router.callback_query(F.data.startswith("edit_f:photo:"))
async def start_edit_photo(callback: CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split(":")[2])
    await state.set_state(EditProductFSM.waiting_for_new_photo)
    await state.update_data(editing_product_id=product_id)

    await callback.message.answer(
        "📸 <b>Надішліть нову фотографію для товару:</b>\n"
        "(або натисніть кнопку нижче, щоб видалити фото чи скасувати)",
        reply_markup=get_cancel_edit_kb(product_id, allow_remove_photo=True),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("edit_f:remove_photo:"))
async def process_remove_photo(callback: CallbackQuery, state: FSMContext):
    """Видаляє фотографію у товару, роблячи його чисто текстовим."""
    await state.clear()
    product_id = int(callback.data.split(":")[2])

    async with async_session_maker() as session:
        product = await ProductService.update_product_fields(session, product_id, clear_photo=True)

    await callback.answer("🗑 Фото товару видалено!", show_alert=True)
    if product:
        await PublisherService.send_product_post(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            product=product,
            is_preview=True,
            reply_markup=get_preview_moderation_kb(product.id, settings.MANAGER_USERNAME)
        )


@router.message(EditProductFSM.waiting_for_new_photo, F.photo)
async def process_new_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    product_id = data.get("editing_product_id")
    await state.clear()

    photo_file_id = message.photo[-1].file_id
    async with async_session_maker() as session:
        product = await ProductService.update_product_fields(session, product_id, photo_file_id=photo_file_id)

    await message.answer("✅ Фотографію товару успішно замінено!")
    if product:
        await PublisherService.send_product_post(
            bot=message.bot,
            chat_id=message.chat.id,
            product=product,
            is_preview=True,
            reply_markup=get_preview_moderation_kb(product.id, settings.MANAGER_USERNAME)
        )


@router.message(EditProductFSM.waiting_for_new_photo)
async def invalid_new_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    product_id = data.get("editing_product_id", 0)
    await message.answer(
        "⚠️ Будь ласка, надішліть фотографію або скористайтесь кнопкою скасування.",
        reply_markup=get_cancel_edit_kb(product_id, allow_remove_photo=True)
    )
