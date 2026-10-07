from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models import BotSettings


class SettingsService:
    @staticmethod
    async def get_auto_post_status(session: AsyncSession) -> bool:
        """Повертає поточний статус автопостингу."""
        result = await session.execute(select(BotSettings).where(BotSettings.id == 1))
        settings_record = result.scalar_one_or_none()
        if not settings_record:
            settings_record = BotSettings(id=1, auto_post_enabled=False)
            session.add(settings_record)
            await session.commit()
            return False
        return settings_record.auto_post_enabled

    @staticmethod
    async def toggle_auto_post_status(session: AsyncSession) -> bool:
        """Перемикає статус автопостингу (ON <-> OFF) та повертає нове значення."""
        result = await session.execute(select(BotSettings).where(BotSettings.id == 1))
        settings_record = result.scalar_one_or_none()
        if not settings_record:
            settings_record = BotSettings(id=1, auto_post_enabled=True)
            session.add(settings_record)
        else:
            settings_record.auto_post_enabled = not settings_record.auto_post_enabled
            settings_record.updated_at = datetime.utcnow()
        await session.commit()
        return settings_record.auto_post_enabled
