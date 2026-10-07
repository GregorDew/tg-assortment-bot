import html
from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from app.config import settings
from app.filters.admin import IsAdminFilter
from app.database.database import async_session_maker
from app.services.settings_service import SettingsService
from app.services.product_service import ProductService
from app.keyboards.admin_kb import get_admin_main_kb

router = Router()
# Застосовуємо фільтр адміна до всіх хендлерів цього роутера
router.message.filter(IsAdminFilter())
router.callback_query.filter(IsAdminFilter())


@router.message(CommandStart())
@router.message(Command("admin"))
async def cmd_admin_panel(message: Message):
    """Головне меню панелі адміністратора."""
    async with async_session_maker() as session:
        auto_post_status = await SettingsService.get_auto_post_status(session)

    text = (
        "👋 <b>Вітаємо в панелі керування оновленнями асортименту!</b>\n\n"
        "Тут ви можете:\n"
        "• Створити пост про новий товар вручну\n"
        "• Увімкнути/вимкнути автоматичну публікацію товарів із бази даних\n"
        "• Переглянути останні товари в базі даних\n\n"
        "Оберіть потрібну дію нижче:"
    )
    await message.answer(text, reply_markup=get_admin_main_kb(auto_post_status), parse_mode="HTML")


@router.callback_query(F.data == "admin:toggle_autopost")
async def callback_toggle_autopost(callback: CallbackQuery):
    """Обробка перемикання режиму автопостингу."""
    async with async_session_maker() as session:
        new_status = await SettingsService.toggle_auto_post_status(session)

    status_str = "🟢 УВІМКНЕНО (пости публікуються без підтвердження)" if new_status else "🔴 ВИМКНЕНО (потрібне підтвердження адміна)"
    await callback.answer(f"Режим змінено на: {status_str}", show_alert=True)

    text = (
        "👋 <b>Панель керування оновленнями асортименту</b>\n\n"
        f"Поточний режим: <b>{status_str}</b>\n\n"
        "Оберіть дію:"
    )
    try:
        await callback.message.edit_text(
            text,
            reply_markup=get_admin_main_kb(new_status),
            parse_mode="HTML"
        )
    except Exception:
        pass


@router.callback_query(F.data == "admin:add_test_product")
async def callback_add_test_product(callback: CallbackQuery):
    """Додає тестовий товар у БД зі статусом 'pending' для перевірки роботи фонового воркера."""
    import random
    item_num = random.randint(100, 999)
    title = f"Тестовий товар #{item_num}"
    description = "Чудовий зразок товару, що надійшов у базі даних. Тестування роботи системи."
    price = f"{item_num * 5} грн"
    photo_url = "https://picsum.photos/600/400"  # Тестове безкоштовне зображення

    async with async_session_maker() as session:
        product = await ProductService.create_product(
            session=session,
            title=title,
            description=description,
            price=price,
            photo_url=photo_url,
            source="db",
            status="pending"
        )

    await callback.answer(f"✅ Додано тестовий товар #{product.id} у БД!", show_alert=True)


@router.callback_query(F.data == "admin:list_products")
async def callback_list_products(callback: CallbackQuery):
    """Показує список останніх товарів у базі даних."""
    async with async_session_maker() as session:
        products = await ProductService.get_latest_products(session, limit=5)
        auto_post_status = await SettingsService.get_auto_post_status(session)

    if not products:
        msg = "ℹ️ У базі даних поки немає жодного товару."
    else:
        status_map = {
            "pending": "⏳ Очікує",
            "published": "✅ Опубліковано",
            "rejected": "❌ Відхилено"
        }
        lines = ["📋 <b>Останні товари в базі даних:</b>\n"]
        for p in products:
            status_text = status_map.get(p.status, p.status)
            lines.append(
                f"• <b>#{p.id} {html.escape(p.title)}</b>\n"
                f"   Ціна: {html.escape(p.price or 'не вказано')} | Статус: {status_text} | Джерело: {p.source}\n"
            )
        msg = "\n".join(lines)

    await callback.message.edit_text(
        msg,
        reply_markup=get_admin_main_kb(auto_post_status),
        parse_mode="HTML"
    )
