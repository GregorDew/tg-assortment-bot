from aiogram.filters import Filter
from aiogram.types import Message, CallbackQuery
from app.config import settings


class IsAdminFilter(Filter):
    """Фільтр, що перевіряє, чи є користувач у списку адміністраторів."""

    async def __call__(self, event: Message | CallbackQuery) -> bool:
        user_id = event.from_user.id
        return user_id in settings.ADMIN_IDS
