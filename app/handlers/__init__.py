from aiogram import Router
from app.handlers.admin import router as admin_router
from app.handlers.manual_post import router as manual_post_router
from app.handlers.moderation import router as moderation_router

main_router = Router()
main_router.include_router(admin_router)
main_router.include_router(manual_post_router)
main_router.include_router(moderation_router)

__all__ = ["main_router"]
