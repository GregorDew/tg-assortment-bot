from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import List


def get_sources_menu_kb() -> InlineKeyboardMarkup:
    """Головне меню розділу Джерела даних."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ Додати джерело", callback_data="src:add"),
                InlineKeyboardButton(text="📋 Мої підключення", callback_data="src:list")
            ],
            [
                InlineKeyboardButton(text="🔙 До головного меню", callback_data="menu:main")
            ]
        ]
    )


def get_source_types_kb() -> InlineKeyboardMarkup:
    """Вибір типу джерела даних (Крок 1 майстра)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🐘 PostgreSQL", callback_data="src_type:postgres"),
                InlineKeyboardButton(text="🐬 MySQL / MariaDB", callback_data="src_type:mysql")
            ],
            [
                InlineKeyboardButton(text="🗄 SQLite / SQL", callback_data="src_type:sqlite"),
                InlineKeyboardButton(text="🌐 HTTP API", callback_data="src_type:http_api")
            ],
            [
                InlineKeyboardButton(text="❌ Скасувати майстер", callback_data="fsm:cancel")
            ]
        ]
    )


def get_tracking_mode_kb() -> InlineKeyboardMarkup:
    """Вибір способу виявлення змін (Крок 7 майстра)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔢 За ID (новий > старого)", callback_data="track_mode:incremental_id")
            ],
            [
                InlineKeyboardButton(text="🕒 За часом оновлення (updated_at)", callback_data="track_mode:updated_at")
            ],
            [
                InlineKeyboardButton(text="🔍 За хешем рядка (Row Hash)", callback_data="track_mode:row_hash")
            ],
            [
                InlineKeyboardButton(text="❌ Скасувати", callback_data="fsm:cancel")
            ]
        ]
    )


def get_items_selection_kb(items: List[str], prefix: str, max_items: int = 12) -> InlineKeyboardMarkup:
    """Динамічна клавіатура для вибору таблиці або колонки."""
    keyboard = []
    # Розбиваємо на рядки по 2 кнопки
    row = []
    for item in items[:max_items]:
        row.append(InlineKeyboardButton(text=item[:25], callback_data=f"{prefix}:{item}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="fsm:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_source_manage_kb(source_id: int, is_active: bool) -> InlineKeyboardMarkup:
    """Кнопки керування окремим джерелом даних."""
    status_text = "🔴 Вимкнути" if is_active else "🟢 Увімкнути"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔄 Перевірити з'єднання", callback_data=f"src_action:test:{source_id}"),
                InlineKeyboardButton(text="👁 Тестова вибірка", callback_data=f"src_action:sample:{source_id}")
            ],
            [
                InlineKeyboardButton(text=status_text, callback_data=f"src_action:toggle:{source_id}"),
                InlineKeyboardButton(text="🗑 Видалити", callback_data=f"src_action:delete_confirm:{source_id}")
            ],
            [
                InlineKeyboardButton(text="🔙 До списку джерел", callback_data="src:list")
            ]
        ]
    )


def get_delete_confirm_kb(item_type: str, item_id: int) -> InlineKeyboardMarkup:
    """Підтвердження видалення елемента."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⚠️ ТАК, видалити", callback_data=f"del_confirm:{item_type}:{item_id}"),
                InlineKeyboardButton(text="❌ Скасувати", callback_data=f"del_cancel:{item_type}:{item_id}")
            ]
        ]
    )
