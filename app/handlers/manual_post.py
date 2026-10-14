from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from app.filters.admin import IsAdminFilter
from app.states.manual_post import ManualPostFSM
from app.keyboards.admin_kb import (
    get_skip_and_cancel_kb,
    get_cancel_only_kb,
    get_preview_moderation_kb,
    get_admin_main_kb
)
from app.config import settings
from app.database.database import async_session_maker
from app.services.product_service import ProductService
from app.services.settings_service import SettingsService
from app.services.publisher import PublisherService

router = Router()
router.message.filter(IsAdminFilter())
router.callback_query.filter(IsAdminFilter())


@router.callback_query(F.data == "admin:create_post")
async def start_manual_post_creation(callback: CallbackQuery, state: FSMContext):
    """Початок сценарію створення посту вручну (FSM)."""
    await state.clear()
    await state.set_state(ManualPostFSM.waiting_for_photo)
    await callback.message.answer(
        "📸 <b>Крок 1/4: Фотографія товару</b>\n\n"
        "Надішліть фото товару у чат, або натисніть кнопку «Пропустити цей крок», якщо пост має бути текстовим.",
        reply_markup=get_skip_and_cancel_kb("photo"),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "fsm:cancel")
async def cancel_fsm(callback: CallbackQuery, state: FSMContext):
    """Скасування процесу створення посту."""
    await state.clear()
    async with async_session_maker() as session:
        auto_post_status = await SettingsService.get_auto_post_status(session)
    await callback.message.answer(
        "🚫 <b>Створення посту скасовано.</b>",
        reply_markup=get_admin_main_kb(auto_post_status),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "fsm:skip:photo", ManualPostFSM.waiting_for_photo)
async def skip_photo_step(callback: CallbackQuery, state: FSMContext):
    """Пропуск кроку завантаження фото."""
    await state.update_data(photo_file_id=None)
    await state.set_state(ManualPostFSM.waiting_for_title)
    await callback.message.answer(
        "✏️ <b>Крок 2/4: Назва товару</b>\n\nВведіть назву товару (заголовок посту):",
        reply_markup=get_cancel_only_kb(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(ManualPostFSM.waiting_for_photo, F.photo)
async def process_photo(message: Message, state: FSMContext):
    """Отримання фото товару від адміністратора."""
    # Беремо найбільший розмір фото
    photo_file_id = message.photo[-1].file_id
    await state.update_data(photo_file_id=photo_file_id)
    await state.set_state(ManualPostFSM.waiting_for_title)
    await message.answer(
        "✅ Фото отримано!\n\n"
        "✏️ <b>Крок 2/4: Назва товару</b>\n\nВведіть назву товару (заголовок посту):",
        reply_markup=get_cancel_only_kb(),
        parse_mode="HTML"
    )


@router.message(ManualPostFSM.waiting_for_photo)
async def invalid_photo(message: Message):
    """Якщо адмін надіслав не фото на цьому кроці."""
    await message.answer(
        "⚠️ Будь ласка, надішліть фотографію або натисніть «Пропустити цей крок».",
        reply_markup=get_skip_and_cancel_kb("photo")
    )


@router.message(ManualPostFSM.waiting_for_title, F.text)
async def process_title(message: Message, state: FSMContext):
    """Отримання назви товару."""
    title = message.text.strip()
    if not title:
        await message.answer("⚠️ Назва не може бути порожньою. Введіть назву товару:")
        return

    await state.update_data(title=title)
    await state.set_state(ManualPostFSM.waiting_for_description)
    await message.answer(
        "📝 <b>Крок 3/4: Опис товару</b>\n\nВведіть опис товару, характеристики або особливості:",
        reply_markup=get_cancel_only_kb(),
        parse_mode="HTML"
    )


@router.message(ManualPostFSM.waiting_for_description, F.text)
async def process_description(message: Message, state: FSMContext):
    """Отримання опису товару."""
    description = message.text.strip()
    await state.update_data(description=description)
    await state.set_state(ManualPostFSM.waiting_for_price)
    await message.answer(
        "💰 <b>Крок 4/4: Вартість / Ціна товару</b>\n\n"
        "Введіть ціну (наприклад: <code>1 250 грн</code> або <code>Від 500 грн</code>) "
        "або натисніть «Пропустити цей крок»:",
        reply_markup=get_skip_and_cancel_kb("price"),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "fsm:skip:price", ManualPostFSM.waiting_for_price)
async def skip_price_step(callback: CallbackQuery, state: FSMContext):
    """Пропуск кроку введення ціни та фіналізація прев'ю."""
    await finish_post_creation(callback.message, state, price=None, user_id=callback.from_user.id)
    await callback.answer()


@router.message(ManualPostFSM.waiting_for_price, F.text)
async def process_price(message: Message, state: FSMContext):
    """Отримання ціни товару та фіналізація прев'ю."""
    price = message.text.strip()
    await finish_post_creation(message, state, price=price, user_id=message.from_user.id)


async def finish_post_creation(message: Message, state: FSMContext, price: str | None, user_id: int):
    """Збереження товару в БД та формування повідомлення попереднього перегляду (Preview)."""
    data = await state.get_data()
    await state.clear()

    title = data.get("title", "Без назви")
    description = data.get("description")
    photo_file_id = data.get("photo_file_id")

    # Зберігаємо в базі даних зі статусом 'pending'
    async with async_session_maker() as session:
        product = await ProductService.create_product(
            session=session,
            title=title,
            description=description,
            price=price,
            photo_file_id=photo_file_id,
            source="manual",
            status="pending"
        )

    # Відправляємо адміну прев'ю з кнопками модерації
    await PublisherService.send_product_post(
        bot=message.bot,
        chat_id=message.chat.id,
        product=product,
        is_preview=True,
        reply_markup=get_preview_moderation_kb(product.id, settings.MANAGER_USERNAME)
    )
