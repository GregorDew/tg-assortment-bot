from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_admin_main_kb(auto_post_enabled: bool) -> InlineKeyboardMarkup:
    """Головна інлайн-клавіатура панелі адміністратора (усі 6 розділів системи)."""
    status_icon = "🟢 УВІМКНЕНО" if auto_post_enabled else "🔴 ВИМКНЕНО"

    keyboard = [
        [
            InlineKeyboardButton(text="🗄 Джерела даних", callback_data="menu:sources"),
            InlineKeyboardButton(text="📢 Канали публікації", callback_data="menu:channels")
        ],
        [
            InlineKeyboardButton(text="📦 Погодження", callback_data="menu:moderation")
        ],
        [
            InlineKeyboardButton(text="📝 Шаблони", callback_data="menu:templates"),
            InlineKeyboardButton(text="📊 Журнал дій", callback_data="menu:logs")
        ],
        [
            InlineKeyboardButton(text="📝 Створити пост вручну", callback_data="admin:create_post")
        ],
        [
            InlineKeyboardButton(text=f"🔄 Автопост: {status_icon}", callback_data="admin:toggle_autopost")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_back_to_main_kb() -> InlineKeyboardMarkup:
    """Кнопка повернення до головного меню."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 До головного меню", callback_data="menu:main")]
        ]
    )



def get_channel_post_kb(manager_username: str | None = None) -> InlineKeyboardMarkup | None:
    """Клавіатура під постом у каналі/групі з кнопкою переходу до продавця."""
    if not manager_username:
        return None

    username = manager_username.strip().lstrip("@")
    if not username:
        return None

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💬 Написати продавцю",
                    url=f"https://t.me/{username}"
                )
            ]
        ]
    )


def get_preview_moderation_kb(product_id: int, manager_username: str | None = None) -> InlineKeyboardMarkup:
    """Кнопки прев'ю: посилання на продавця, публікація, відхилення та редагування."""
    keyboard = []

    # 1. Кнопка зв'язку з продавцем (як покупці бачитимуть її у пості)
    if manager_username:
        username = manager_username.strip().lstrip("@")
        if username:
            keyboard.append([
                InlineKeyboardButton(
                    text="💬 Написати продавцю (як у пості)",
                    url=f"https://t.me/{username}"
                )
            ])

    # 2. Кнопки модерації
    keyboard.append([
        InlineKeyboardButton(
            text="✅ Опублікувати в канали",
            callback_data=f"mod:publish:{product_id}"
        ),
        InlineKeyboardButton(
            text="❌ Відхилити",
            callback_data=f"mod:reject:{product_id}"
        )
    ])

    # 3. Кнопка редагування посту
    keyboard.append([
        InlineKeyboardButton(
            text="✏️ Редагувати пост",
            callback_data=f"mod:edit:{product_id}"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_edit_menu_kb(product_id: int) -> InlineKeyboardMarkup:
    """Меню вибору поля для редагування."""
    keyboard = [
        [
            InlineKeyboardButton(text="🖼 Змінити фото", callback_data=f"edit_f:photo:{product_id}"),
            InlineKeyboardButton(text="✏️ Змінити назву", callback_data=f"edit_f:title:{product_id}")
        ],
        [
            InlineKeyboardButton(text="📝 Змінити опис", callback_data=f"edit_f:desc:{product_id}"),
            InlineKeyboardButton(text="💰 Змінити ціну", callback_data=f"edit_f:price:{product_id}")
        ],
        [
            InlineKeyboardButton(text="🔙 Повернутися до погодження", callback_data=f"edit_f:back:{product_id}")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_cancel_edit_kb(product_id: int, allow_remove_photo: bool = False) -> InlineKeyboardMarkup:
    """Клавіатура для скасування редагування або видалення фото."""
    keyboard = []
    if allow_remove_photo:
        keyboard.append([
            InlineKeyboardButton(
                text="🗑 Видалити фото (зробити текстовим)",
                callback_data=f"edit_f:remove_photo:{product_id}"
            )
        ])
    keyboard.append([
        InlineKeyboardButton(
            text="❌ Скасувати редагування",
            callback_data=f"edit_f:back:{product_id}"
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)



def get_skip_and_cancel_kb(field: str) -> InlineKeyboardMarkup:
    """Клавіатура для FSM з можливістю пропустити необов'язкове поле або скасувати."""
    keyboard = [
        [
            InlineKeyboardButton(
                text="⏭ Пропустити цей крок",
                callback_data=f"fsm:skip:{field}"
            )
        ],
        [
            InlineKeyboardButton(
                text="❌ Скасувати створення",
                callback_data="fsm:cancel"
            )
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_cancel_only_kb() -> InlineKeyboardMarkup:
    """Клавіатура для обов'язкових кроків FSM (лише кнопка скасування)."""
    keyboard = [
        [
            InlineKeyboardButton(
                text="❌ Скасувати створення",
                callback_data="fsm:cancel"
            )
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
