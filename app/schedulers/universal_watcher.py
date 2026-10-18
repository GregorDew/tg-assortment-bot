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
    Періодична фонова задача для перевірки та виконання активних правил публікації.
    Опитує підключені джерела даних відповідно до check_interval_seconds кожного правила.
    """
    try:
        async with async_session_maker() as session:
            result = await session.execute(
                select(PublishRuleModel).where(
                    PublishRuleModel.is_active == True,
                    PublishRuleModel.mode != "disabled"
                )
            )
            active_rules = list(result.scalars().all())

            if not active_rules:
                return

            now = datetime.utcnow()

            for rule in active_rules:
                # Перевіряємо чи настав час виконання з урахуванням check_interval_seconds
                should_run = False
                if rule.last_run_at is None:
                    should_run = True
                else:
                    elapsed = (now - rule.last_run_at).total_seconds()
                    interval = rule.check_interval_seconds or 60
                    if elapsed >= interval:
                        should_run = True

                if should_run:
                    try:
                        logger.debug(f"Запуск виконання правила #{rule.id} «{rule.name}»...")
                        await execute_publish_rule(session=session, bot=bot, rule=rule)
                    except Exception as rule_err:
                        logger.error(
                            f"Помилка при виконанні правила #{rule.id} «{rule.name}»: {rule_err}",
                            exc_info=True
                        )
                        rule.last_run_at = datetime.utcnow()
                        await session.commit()

    except Exception as e:
        logger.error(f"Помилка у фоновому воркері universal_watcher: {e}", exc_info=True)
