from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_admin_main_kb(auto_post_enabled: bool) -> InlineKeyboardMarkup:
    """Головна інлайн-клавіатура панелі адміністратора."""
    status_icon = "🟢 УВІМКНЕНО" if auto_post_enabled else "🔴 ВИМКНЕНО"

    keyboard = [
        [
            InlineKeyboardButton(
                text="📝 Створити пост вручну",
                callback_data="admin:create_post"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"🔄 Автопост: {status_icon}",
                callback_data="admin:toggle_autopost"
            )
        ],
        [
            InlineKeyboardButton(
                text="➕ Додати тестовий товар у БД",
                callback_data="admin:add_test_product"
            )
        ],
        [
            InlineKeyboardButton(
                text="📋 Останні оновлення (БД)",
                callback_data="admin:list_products"
            )
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_preview_moderation_kb(product_id: int) -> InlineKeyboardMarkup:
    """Кнопки підтвердження або відхилення публікації."""
    keyboard = [
        [
            InlineKeyboardButton(
                text="✅ Опублікувати в групу",
                callback_data=f"mod:publish:{product_id}"
            ),
            InlineKeyboardButton(
                text="❌ Відхилити",
                callback_data=f"mod:reject:{product_id}"
            )
        ]
    ]
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
