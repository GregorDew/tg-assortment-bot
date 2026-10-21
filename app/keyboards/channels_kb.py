from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_channels_menu_kb() -> InlineKeyboardMarkup:
    """Головне меню розділу Канали публікації."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ Додати канал", callback_data="chn:add"),
                InlineKeyboardButton(text="📋 Список каналів", callback_data="chn:list")
            ],
            [
                InlineKeyboardButton(text="🔙 До головного меню", callback_data="menu:main")
            ]
        ]
    )


def get_channel_types_kb() -> InlineKeyboardMarkup:
    """Вибір платформи каналу публікації."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✈️ Telegram", callback_data="chn_type:telegram"),
                InlineKeyboardButton(text="🎮 Discord", callback_data="chn_type:discord")
            ],
            [
                InlineKeyboardButton(text="🌐 HTTP API", callback_data="chn_type:http_api"),
                InlineKeyboardButton(text="📧 Email (SMTP)", callback_data="chn_type:email")
            ],
            [
                InlineKeyboardButton(text="❌ Скасувати", callback_data="fsm:cancel")
            ]
        ]
    )


def get_channel_manage_kb(channel_id: int, is_active: bool) -> InlineKeyboardMarkup:
    """Керування окремим каналом публікації."""
    status_text = "🔴 Вимкнути" if is_active else "🟢 Увімкнути"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📨 Тестовий пост", callback_data=f"chn_action:test:{channel_id}"),
                InlineKeyboardButton(text=status_text, callback_data=f"chn_action:toggle:{channel_id}")
            ],
            [
                InlineKeyboardButton(text="🗑 Видалити канал", callback_data=f"chn_action:delete_confirm:{channel_id}")
            ],
            [
                InlineKeyboardButton(text="🔙 До списку каналів", callback_data="chn:list")
            ]
        ]
    )
