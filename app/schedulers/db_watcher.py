import json
import logging
from datetime import datetime
from aiogram import Bot
from sqlalchemy import select
from app.config import settings
from app.database.database import async_session_maker
from app.database.models import Product, DataSourceModel
from app.core.security import decrypt_secret
from app.core.sources.factory import create_data_source
from app.services.settings_service import SettingsService
from app.services.product_service import ProductService
from app.services.publisher import PublisherService
from app.services.delivery import broadcast_product, format_broadcast_report
from app.keyboards.admin_kb import get_preview_moderation_kb

logger = logging.getLogger(__name__)


async def sync_external_data_sources(session, bot: Bot) -> None:
    """
    Опитує всі активні зовнішні джерела даних (PostgreSQL, MySQL, SQLite, HTTP API)
    та імпортує нові товари у чергу модерації 'pending'.
    """
    src_res = await session.execute(
        select(DataSourceModel).where(DataSourceModel.is_active.is_(True))
    )
    active_sources = list(src_res.scalars().all())
    if not active_sources:
        return

    for src in active_sources:
        if not src.selected_table or not src.pk_field:
            continue

        try:
            cfg = json.loads(decrypt_secret(src.config_json))
            adapter = create_data_source(src.type, cfg)

            fields = []
            if src.selected_fields:
                try:
                    fields = json.loads(src.selected_fields)
                except Exception:
                    fields = []

            # Отримуємо записи з джерела
            records = await adapter.fetch_records(
                table_name=src.selected_table,
                fields=fields,
                pk_field=src.pk_field,
                tracking_mode="full_diff",  # отримуємо всі наявні записи таблиці
                limit=100
            )

            # Перевіряємо кожен запис
            for rec in records:
                source_record_id = f"src_{src.id}_{rec.id}"
                # Перевіряємо, чи ми вже імпортували цей запис
                existing = await session.execute(
                    select(Product).where(Product.source == source_record_id)
                )
                if existing.scalar_one_or_none():
                    continue

                # Новий товар! Витягуємо поля
                title = (
                    rec.data.get("title")
                    or rec.data.get("name")
                    or rec.data.get("item_name")
                    or f"Товар #{rec.id}"
                )
                description = (
                    rec.data.get("description")
                    or rec.data.get("desc")
                    or rec.data.get("details")
                    or ""
                )
                price = (
                    rec.data.get("price")
                    or rec.data.get("cost")
                    or ""
                )
                photo_file_id = (
                    rec.data.get("photo_file_id")
                    or rec.data.get("file_id")
                    or None
                )
                photo_url = (
                    rec.data.get("photo_url")
                    or rec.data.get("image_url")
                    or rec.data.get("image")
                    or None
                )

                new_product = Product(
                    title=str(title),
                    description=str(description) if description else None,
                    price=str(price) if price else None,
                    photo_file_id=str(photo_file_id) if photo_file_id else None,
                    photo_url=str(photo_url) if photo_url else None,
                    source=source_record_id,
                    status="pending",
                    created_at=datetime.utcnow()
                )
                session.add(new_product)
                await session.commit()
                logger.info(f"Імпортовано новий товар #{new_product.id} з джерела '{src.name}' (ID={src.id})")

            src.last_sync_at = datetime.utcnow()
            src.last_error = None
            await session.commit()

        except Exception as src_err:
            logger.error(f"Помилка опитування джерела '{src.name}' (ID={src.id}): {src_err}")
            src.last_error = str(src_err)[:300]
            await session.commit()


async def check_and_process_db_updates(bot: Bot) -> None:
    """
    Фонова задача для моніторингу оновлень асортименту в базі даних.
    Виконується періодично через планувальник APScheduler.
    """
    try:
        async with async_session_maker() as session:
            # 1. Синхронізуємо підключені джерела даних
            await sync_external_data_sources(session, bot)

            # 2. Перевіряємо поточний статус режиму автопостингу
            auto_post_enabled = await SettingsService.get_auto_post_status(session)

            # 3. Отримуємо нові товари зі статусом 'pending'
            result = await session.execute(
                select(Product)
                .where(Product.status == "pending")
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
