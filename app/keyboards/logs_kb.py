from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_logs_menu_kb(filter_type: str = "all") -> InlineKeyboardMarkup:
    """Клавіатура розділу Журнал і помилки."""
    all_btn = "• Всі •" if filter_type == "all" else "Всі"
    err_btn = "• Тільки помилки ❌ •" if filter_type == "failed" else "Тільки помилки ❌"
    succ_btn = "• Успішні ✅ •" if filter_type == "success" else "Успішні ✅"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=all_btn, callback_data="logs:filter:all"),
                InlineKeyboardButton(text=err_btn, callback_data="logs:filter:failed")
            ],
            [
                InlineKeyboardButton(text=succ_btn, callback_data="logs:filter:success"),
                InlineKeyboardButton(text="🔄 Оновити", callback_data=f"logs:filter:{filter_type}")
            ],
            [
                InlineKeyboardButton(text="🔁 Повторити всі помилки", callback_data="logs:retry_failed")
            ],
            [
                InlineKeyboardButton(text="🔙 До головного меню", callback_data="menu:main")
            ]
        ]
    )
