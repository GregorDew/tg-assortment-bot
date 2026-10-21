from datetime import datetime
import json
import logging
from typing import Any, Dict, List, Optional
from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.connectors.base import PreparedPost, PublishResult
from app.core.connectors.factory import create_connector
from app.core.security import decrypt_secret
from app.core.sources.base import DataRecord
from app.core.sources.factory import create_data_source
from app.core.templating import render_template
from app.database.models import (
    DataSourceModel,
    PublishChannelModel,
    TemplateModel,
    PublishRuleModel,
    PendingPublicationModel,
    DeliveryLogModel,
    ProcessedRecordModel
)
from app.keyboards.admin_kb import get_preview_moderation_kb
from app.services.delivery import explain_telegram_error

logger = logging.getLogger(__name__)


def evaluate_filters(record_data: Dict[str, Any], filters_json: Optional[str]) -> bool:
    """Перевіряє, чи відповідає запис налаштованим фільтрам правила."""
    if not filters_json:
        return True
    try:
        filters = json.loads(filters_json)
        if not isinstance(filters, list):
            return True

        for flt in filters:
            field = flt.get("field")
            op = flt.get("op", "==")
            target_val = flt.get("value")

            actual_val = record_data.get(field)
            if actual_val is None:
                return False

            str_actual = str(actual_val)
            str_target = str(target_val)

            if op == "==" and str_actual != str_target:
                return False
            elif op == "!=" and str_actual == str_target:
                return False
            elif op == ">":
                try:
                    if float(str_actual) <= float(str_target):
                        return False
                except ValueError:
                    return False
            elif op == "<":
                try:
                    if float(str_actual) >= float(str_target):
                        return False
                except ValueError:
                    return False
            elif op == "contains" and str_target.lower() not in str_actual.lower():
                return False

        return True
    except Exception as e:
        logger.warning(f"Помилка оцінки фільтрів: {e}")
        return True


def prepare_post_content(
    record_data: Dict[str, Any],
    template: Optional[TemplateModel],
    rule_name: str
) -> PreparedPost:
    """Формує підготовлений вміст публікації на основі шаблону або дефолтного формату."""
    manager_url = None
    if settings.MANAGER_USERNAME:
        username = settings.MANAGER_USERNAME.strip().lstrip("@")
        if username:
            manager_url = f"https://t.me/{username}"

    photo_url = None
    for photo_key in ("photo_url", "image_url", "image", "photo", "img"):
        if record_data.get(photo_key):
            photo_url = str(record_data[photo_key])
            break

    if template and template.body_template:
        body = render_template(template.body_template, record_data, escape_for_html=False)
        title = render_template(template.title_template or "", record_data, escape_for_html=False) or None
    else:
        # Стандартний формат
        title = str(record_data.get("title") or record_data.get("name") or rule_name)
        lines = [f"🔥 <b>{title}</b>\n───────────────────────"]
        for k, v in record_data.items():
            if k in ("id", "photo_url", "image_url", "photo", "img"):
                continue
            lines.append(f"• <b>{k}:</b> {v}")
        body = "\n".join(lines)

    return PreparedPost(
        title=title,
        body=body,
        photo_url=photo_url,
        manager_button_url=manager_url,
        extra_data=record_data
    )


async def dispatch_to_channels(
    session: AsyncSession,
    bot: Bot,
    channel_ids: List[int],
    post: PreparedPost,
    rule_id: int,
    source_id: int,
    record_id: str,
    event_type: str = "new",
    existing_external_ids: Optional[Dict[str, str]] = None,
    is_update: bool = False
) -> Dict[str, str]:
    """
    Відправляє підготовлену публікацію у всі вказані канали.
    Ізоляція помилок: збій в одному каналі НЕ перешкоджає іншим каналам.
    Повертає словник {channel_id: external_message_id}.
    """
    res_external_ids: Dict[str, str] = dict(existing_external_ids or {})

    for ch_id in channel_ids:
        # Отримуємо канал з БД
        res = await session.execute(
            select(PublishChannelModel).where(PublishChannelModel.id == ch_id)
        )
        channel = res.scalar_one_or_none()
        ch_label = f"#{ch_id}"
        if channel:
            ch_label = f"#{channel.id} «{channel.name}»"

        if not channel:
            err_msg = f"Канал {ch_label} видалено з бота."
            log = DeliveryLogModel(
                rule_id=rule_id,
                source_id=source_id,
                channel_id=ch_id,
                record_id=record_id,
                event_type=event_type,
                status="failed",
                error_message=err_msg
            )
            session.add(log)
            await session.commit()
            continue
        if not channel.is_active:
            err_msg = f"Канал {ch_label} вимкнено в налаштуваннях."
            log = DeliveryLogModel(
                rule_id=rule_id,
                source_id=source_id,
                channel_id=ch_id,
                record_id=record_id,
                event_type=event_type,
                status="failed",
                error_message=err_msg
            )
            session.add(log)
            await session.commit()
            continue

        try:
            # Розшифровуємо конфіг каналу
            decrypted_cfg_str = decrypt_secret(channel.config_json)
            config = json.loads(decrypted_cfg_str)
        except Exception as cfg_err:
            logger.error(f"Помилка конфігурації каналу {ch_label}: {cfg_err}")
            log = DeliveryLogModel(
                rule_id=rule_id,
                source_id=source_id,
                channel_id=ch_id,
                record_id=record_id,
                event_type=event_type,
                status="failed",
                error_message=f"Помилка конфігурації: {cfg_err}"
            )
            session.add(log)
            await session.commit()
            continue

        # Створюємо конектор
        try:
            connector = create_connector(channel.type, config, bot=bot)
        except Exception as conn_err:
            logger.error(f"Не вдалося створити конектор для каналу {ch_label}: {conn_err}")
            log = DeliveryLogModel(
                rule_id=rule_id,
                source_id=source_id,
                channel_id=ch_id,
                record_id=record_id,
                event_type=event_type,
                status="failed",
                error_message=str(conn_err)
            )
            session.add(log)
            await session.commit()
            continue

        # Публікуємо або оновлюємо
        ext_msg_id = res_external_ids.get(str(ch_id))
        pub_result: PublishResult

        if is_update and ext_msg_id:
            pub_result = await connector.update(ext_msg_id, post)
        else:
            pub_result = await connector.publish(post)

        err_text = None
        if not pub_result.success:
            raw_err = pub_result.error_message or "Невідома помилка"
            err_text = explain_telegram_error(raw_err) if channel.type == "telegram" else raw_err

        # Журналювання результату
        log = DeliveryLogModel(
            rule_id=rule_id,
            source_id=source_id,
            channel_id=ch_id,
            record_id=record_id,
            event_type=event_type,
            status="success" if pub_result.success else "failed",
            error_message=err_text,
            external_message_id=pub_result.external_id or ext_msg_id
        )
        session.add(log)
        await session.commit()

        if pub_result.success and pub_result.external_id:
            res_external_ids[str(ch_id)] = pub_result.external_id

    return res_external_ids


async def execute_publish_rule(session: AsyncSession, bot: Bot, rule: PublishRuleModel) -> None:
    """Виконує один цикл опитування джерела за правилом."""
    # 1. Завантажуємо джерело
    src_res = await session.execute(
        select(DataSourceModel).where(DataSourceModel.id == rule.data_source_id)
    )
    data_source = src_res.scalar_one_or_none()
    if not data_source or not data_source.is_active:
        return

    # 2. Завантажуємо шаблон
    template = None
    if rule.template_id:
        tpl_res = await session.execute(
            select(TemplateModel).where(TemplateModel.id == rule.template_id)
        )
        template = tpl_res.scalar_one_or_none()

    # 3. Ініціалізуємо конектор джерела
    try:
        decrypted_src_cfg = decrypt_secret(data_source.config_json)
        src_cfg = json.loads(decrypted_src_cfg)
        source_adapter = create_data_source(data_source.type, src_cfg)
    except Exception as e:
        logger.error(f"Помилка ініціалізації джерела #{data_source.id}: {e}")
        data_source.last_error = str(e)
        await session.commit()
        return

    # 4. Отримуємо записи з джерела
    fields = []
    if data_source.selected_fields:
        try:
            fields = json.loads(data_source.selected_fields)
        except Exception:
            fields = []

    pk_field = data_source.pk_field or "id"
    table_name = data_source.selected_table or ""

    try:
        records: List[DataRecord] = await source_adapter.fetch_records(
            table_name=table_name,
            fields=fields,
            pk_field=pk_field,
            tracking_mode=data_source.change_tracking_mode,
            tracking_field=data_source.tracking_field,
            limit=50
        )
        data_source.last_sync_at = datetime.utcnow()
        data_source.last_error = None
        await session.commit()
    except Exception as e:
        logger.error(f"Помилка отримання даних з джерела #{data_source.id}: {e}")
        data_source.last_error = str(e)
        await session.commit()
        return

    # Парсимо канали та події правила
    channel_ids: List[int] = []
    if rule.channel_ids_json:
        try:
            channel_ids = [int(x) for x in json.loads(rule.channel_ids_json)]
        except Exception:
            channel_ids = []
    if not channel_ids:
        all_ch = list((await session.execute(
            select(PublishChannelModel).where(PublishChannelModel.is_active.is_(True))
        )).scalars().all())
        channel_ids = [c.id for c in all_ch]

    trigger_events: List[str] = ["new"]
    if rule.trigger_events:
        try:
            trigger_events = json.loads(rule.trigger_events)
        except Exception:
            trigger_events = ["new"]

    # 5. Обробка кожного отриманого запису
    for rec in records:
        if not evaluate_filters(rec.data, rule.filters_json):
            continue

        # Перевірка наявності в ProcessedRecordModel
        proc_res = await session.execute(
            select(ProcessedRecordModel).where(
                ProcessedRecordModel.rule_id == rule.id,
                ProcessedRecordModel.record_id == rec.id
            ).order_by(ProcessedRecordModel.id.desc())
        )
        proc_rec = proc_res.scalars().first()

        post = prepare_post_content(rec.data, template, rule.name)

        # Випадок A: Новий запис
        if not proc_rec:
            if "new" not in trigger_events:
                continue

            if rule.mode == "auto":
                ext_ids = await dispatch_to_channels(
                    session=session,
                    bot=bot,
                    channel_ids=channel_ids,
                    post=post,
                    rule_id=rule.id,
                    source_id=data_source.id,
                    record_id=rec.id,
                    event_type="new"
                )
                new_proc = ProcessedRecordModel(
                    rule_id=rule.id,
                    record_id=rec.id,
                    row_hash=rec.row_hash,
                    last_seen_at=datetime.utcnow(),
                    external_ids_json=json.dumps(ext_ids)
                )
                session.add(new_proc)
                await session.commit()

            elif rule.mode == "approval":
                # Створюємо завдання на погодження
                pending = PendingPublicationModel(
                    rule_id=rule.id,
                    source_id=data_source.id,
                    record_id=rec.id,
                    event_type="new",
                    raw_data_json=json.dumps(rec.data, default=str),
                    prepared_data_json=json.dumps({
                        "title": post.title,
                        "body": post.body,
                        "photo_url": post.photo_url,
                        "manager_button_url": post.manager_button_url
                    }),
                    status="pending"
                )
                session.add(pending)
                new_proc = ProcessedRecordModel(
                    rule_id=rule.id,
                    record_id=rec.id,
                    row_hash=rec.row_hash,
                    last_seen_at=datetime.utcnow(),
                    external_ids_json="{}"
                )
                session.add(new_proc)
                await session.commit()
                await session.refresh(pending)

                # Розсилаємо адмінам прев'ю
                for adm_id in settings.ADMIN_IDS:
                    try:
                        await bot.send_message(
                            chat_id=adm_id,
                            text=f"🔔 <b>Новий запис для погодження (Правило: {rule.name})!</b>",
                            parse_mode="HTML"
                        )
                        caption = f"👁 <b>[ПОГОДЖЕННЯ]</b>\nПравило: <b>{rule.name}</b>\n───────────────────────\n{post.body}"
                        if post.photo_url:
                            await bot.send_photo(
                                chat_id=adm_id,
                                photo=post.photo_url,
                                caption=caption,
                                parse_mode="HTML",
                                reply_markup=get_preview_moderation_kb(pending.id, settings.MANAGER_USERNAME)
                            )
                        else:
                            await bot.send_message(
                                chat_id=adm_id,
                                text=caption,
                                parse_mode="HTML",
                                reply_markup=get_preview_moderation_kb(pending.id, settings.MANAGER_USERNAME)
                            )
                    except Exception as adm_err:
                        logger.warning(f"Не вдалося сповістити адміна {adm_id}: {adm_err}")

        # Випадок B: Запис змінився
        elif proc_rec.row_hash != rec.row_hash:
            if "updated" not in trigger_events:
                continue

            existing_ext_ids = {}
            try:
                existing_ext_ids = json.loads(proc_rec.external_ids_json)
            except Exception:
                existing_ext_ids = {}

            if rule.on_update_action == "ignore":
                proc_rec.row_hash = rec.row_hash
                proc_rec.last_seen_at = datetime.utcnow()
                await session.commit()
                continue

            elif rule.on_update_action == "update_post" and rule.mode == "auto":
                updated_ext_ids = await dispatch_to_channels(
                    session=session,
                    bot=bot,
                    channel_ids=channel_ids,
                    post=post,
                    rule_id=rule.id,
                    source_id=data_source.id,
                    record_id=rec.id,
                    event_type="updated",
                    existing_external_ids=existing_ext_ids,
                    is_update=True
                )
                proc_rec.row_hash = rec.row_hash
                proc_rec.last_seen_at = datetime.utcnow()
                proc_rec.external_ids_json = json.dumps(updated_ext_ids)
                await session.commit()

            elif rule.on_update_action == "new_post" and rule.mode == "auto":
                new_ext_ids = await dispatch_to_channels(
                    session=session,
                    bot=bot,
                    channel_ids=channel_ids,
                    post=post,
                    rule_id=rule.id,
                    source_id=data_source.id,
                    record_id=rec.id,
                    event_type="updated"
                )
                proc_rec.row_hash = rec.row_hash
                proc_rec.last_seen_at = datetime.utcnow()
                proc_rec.external_ids_json = json.dumps(new_ext_ids)
                await session.commit()

            elif rule.on_update_action == "approval" or rule.mode == "approval":
                # Передаємо зміну на повторне погодження
                pending = PendingPublicationModel(
                    rule_id=rule.id,
                    source_id=data_source.id,
                    record_id=rec.id,
                    event_type="updated",
                    raw_data_json=json.dumps(rec.data, default=str),
                    prepared_data_json=json.dumps({
                        "title": post.title,
                        "body": post.body,
                        "photo_url": post.photo_url,
                        "manager_button_url": post.manager_button_url
                    }),
                    status="pending"
                )
                session.add(pending)
                proc_rec.row_hash = rec.row_hash
                proc_rec.last_seen_at = datetime.utcnow()
                await session.commit()
                await session.refresh(pending)

                for adm_id in settings.ADMIN_IDS:
                    try:
                        caption = f"⚠️ <b>[ЗМІНА ЗАПИСУ НА ПОГОДЖЕННЯ]</b>\nПравило: <b>{rule.name}</b>\n───────────────────────\n{post.body}"
                        if post.photo_url:
                            await bot.send_photo(
                                chat_id=adm_id,
                                photo=post.photo_url,
                                caption=caption,
                                parse_mode="HTML",
                                reply_markup=get_preview_moderation_kb(pending.id, settings.MANAGER_USERNAME)
                            )
                        else:
                            await bot.send_message(
                                chat_id=adm_id,
                                text=caption,
                                parse_mode="HTML",
                                reply_markup=get_preview_moderation_kb(pending.id, settings.MANAGER_USERNAME)
                            )
                    except Exception as adm_err:
                        logger.warning(f"Не вдалося сповістити адміна {adm_id}: {adm_err}")

    rule.last_run_at = datetime.utcnow()
    await session.commit()
