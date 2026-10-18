from aiogram import Router
from app.handlers.admin import router as admin_router
from app.handlers.manual_post import router as manual_post_router
from app.handlers.moderation import router as moderation_router
from app.handlers.sources import router as sources_router
from app.handlers.channels import router as channels_router
from app.handlers.templates import router as templates_router
from app.handlers.rules import router as rules_router
from app.handlers.logs import router as logs_router

main_router = Router()
main_router.include_router(admin_router)
main_router.include_router(manual_post_router)
main_router.include_router(moderation_router)
main_router.include_router(sources_router)
main_router.include_router(channels_router)
main_router.include_router(templates_router)
main_router.include_router(rules_router)
main_router.include_router(logs_router)

__all__ = ["main_router"]
