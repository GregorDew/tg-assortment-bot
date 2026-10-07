from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select
from app.config import settings
from app.database.models import Base, BotSettings

# Створення асинхронного рушія БД
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True
)

# Фабрика сесій
async_session_maker = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)


async def init_db() -> None:
    """Ініціалізація структури бази даних та створення початкових налаштувань."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Перевірка наявності запису налаштувань
    async with async_session_maker() as session:
        result = await session.execute(select(BotSettings).where(BotSettings.id == 1))
        settings_record = result.scalar_one_or_none()
        if not settings_record:
            default_settings = BotSettings(id=1, auto_post_enabled=False)
            session.add(default_settings)
            await session.commit()
