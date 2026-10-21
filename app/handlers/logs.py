import html
import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import select

from app.database.database import async_session_maker
from app.database.models import DeliveryLogModel, Product, PublishChannelModel
from app.filters.admin import IsAdminFilter
from app.keyboards.logs_kb import get_logs_menu_kb
from app.services.delivery import product_to_prepared_post, publish_to_channel

logger = logging.getLogger(__name__)

router = Router()
router.message.filter(IsAdminFilter())
router.callback_query.filter(IsAdminFilter())

STATUS_LABEL = {
    "success": "✅ Успіх",
    "failed": "❌ Помилка",
    "pending_approval": "⏳ Погодження",
    "skipped": "⏭ Пропуск",
}


def _format_log_line(entry: DeliveryLogModel) -> str:
    ts = entry.created_at.strftime("%d.%m %H:%M") if entry.created_at else "—"
    status = STATUS_LABEL.get(entry.status, entry.status)
    channel = f"канал #{entry.channel_id}" if entry.channel_id else "без каналу"
    rec = f"запис {html.escape(str(entry.record_id))}" if entry.record_id else "—"
    line = f"• <code>{ts}</code> {status} | {channel} | {rec} | <code>{entry.event_type}</code>"
    if entry.external_message_id and entry.status == "success":
        line += f"\n   id повідомлення: <code>{html.escape(str(entry.external_message_id))}</code>"
    if entry.error_message:
        err = html.escape(entry.error_message[:280])
        line += f"\n   {err}"
    return line


@router.callback_query(F.data == "menu:logs")
@router.callback_query(F.data.startswith("logs:filter:"))
async def show_logs(callback: CallbackQuery):
    filter_type = "all"
    if callback.data.startswith("logs:filter:"):
        filter_type = callback.data.split(":")[2]

    async with async_session_maker() as session:
        stmt = select(DeliveryLogModel).order_by(DeliveryLogModel.id.desc()).limit(20)
        if filter_type in ("failed", "success"):
            stmt = (
                select(DeliveryLogModel)
                .where(DeliveryLogModel.status == filter_type)
                .order_by(DeliveryLogModel.id.desc())
                .limit(20)
            )
        entries = list((await session.execute(stmt)).scalars().all())
        failed_count = len(
            list(
                (
                    await session.execute(
                        select(DeliveryLogModel).where(DeliveryLogModel.status == "failed")
                    )
                ).scalars().all()
            )
        )

    title_map = {"all": "усі", "failed": "помилки", "success": "успішні"}
    title = title_map.get(filter_type, filter_type)
    if not entries:
        text = (
            f"📊 <b>Журнал дій ({title})</b>\n\n"
            "Записів немає. Журнал з'являється після спроби публікації: "
            "погодження товару, автопост або тест каналу."
        )
        await callback.message.edit_text(text, reply_markup=get_logs_menu_kb(filter_type), parse_mode="HTML")
        await callback.answer()
        return

    lines = [f"📊 <b>Журнал дій ({title})</b>", f"Невиправлених помилок у базі: <b>{failed_count}</b>\n"]
    lines.extend(_format_log_line(e) for e in entries)
    text = "\n".join(lines)
    if len(text) > 3800:
        text = text[:3800] + "\n…"
    await callback.message.edit_text(text, reply_markup=get_logs_menu_kb(filter_type), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "logs:retry_failed")
async def retry_failed_deliveries(callback: CallbackQuery):
    await callback.answer("Повторюю невдалі відправки...")
    success = 0
    processed = 0
    notes = []

    async with async_session_maker() as session:
        failed = list(
            (
                await session.execute(
                    select(DeliveryLogModel)
                    .where(DeliveryLogModel.status == "failed")
                    .order_by(DeliveryLogModel.id.desc())
                    .limit(30)
                )
            ).scalars().all()
        )
        for entry in failed:
            processed += 1
            if not entry.channel_id or not entry.record_id:
                notes.append(f"#{entry.id}: немає каналу або запису")
                continue
            channel = (
                await session.execute(
                    select(PublishChannelModel).where(PublishChannelModel.id == entry.channel_id)
                )
            ).scalar_one_or_none()
            if not channel or not channel.is_active:
                notes.append(f"#{entry.id}: канал вимкнено або видалено")
                continue

            post = None
            if entry.event_type == "product" and str(entry.record_id).isdigit():
                product = (
                    await session.execute(select(Product).where(Product.id == int(entry.record_id)))
                ).scalar_one_or_none()
                if product:
                    post = product_to_prepared_post(product)
            if post is None:
                notes.append(f"#{entry.id}: не можу відновити текст посту")
                continue

            result, _ = await publish_to_channel(
                session,
                callback.bot,
                channel,
                post,
                record_id=str(entry.record_id),
                event_type=f"retry:{entry.event_type}",
            )
            if result.success:
                success += 1
                entry.status = "success"
                entry.error_message = None
                entry.external_message_id = result.external_id
                entry.updated_at = datetime.utcnow()
                entry.attempts = (entry.attempts or 1) + 1
                await session.commit()
            else:
                entry.attempts = (entry.attempts or 1) + 1
                entry.error_message = result.error_message
                entry.updated_at = datetime.utcnow()
                await session.commit()
                notes.append(f"#{entry.id}: {result.error_message}")

    extra = ("\n" + "\n".join(notes[:8])) if notes else ""
    await callback.message.answer(
        f"🔁 <b>Повтор відправок</b>\nОброблено помилок: {processed}\nУспішно: {success}{extra}",
        parse_mode="HTML",
    )
    callback.data = "logs:filter:failed"
    await show_logs(callback)
