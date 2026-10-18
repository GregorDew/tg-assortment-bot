import json
import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy import select, desc

from app.filters.admin import IsAdminFilter
from app.database.database import async_session_maker
from app.database.models import DeliveryLogModel, PublishRuleModel, PublishChannelModel, ProcessedRecordModel
from app.core.connectors.base import PreparedPost, PublishResult
from app.core.connectors.factory import create_connector
from app.core.security import decrypt_secret
from app.keyboards.logs_kb import get_logs_menu_kb

logger = logging.getLogger(__name__)

router = Router()
router.message.filter(IsAdminFilter())
router.callback_query.filter(IsAdminFilter())


@router.callback_query(F.data == "menu:logs")
@router.callback_query(F.data.startswith("logs:filter:"))
async def show_logs(callback: CallbackQuery):
    filter_type = callback.data.split(":")[2] if ":" in callback.data and callback.data.startswith("logs:filter:") else "all"

    async with async_session_maker() as session:
        query = select(DeliveryLogModel).order_by(desc(DeliveryLogModel.created_at)).limit(10)
        if filter_type == "failed":
            query = query.where(DeliveryLogModel.status == "failed")
        elif filter_type == "success":
            query = query.where(DeliveryLogModel.status == "success")

        res = await session.execute(query)
        logs = list(res.scalars().all())

    if not logs:
        text = f"📊 <b>Журнал операцій та помилок ({filter_type})</b>\n\nЗаписів не знайдено."
        await callback.message.edit_text(text, reply_markup=get_logs_menu_kb(filter_type), parse_mode="HTML")
        await callback.answer()
        return

    lines = [f"📊 <b>Журнал операцій та помилок (Фільтр: {filter_type}):</b>\n"]
    for l in logs:
        status_ico = "✅" if l.status == "success" else ("❌" if l.status == "failed" else "⏳")
        err_info = f"\n   ⚠️ <i>{l.error_message[:60]}...</i>" if l.error_message else ""
        time_str = l.created_at.strftime('%m-%d %H:%M:%S')
        lines.append(
            f"{status_ico} <b>[{time_str}]</b> Правило #{l.rule_id or '—'} ──> Канал #{l.channel_id or '—'}\n"
            f"   Запис ID: <code>{l.record_id or '—'}</code> | Подія: <code>{l.event_type}</code> | Спроб: {l.attempts}"
            f"{err_info}\n"
        )

    text = "\n".join(lines)
    await callback.message.edit_text(text, reply_markup=get_logs_menu_kb(filter_type), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "logs:retry_failed")
async def retry_failed_deliveries(callback: CallbackQuery):
    await callback.answer("⏳ Повторне виконання помилкових операцій...", show_alert=False)

    retried_count = 0
    success_count = 0

    async with async_session_maker() as session:
        res = await session.execute(
            select(DeliveryLogModel)
            .where(DeliveryLogModel.status == "failed")
            .order_by(desc(DeliveryLogModel.created_at))
            .limit(10)
        )
        failed_logs = list(res.scalars().all())

        for log in failed_logs:
            if not log.channel_id or not log.rule_id:
                continue

            retried_count += 1
            # Завантажуємо канал
            ch_res = await session.execute(
                select(PublishChannelModel).where(PublishChannelModel.id == log.channel_id)
            )
            channel = ch_res.scalar_one_or_none()
            if not channel or not channel.is_active:
                continue

            try:
                cfg = json.loads(decrypt_secret(channel.config_json))
                connector = create_connector(channel.type, cfg, bot=callback.bot)

                # Формуємо базовий пост для повтору
                post = PreparedPost(
                    title="Повторна публікація",
                    body=f"Повторне відправлення запису #{log.record_id}"
                )
                pub_result = await connector.publish(post)

                log.attempts += 1
                if pub_result.success:
                    success_count += 1
                    log.status = "success"
                    log.error_message = None
                    log.external_message_id = pub_result.external_id
                else:
                    log.error_message = pub_result.error_message

                await session.commit()
            except Exception as e:
                log.attempts += 1
                log.error_message = f"Помилка повтору: {e}"
                await session.commit()

    await callback.message.answer(
        f"🔁 <b>Результати повторної спроби:</b>\n"
        f"Оброблено помилок: {retried_count}\n"
        f"Успішно відправлено: {success_count}",
        parse_mode="HTML"
    )
