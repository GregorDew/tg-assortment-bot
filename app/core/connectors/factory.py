from typing import Any, Dict, Optional
from aiogram import Bot
from app.core.connectors.base import BasePublisherConnector
from app.core.connectors.telegram import TelegramPublisherConnector
from app.core.connectors.discord import DiscordPublisherConnector
from app.core.connectors.http_api import HttpApiPublisherConnector
from app.core.connectors.email import EmailPublisherConnector


def create_connector(
    channel_type: str,
    config: Dict[str, Any],
    bot: Optional[Bot] = None
) -> BasePublisherConnector:
    """Фабрика для створення конектора публікації за типом каналу."""
    t = channel_type.lower()
    if t == "telegram":
        return TelegramPublisherConnector(config, bot=bot)
    elif t == "discord":
        return DiscordPublisherConnector(config)
    elif t in ("http", "http_api", "api"):
        return HttpApiPublisherConnector(config)
    elif t in ("email", "smtp", "mail"):
        return EmailPublisherConnector(config)
    else:
        raise ValueError(f"Невідомий тип каналу публікації: '{channel_type}'")
