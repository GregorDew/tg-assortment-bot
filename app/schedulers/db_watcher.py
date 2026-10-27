import json
import logging
from datetime import datetime
from aiogram import Bot
from sqlalchemy import select
from app.config import settings
from app.database.database import async_session_maker
from app.database.models import Product, DataSourceModel, DeliveryLogModel, PublishChannelModel
from app.core.security import decrypt_secret
from app.core.sources.factory import create_data_source
from app.core.connectors.factory import create_connector
from app.core.connectors.base import PreparedPost
from app.services.settings_service import SettingsService
from app.services.product_service import ProductService
from app.services.publisher import PublisherService
from app.services.delivery import broadcast_product, format_broadcast_report
from app.keyboards.admin_kb import get_preview_moderation_kb

logger = logging.getLogger(__name__)


async def handle_deleted_products(session, bot: Bot, src: DataSourceModel, existing_external_ids: set) -> None:
    """
    Якщо товар був видалений із зовнішньої бази (наприклад, проданий):
    знаходимо його публікації в каналах і оновлюємо підпис на «🔴 НЕМАЄ В НАЯВНОСТІ / ПРОДАНО»
    або видаляємо кнопку замовлення.
    """
    # Знаходимо всі товари, які були імпортовані з цього джерела
    prefix = f"src_{src.id}_"
    res = await session.execute(
        select(Product).where(
            Product.source.startswith(prefix),
            Product.status == "published"
        )
    )
    published_products = list(res.scalars().all())

    for prod in published_products:
        ext_id = prod.source[len(prefix):]
        # Якщо запису більше немає в базі даних (його видалили/купили)
        if ext_id not in existing_external_ids:
            logger.info(f"Товар #{prod.id} (зовнішній id={ext_id}) відсутній у джерелі '{src.name}'. Позначаємо як проданий.")
            prod.status = "out_of_stock"
            await session.commit()

            # Знаходимо всі успішні доставки для цього товару в канали
            logs_res = await session.execute(
                select(DeliveryLogModel).where(
                    DeliveryLogModel.record_id == str(prod.id),
                    DeliveryLogModel.status == "success",
                    DeliveryLogModel.external_message_id.isnot(None)
                )
            )
            logs = list(logs_res.scalars().all())

            # Текст для оновленого посту
            sold_post = PreparedPost(
                title=f"❌ [НЕМАЄ В НАЯВНОСТІ] {prod.title}",
                body=(
                    f"🔴 <b>ТОЙ ТОВАР ВЖЕ ПРОДАНО / НЕМАЄ В НАЯВНОСТІ</b>\n"
                    f"───────────────────────\n"
                    f"<s>{prod.title}</s>\n\n"
                    f"<i>Цей товар вилучено з бази даних наявності.</i>"
                ),
                photo_file_id=prod.photo_file_id,
                photo_url=prod.photo_url,
                manager_button_url=None  # прибираємо кнопку зв'язку
            )

            for log_entry in logs:
                if not log_entry.channel_id:
                    continue
                ch_res = await session.execute(
                    select(PublishChannelModel).where(PublishChannelModel.id == log_entry.channel_id)
                )
                channel = ch_res.scalar_one_or_none()
                if not channel or not channel.is_active:
                    continue

                try:
                    ch_cfg = json.loads(decrypt_secret(channel.config_json))
                    connector = create_connector(channel.type, ch_cfg, bot=bot)
                    await connector.update(log_entry.external_message_id, sold_post)
                    logger.info(f"Оновлено статус товару #{prod.id} на 'немає в наявності' у каналі {channel.name}")
                except Exception as up_err:
                    logger.warning(f"Не вдалося оновити пост у каналі {channel.id}: {up_err}")


async def sync_external_data_sources(session, bot: Bot) -> None:
    """
    Опитує всі активні зовнішні джерела даних (PostgreSQL, MySQL, SQLite, HTTP API)
    та імпортує нові товари у чергу модерації 'pending'.
    Також відстежує товари, які зникли з бази даних (продані), та оновлює їх статус у каналах.
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
            # Завжди додаємо photo_blob, якщо таблиця містить бінарне зображення
            if fields and "photo_blob" not in fields:
                fields.append("photo_blob")

            # Отримуємо всі наявні записи з джерела
            records = await adapter.fetch_records(
                table_name=src.selected_table,
                fields=fields,
                pk_field=src.pk_field,
                tracking_mode="full_diff",
                limit=500
            )

            current_record_ids = set()

            for rec in records:
                current_record_ids.add(str(rec.id))
                source_record_id = f"src_{src.id}_{rec.id}"

                # 1. Перевірка 1: чи імпортували цей унікальний ID раніше
                existing_by_src = await session.execute(
                    select(Product).where(Product.source == source_record_id)
                )
                if existing_by_src.scalar_one_or_none():
                    continue

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
                photo_blob = (
                    rec.data.get("photo_blob")
                    or rec.data.get("photo")
                    or rec.data.get("image_blob")
                    or None
                )

                # 2. Перевірка 2: захист від дублікатів (1 в 1)
                # Якщо вже є товар з такою ж назвою, описом та ціною, який вже опубліковано або очікує
                duplicate_check = await session.execute(
                    select(Product).where(
                        Product.title == str(title),
                        Product.price == (str(price) if price else None),
                        Product.description == (str(description) if description else None),
                        Product.status.in_(["pending", "waiting_approval", "published"])
                    )
                )
                if duplicate_check.scalar_one_or_none():
                    continue

                new_product = Product(
                    title=str(title),
                    description=str(description) if description else None,
                    price=str(price) if price else None,
                    photo_file_id=str(photo_file_id) if photo_file_id else None,
                    photo_url=str(photo_url) if photo_url else None,
                    photo_blob=photo_blob if isinstance(photo_blob, bytes) else None,
                    source=source_record_id,
                    status="pending",
                    created_at=datetime.utcnow()
                )
                session.add(new_product)
                await session.commit()
                logger.info(f"Імпортовано новий товар #{new_product.id} з джерела '{src.name}' (ID={src.id})")

            # 3. Перевірка видалених/куплених товарів у джерелі
            await handle_deleted_products(session, bot, src, current_record_ids)

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

            # 3. Отримуємо нові товари зі статусом 'pending' (лише 1 за раз, щоб не спамити)
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
                    # Відправляємо товар на погодження і оновлюємо статус, щоб не надсилати повторно
                    await ProductService.update_product_status(
                        session=session,
                        product_id=product.id,
                        status="waiting_approval"
                    )

                    for admin_id in settings.ADMIN_IDS:
                        try:
                            await bot.send_message(
                                chat_id=admin_id,
                                text="🔔 <b>Нове надходження товару!</b> Потрібна модерація:",
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
