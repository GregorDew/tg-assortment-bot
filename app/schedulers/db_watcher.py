import logging
from aiogram import Bot
from sqlalchemy import select
from app.config import settings
from app.database.database import async_session_maker
from app.database.models import Product
from app.services.settings_service import SettingsService
from app.services.product_service import ProductService
from app.services.publisher import PublisherService
from app.services.delivery import broadcast_product, format_broadcast_report
from app.keyboards.admin_kb import get_preview_moderation_kb

logger = logging.getLogger(__name__)


async def check_and_process_db_updates(bot: Bot) -> None:
    """
    Фонова задача для моніторингу оновлень асортименту в базі даних.
    Виконується періодично через планувальник APScheduler.
    """
    try:
        async with async_session_maker() as session:
            # 1. Перевіряємо поточний статус режиму автопостингу
            auto_post_enabled = await SettingsService.get_auto_post_status(session)

            # 2. Отримуємо нові товари з БД зі статусом 'pending'
            result = await session.execute(
                select(Product)
                .where(Product.status == "pending", Product.source == "db")
                .order_by(Product.created_at.asc())
            )
            pending_products = list(result.scalars().all())

            if not pending_products:
                return

            logger.info(
                f"Знайдено {len(pending_products)} нових оновлень у БД. "
                f"Режим автопостингу: {'УВІМКНЕНО' if auto_post_enabled else 'ВИМКНЕНО'}"
            )

            for product in pending_products:
                if auto_post_enabled:
                    try:
                        outcome = await broadcast_product(session, bot, product)
                        report = format_broadcast_report(
                            f"⚡ Автопост товару #{product.id} «{product.title}»",
                            outcome,
                        )
                        if outcome.get("ok"):
                            await ProductService.update_product_status(
                                session=session,
                                product_id=product.id,
                                status="published",
                                moderated_by="🤖 Автопост"
                            )
                        else:
                            logger.error(f"Автопост товару #{product.id} не вдався: {outcome}")

                        for admin_id in settings.ADMIN_IDS:
                            try:
                                await bot.send_message(
                                    chat_id=admin_id,
                                    text=report,
                                    parse_mode="HTML"
                                )
                            except Exception as adm_err:
                                logger.warning(f"Не вдалося сповістити адміна {admin_id}: {adm_err}")

                    except Exception as pub_err:
                        logger.error(f"Помилка автопостингу товару #{product.id}: {pub_err}")

                else:
                    # РЕЖИМ 2: Ручне підтвердження (прев'ю розсилається всім адмінам)
                    await ProductService.update_product_status(
                        session=session,
                        product_id=product.id,
                        status="waiting_approval"
                    )

                    for admin_id in settings.ADMIN_IDS:
                        try:
                            await bot.send_message(
                                chat_id=admin_id,
                                text="🔔 <b>Нове надходження товару з бази даних!</b> Потрібна модерація:",
                                parse_mode="HTML"
                            )
                            await PublisherService.send_product_post(
                                bot=bot,
                                chat_id=admin_id,
                                product=product,
                                is_preview=True,
                                reply_markup=get_preview_moderation_kb(product.id, settings.MANAGER_USERNAME)
                            )
                        except Exception as adm_err:
                            logger.warning(f"Не вдалося надіслати прев'ю адміну {admin_id}: {adm_err}")

    except Exception as e:
        logger.error(f"Помилка у фоновому воркері моніторингу БД: {e}", exc_info=True)
