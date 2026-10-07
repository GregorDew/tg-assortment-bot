import html
from aiogram import Router, F
from aiogram.types import CallbackQuery
from app.config import settings
from app.filters.admin import IsAdminFilter
from app.database.database import async_session_maker
from app.services.product_service import ProductService
from app.services.publisher import PublisherService

router = Router()
router.callback_query.filter(IsAdminFilter())


@router.callback_query(F.data.startswith("mod:publish:"))
async def process_publish_decision(callback: CallbackQuery):
    """Обробка підтвердження публікації посту в цільову групу/канал."""
    product_id = int(callback.data.split(":")[2])
    admin_name = f"@{callback.from_user.username}" if callback.from_user.username else f"ID: {callback.from_user.id}"

    async with async_session_maker() as session:
        product = await ProductService.get_product_by_id(session, product_id)

        if not product:
            await callback.answer("⚠️ Товар не знайдено в базі даних!", show_alert=True)
            return

        # Захист від повторної обробки різними адмінами
        if product.status in ("published", "rejected"):
            status_text = "опубліковано" if product.status == "published" else "відхилено"
            await callback.answer(
                f"⚠️ Цей пост уже був {status_text} адміністратором ({product.moderated_by or 'невідомо'})!",
                show_alert=True
            )
            return

        # 1. Публікація в цільову групу / канал
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

        # 2. Оновлення статусу в базі даних
        await ProductService.update_product_status(
            session=session,
            product_id=product_id,
            status="published",
            moderated_by=admin_name
        )

    await callback.answer("✅ Пост успішно опубліковано в групу!", show_alert=True)

    # 3. Оновлення повідомлення попереднього перегляду у чаті адміна
    status_suffix = f"\n\n━━━━━━━━━━━━━━━━━━━━\n✅ <b>ОПУБЛІКОВАНО В ГРУПУ</b>\n👤 Адміністратор: {html.escape(admin_name)}"
    new_caption = (callback.message.caption or callback.message.text or "") + status_suffix

    try:
        if callback.message.photo:
            await callback.message.edit_caption(
                caption=new_caption,
                reply_markup=None,
                parse_mode="HTML"
            )
        else:
            await callback.message.edit_text(
                text=new_caption,
                reply_markup=None,
                parse_mode="HTML"
            )
    except Exception:
        pass


@router.callback_query(F.data.startswith("mod:reject:"))
async def process_reject_decision(callback: CallbackQuery):
    """Обробка відхилення публікації посту."""
    product_id = int(callback.data.split(":")[2])
    admin_name = f"@{callback.from_user.username}" if callback.from_user.username else f"ID: {callback.from_user.id}"

    async with async_session_maker() as session:
        product = await ProductService.get_product_by_id(session, product_id)

        if not product:
            await callback.answer("⚠️ Товар не знайдено в базі даних!", show_alert=True)
            return

        # Захист від повторної обробки
        if product.status in ("published", "rejected"):
            status_text = "опубліковано" if product.status == "published" else "відхилено"
            await callback.answer(
                f"⚠️ Цей пост уже був {status_text} адміністратором ({product.moderated_by or 'невідомо'})!",
                show_alert=True
            )
            return

        # Оновлення статусу на 'rejected'
        await ProductService.update_product_status(
            session=session,
            product_id=product_id,
            status="rejected",
            moderated_by=admin_name
        )

    await callback.answer("❌ Публікацію відхилено.", show_alert=True)

    status_suffix = f"\n\n━━━━━━━━━━━━━━━━━━━━\n❌ <b>ВІДХИЛЕНО</b>\n👤 Адміністратор: {html.escape(admin_name)}"
    new_caption = (callback.message.caption or callback.message.text or "") + status_suffix

    try:
        if callback.message.photo:
            await callback.message.edit_caption(
                caption=new_caption,
                reply_markup=None,
                parse_mode="HTML"
            )
        else:
            await callback.message.edit_text(
                text=new_caption,
                reply_markup=None,
                parse_mode="HTML"
            )
    except Exception:
        pass
