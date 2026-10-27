import html
import logging
from typing import Optional, Union
from aiogram import Bot
from aiogram.types import Message
from app.database.models import Product

logger = logging.getLogger(__name__)


class PublisherService:
    @staticmethod
    def format_product_post(product: Product, is_preview: bool = False) -> str:
        """
        Форматує текст повідомлення про оновлення асортименту у форматі HTML.
        """
        escaped_title = html.escape(product.title)
        lines = []

        if is_preview:
            lines.append("👁 <b>[ПОПЕРЕДНІЙ ПЕРЕГЛЯД ПОСТУ]</b>")
            lines.append("───────────────────────")
        else:
            lines.append("🔥 <b>ОНОВЛЕННЯ АСОРТИМЕНТУ!</b>")
            lines.append("───────────────────────")

        lines.append(f"📦 <b>{escaped_title}</b>\n")

        if product.description:
            escaped_desc = html.escape(product.description)
            lines.append(f"📝 <b>Опис:</b>\n{escaped_desc}\n")

        if product.price:
            escaped_price = html.escape(product.price)
            lines.append(f"💰 <b>Ціна:</b> {escaped_price}")

        lines.append("\n🛒 <i>Для замовлення звертайтесь до адміністратора!</i>")

        return "\n".join(lines)

    @staticmethod
    async def send_product_post(
        bot: Bot,
        chat_id: Union[int, str],
        product: Product,
        is_preview: bool = False,
        reply_markup=None
    ) -> Optional[Message]:
        """
        Публікує пост про товар у зазначений чат (канал/групу або адміну для прев'ю).
        Підтримує відправку фото (file_id або URL) або просто тексту, якщо фото відсутнє.
        """
        if not is_preview and reply_markup is None:
            from app.config import settings
            from app.keyboards.admin_kb import get_channel_post_kb
            reply_markup = get_channel_post_kb(settings.MANAGER_USERNAME)

        caption = PublisherService.format_product_post(product, is_preview=is_preview)

        try:
            # 1. Якщо є Telegram file_id
            if product.photo_file_id:
                try:
                    return await bot.send_photo(
                        chat_id=chat_id,
                        photo=product.photo_file_id,
                        caption=caption,
                        parse_mode="HTML",
                        reply_markup=reply_markup
                    )
                except Exception as photo_err:
                    logger.warning(
                        f"Не вдалося надіслати photo_file_id для товару #{product.id} ({photo_err}). "
                        "Відправляю як текстовий пост."
                    )
                    # Безпечний фолбек: якщо file_id чужий або застарілий, надсилаємо пост текстом
                    return await bot.send_message(
                        chat_id=chat_id,
                        text=caption,
                        parse_mode="HTML",
                        reply_markup=reply_markup
                    )

            # 2. Якщо є зовнішнє посилання на фото (URL)
            elif product.photo_url:
                try:
                    return await bot.send_photo(
                        chat_id=chat_id,
                        photo=product.photo_url,
                        caption=caption,
                        parse_mode="HTML",
                        reply_markup=reply_markup
                    )
                except Exception as url_err:
                    logger.warning(
                        f"Не вдалося завантажити photo_url для товару #{product.id} ({url_err}). "
                        "Відправляю як текстовий пост."
                    )
                    return await bot.send_message(
                        chat_id=chat_id,
                        text=caption,
                        parse_mode="HTML",
                        reply_markup=reply_markup
                    )

            # 3. Якщо фото немає - відправляємо як текстове повідомлення
            else:
                return await bot.send_message(
                    chat_id=chat_id,
                    text=caption,
                    parse_mode="HTML",
                    reply_markup=reply_markup
                )

        except Exception as e:
            logger.error(f"Помилка при надсиланні посту товару #{product.id} в чат {chat_id}: {e}")
            raise e
