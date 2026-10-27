import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.connectors.base import PreparedPost, PublishResult
from app.core.connectors.factory import create_connector
from app.core.security import decrypt_secret
from app.database.models import DeliveryLogModel, Product, PublishChannelModel
from app.services.publisher import PublisherService

logger = logging.getLogger(__name__)


def explain_telegram_error(error: str) -> str:
    """Перекладає типові помилки Telegram на зрозумілі інструкції."""
    raw = (error or "").lower()
    if "chat not found" in raw:
        return (
            "Чат не знайдено. Перевірте ID/@username і що бота ДОДАНО в канал "
            "як адміністратора з правом «Публікація повідомлень»."
        )
    if "bot is not a member" in raw or "not a member" in raw:
        return "Бот не є учасником цього каналу. Додайте бота в канал і дайте права адміністратора."
    if "not enough rights" in raw or "need administrator" in raw or "chat_write_forbidden" in raw:
        return (
            "У бота немає права публікувати. У каналі: адміністратори → цей бот → "
            "увімкніть «Публікація повідомлень»."
        )
    if "forbidden" in raw:
        return "Telegram заборонив відправку. Бот має бути адміном каналу з правом публікації."
    if "message caption is too long" in raw:
        return "Текст підпису занадто довгий (ліміт Telegram ~1024 символи для фото)."
    if "can't parse entities" in raw or "can't find end of the entity" in raw:
        return "Помилка HTML-розмітки в тексті посту. Спробуйте без спецсимволів < >."
    return error


def product_to_prepared_post(product: Product) -> PreparedPost:
    manager_url = None
    if settings.MANAGER_USERNAME:
        username = settings.MANAGER_USERNAME.strip().lstrip("@")
        if username:
            manager_url = f"https://t.me/{username}"
    return PreparedPost(
        title=product.title,
        body=PublisherService.format_product_post(product, is_preview=False),
        photo_url=product.photo_url,
        photo_file_id=product.photo_file_id,
        photo_blob=product.photo_blob,
        manager_button_url=manager_url,
        extra_data={"product_id": product.id, "source": product.source},
    )


def parse_channel_config(channel: PublishChannelModel) -> Dict[str, Any]:
    decrypted = decrypt_secret(channel.config_json)
    return json.loads(decrypted)


async def load_active_channels(session: AsyncSession) -> List[PublishChannelModel]:
    result = await session.execute(
        select(PublishChannelModel)
        .where(PublishChannelModel.is_active.is_(True))
        .order_by(PublishChannelModel.id.asc())
    )
    return list(result.scalars().all())


async def log_delivery(
    session: AsyncSession,
    *,
    channel_id: Optional[int],
    record_id: Optional[str],
    event_type: str,
    status: str,
    error_message: Optional[str] = None,
    external_message_id: Optional[str] = None,
    rule_id: Optional[int] = None,
    source_id: Optional[int] = None,
) -> DeliveryLogModel:
    entry = DeliveryLogModel(
        rule_id=rule_id,
        source_id=source_id,
        channel_id=channel_id,
        record_id=record_id,
        event_type=event_type,
        status=status,
        error_message=error_message,
        external_message_id=external_message_id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return entry


async def publish_to_channel(
    session: AsyncSession,
    bot: Bot,
    channel: PublishChannelModel,
    post: PreparedPost,
    *,
    record_id: str,
    event_type: str,
) -> Tuple[PublishResult, Optional[str]]:
    try:
        config = parse_channel_config(channel)
    except Exception as exc:
        err = f"Не вдалося прочитати налаштування каналу: {exc}"
        await log_delivery(
            session,
            channel_id=channel.id,
            record_id=record_id,
            event_type=event_type,
            status="failed",
            error_message=err,
        )
        return PublishResult(success=False, error_message=err), err

    try:
        connector = create_connector(channel.type, config, bot=bot)
        result = await connector.publish(post)
    except Exception as exc:
        result = PublishResult(success=False, error_message=str(exc))

    friendly = None
    if not result.success:
        friendly = explain_telegram_error(result.error_message or "Невідома помилка")
        if channel.type == "telegram":
            result.error_message = friendly

    await log_delivery(
        session,
        channel_id=channel.id,
        record_id=record_id,
        event_type=event_type,
        status="success" if result.success else "failed",
        error_message=None if result.success else (result.error_message or friendly),
        external_message_id=result.external_id,
    )
    return result, friendly


async def broadcast_post(
    session: AsyncSession,
    bot: Bot,
    post: PreparedPost,
    *,
    record_id: str,
    event_type: str,
    channels: Optional[List[PublishChannelModel]] = None,
) -> Dict[str, Any]:
    """
    Відправляє пост у всі активні канали.
    Якщо каналів немає — пробує TARGET_CHAT_ID з .env як запасний Telegram.
    """
    channels = list(channels if channels is not None else await load_active_channels(session))
    reports: List[str] = []
    success_count = 0
    fail_count = 0
    used_fallback = False

    if not channels:
        used_fallback = True
        fallback = PublishChannelModel(
            id=0,
            name="TARGET_CHAT_ID (.env)",
            type="telegram",
            config_json=json.dumps({"chat_id": settings.TARGET_CHAT_ID}),
            is_active=True,
        )
        channels = [fallback]
        reports.append(
            "⚠️ У боті немає доданих каналів. Відправляю лише в TARGET_CHAT_ID з .env. "
            "Додайте канали в «📢 Канали публікації», щоб пости йшли в кілька місць."
        )

    for channel in channels:
        result, _friendly = await publish_to_channel(
            session,
            bot,
            channel,
            post,
            record_id=record_id,
            event_type=event_type,
        )
        label = f"{channel.type} «{channel.name}»"
        if result.success:
            success_count += 1
            extra = f" (id={result.external_id})" if result.external_id else ""
            reports.append(f"✅ {label}: відправлено{extra}")
        else:
            fail_count += 1
            reports.append(f"❌ {label}: {result.error_message}")

    return {
        "success_count": success_count,
        "fail_count": fail_count,
        "reports": reports,
        "used_fallback": used_fallback,
        "ok": success_count > 0,
    }


def format_broadcast_report(title: str, outcome: Dict[str, Any]) -> str:
    lines = [title, "───────────────────────"]
    lines.extend(outcome.get("reports") or [])
    lines.append("")
    lines.append(
        f"Підсумок: успішно {outcome.get('success_count', 0)}, "
        f"помилок {outcome.get('fail_count', 0)}."
    )
    if outcome.get("fail_count") and not outcome.get("ok"):
        lines.append("Пост НЕ опубліковано в жодному каналі. Виправте помилки і спробуйте ще раз.")
    elif outcome.get("fail_count"):
        lines.append("Частина каналів не прийняла пост. Деталі збережено в журналі.")
    return "\n".join(lines)


async def broadcast_product(session: AsyncSession, bot: Bot, product: Product) -> Dict[str, Any]:
    post = product_to_prepared_post(product)
    return await broadcast_post(
        session,
        bot,
        post,
        record_id=str(product.id),
        event_type="product",
    )
