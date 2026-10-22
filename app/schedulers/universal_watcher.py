import asyncio
from datetime import datetime
import logging
from aiogram import Bot
from sqlalchemy import select

from app.database.database import async_session_maker
from app.database.models import PublishRuleModel
from app.core.rules.engine import execute_publish_rule

logger = logging.getLogger(__name__)


async def check_and_execute_publish_rules(bot: Bot) -> None:
    """
    Правила вимкнено користувачем. Функція залишена як no-op для сумісності.
    """
    return
