from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_templates_menu_kb() -> InlineKeyboardMarkup:
    """Головне меню розділу Шаблони."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ Створити шаблон", callback_data="tpl:add"),
                InlineKeyboardButton(text="📋 Список шаблонів", callback_data="tpl:list")
            ],
            [
                InlineKeyboardButton(text="🔙 До головного меню", callback_data="menu:main")
            ]
        ]
    )


def get_template_platforms_kb() -> InlineKeyboardMarkup:
    """Вибір цільової платформи для шаблону."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🌐 Універсальний", callback_data="tpl_plat:universal"),
                InlineKeyboardButton(text="✈️ Telegram", callback_data="tpl_plat:telegram")
            ],
            [
                InlineKeyboardButton(text="🎮 Discord Embed", callback_data="tpl_plat:discord"),
                InlineKeyboardButton(text="📧 Email (HTML/Text)", callback_data="tpl_plat:email")
            ],
            [
                InlineKeyboardButton(text="🌐 HTTP API (JSON)", callback_data="tpl_plat:http_api")
            ],
            [
                InlineKeyboardButton(text="❌ Скасувати", callback_data="fsm:cancel")
            ]
        ]
    )


def get_template_manage_kb(template_id: int) -> InlineKeyboardMarkup:
    """Керування окремим шаблоном."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👁 Попередній перегляд", callback_data=f"tpl_action:preview:{template_id}"),
                InlineKeyboardButton(text="🗑 Видалити", callback_data=f"tpl_action:delete_confirm:{template_id}")
            ],
            [
                InlineKeyboardButton(text="🔙 До списку шаблонів", callback_data="tpl:list")
            ]
        ]
    )
