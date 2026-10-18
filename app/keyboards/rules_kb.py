from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_rules_menu_kb() -> InlineKeyboardMarkup:
    """Головне меню розділу Правила та маршрути."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ Створити правило", callback_data="rule:add"),
                InlineKeyboardButton(text="📋 Список правил", callback_data="rule:list")
            ],
            [
                InlineKeyboardButton(text="🔙 До головного меню", callback_data="menu:main")
            ]
        ]
    )


def get_rule_mode_kb() -> InlineKeyboardMarkup:
    """Вибір режиму роботи правила."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📦 З погодженням адмінами", callback_data="rule_mode:approval")
            ],
            [
                InlineKeyboardButton(text="⚡ Автоматична публікація", callback_data="rule_mode:auto")
            ],
            [
                InlineKeyboardButton(text="❌ Скасувати", callback_data="fsm:cancel")
            ]
        ]
    )


def get_rule_update_action_kb() -> InlineKeyboardMarkup:
    """Вибір дії при виявленні змін у записі."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📢 Нова публікація", callback_data="rule_upd:new_post")
            ],
            [
                InlineKeyboardButton(text="🔄 Оновити раніше опубліковане", callback_data="rule_upd:update_post")
            ],
            [
                InlineKeyboardButton(text="📦 Відправити на погодження", callback_data="rule_upd:approval")
            ],
            [
                InlineKeyboardButton(text="🙈 Ігнорувати зміну", callback_data="rule_upd:ignore")
            ],
            [
                InlineKeyboardButton(text="❌ Скасувати", callback_data="fsm:cancel")
            ]
        ]
    )


def get_rule_manage_kb(rule_id: int, is_active: bool) -> InlineKeyboardMarkup:
    """Керування окремим правилом."""
    status_text = "🔴 Зупинити" if is_active else "🟢 Запустити"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="▶️ Перевірити зараз", callback_data=f"rule_action:run:{rule_id}"),
                InlineKeyboardButton(text=status_text, callback_data=f"rule_action:toggle:{rule_id}")
            ],
            [
                InlineKeyboardButton(text="🗑 Видалити правило", callback_data=f"rule_action:delete_confirm:{rule_id}")
            ],
            [
                InlineKeyboardButton(text="🔙 До списку правил", callback_data="rule:list")
            ]
        ]
    )
