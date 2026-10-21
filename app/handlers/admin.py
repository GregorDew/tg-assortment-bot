import html
from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select
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


@router.callback_query(F.data == "menu:main")
async def callback_back_to_main(callback: CallbackQuery):
    """Повернення до головного меню з будь-якого розділу."""
    async with async_session_maker() as session:
        auto_post_status = await SettingsService.get_auto_post_status(session)

    text = (
        "👋 <b>Головна панель керування системою</b>\n\n"
        "Оберіть потрібний розділ для керування:"
    )
    try:
        await callback.message.edit_text(
            text,
            reply_markup=get_admin_main_kb(auto_post_status),
            parse_mode="HTML"
        )
    except Exception:
        await callback.message.answer(
            text,
            reply_markup=get_admin_main_kb(auto_post_status),
            parse_mode="HTML"
        )
    await callback.answer()


@router.callback_query(F.data == "menu:moderation")
async def callback_moderation_queue(callback: CallbackQuery):
    """Черга погодження: показує наступний необроблений товар."""
    from app.database.models import PendingPublicationModel, Product
    from app.handlers.moderation import send_next_queue_item
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    async with async_session_maker() as session:
        res_pending = await session.execute(
            select(PendingPublicationModel).where(PendingPublicationModel.status == "pending")
        )
        pendings = list(res_pending.scalars().all())
        res_prod = await session.execute(
            select(Product).where(Product.status.in_(("pending", "waiting_approval")))
        )
        prods = list(res_prod.scalars().all())

    total_waiting = len(pendings) + len(prods)
    from app.keyboards.admin_kb import get_back_to_main_kb
    if total_waiting == 0:
        text = "📦 <b>Черга погодження</b>\n\n✅ Немає необроблених товарів."
        await callback.message.edit_text(text, reply_markup=get_back_to_main_kb(), parse_mode="HTML")
        await callback.answer()
        return

    text = (
        f"📦 <b>Черга погодження: {total_waiting}</b>\n\n"
        f"• Товари бота: <b>{len(prods)}</b>\n"
        f"• Записи з джерел: <b>{len(pendings)}</b>\n\n"
        "Нижче надішлю перший необроблений. Після «Опублікувати» або «Відхилити» "
        "з'явиться наступний. Старе повідомлення повторно нічого не відправить."
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="▶️ Показати наступний", callback_data="mod:queue:next")],
            [InlineKeyboardButton(text="🔙 До головного меню", callback_data="menu:main")],
        ]
    )
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()
    await send_next_queue_item(callback.bot, callback.from_user.id)

