import asyncio
import logging
import sys

# Безпечне налаштування UTF-8 для виводу в консоль на Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.database import init_db
from app.handlers import main_router
from app.schedulers import check_and_process_db_updates, check_and_execute_publish_rules

# Налаштування логування
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("main")


async def setup_bot_commands(bot: Bot):
    """Реєструє команди у спливаючому меню бота."""
    commands = [
        BotCommand(command="admin", description="Панель адміністратора"),
        BotCommand(command="start", description="Головне меню"),
    ]
    await bot.set_my_commands(commands)


async def main():
    logger.info("Ініціалізація бази даних...")
    await init_db()
    logger.info("База даних успішно ініціалізована.")

    if not settings.BOT_TOKEN or settings.BOT_TOKEN.startswith("123456789:"):
        logger.warning(
            "⚠️ Увага: Токен бота не налаштований або містить значення за замовчуванням у .env!"
        )

    # Ініціалізація клієнта бота та диспетчера
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(main_router)

    # Налаштування планувальника завдань (Scheduler)
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        check_and_process_db_updates,
        trigger="interval",
        seconds=settings.DB_CHECK_INTERVAL_SECONDS,
        args=[bot]
    )
    scheduler.add_job(
        check_and_execute_publish_rules,
        trigger="interval",
        seconds=15,
        args=[bot]
    )
    scheduler.start()
    logger.info(
        f"Фоновий моніторинг БД запущено ({settings.DB_CHECK_INTERVAL_SECONDS}с) та універсальних правил (15с)."
    )

    try:
        await setup_bot_commands(bot)
        # Видаляємо старі вебхуки та накопичені оновлення при старті
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Бот готовий до роботи та починає опитування (polling)...")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Отримано сигнал зупинки бота.")
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()
        logger.info("Сесію бота закрито. Роботу завершено.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
