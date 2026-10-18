from typing import Any, Dict, Optional, Tuple
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from app.config import settings
from app.core.connectors.base import BasePublisherConnector, PreparedPost, PublishResult


class TelegramPublisherConnector(BasePublisherConnector):
    """Конектор для публікації в Telegram-канали та групи."""

    def __init__(self, config: Dict[str, Any], bot: Optional[Bot] = None):
        self.chat_id = config.get("chat_id") or settings.TARGET_CHAT_ID
        self.bot_token = config.get("bot_token") or settings.BOT_TOKEN
        self._custom_bot = None
        if bot:
            self.bot = bot
        else:
            self.bot = Bot(token=self.bot_token)
            self._custom_bot = self.bot

    async def _close(self):
        if self._custom_bot:
            await self._custom_bot.session.close()

    def _build_keyboard(self, manager_url: Optional[str]) -> Optional[InlineKeyboardMarkup]:
        if not manager_url:
            return None
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💬 Написати продавцю", url=manager_url)]
            ]
        )

    async def test_connection(self) -> Tuple[bool, str]:
        try:
            chat = await self.bot.get_chat(chat_id=self.chat_id)
            title = chat.title or chat.username or str(chat.id)
            return True, f"Успішно підключено до Telegram-чату: «{title}»!"
        except Exception as e:
            return False, f"Помилка доступу до Telegram-чату {self.chat_id}: {e}"

    async def publish(self, post: PreparedPost) -> PublishResult:
        try:
            reply_markup = self._build_keyboard(post.manager_button_url)
            caption = post.body

            # 1. Якщо є Telegram file_id
            if post.photo_file_id:
                msg = await self.bot.send_photo(
                    chat_id=self.chat_id,
                    photo=post.photo_file_id,
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=reply_markup
                )
            # 2. Якщо є URL фото
            elif post.photo_url:
                msg = await self.bot.send_photo(
                    chat_id=self.chat_id,
                    photo=post.photo_url,
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=reply_markup
                )
            # 3. Текстове повідомлення
            else:
                msg = await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=caption,
                    parse_mode="HTML",
                    reply_markup=reply_markup
                )

            return PublishResult(
                success=True,
                external_id=str(msg.message_id),
                raw_response=f"Telegram message_id={msg.message_id}"
            )
        except Exception as e:
            return PublishResult(success=False, error_message=str(e))

    async def update(self, external_id: str, post: PreparedPost) -> PublishResult:
        try:
            msg_id = int(external_id)
            reply_markup = self._build_keyboard(post.manager_button_url)
            try:
                # Спробуємо оновити як підпис фото
                await self.bot.edit_message_caption(
                    chat_id=self.chat_id,
                    message_id=msg_id,
                    caption=post.body,
                    parse_mode="HTML",
                    reply_markup=reply_markup
                )
            except Exception:
                # Якщо це було суто текстове повідомлення
                await self.bot.edit_message_text(
                    chat_id=self.chat_id,
                    message_id=msg_id,
                    text=post.body,
                    parse_mode="HTML",
                    reply_markup=reply_markup
                )
            return PublishResult(success=True, external_id=external_id)
        except Exception as e:
            return PublishResult(success=False, error_message=str(e))

    async def delete(self, external_id: str) -> PublishResult:
        try:
            msg_id = int(external_id)
            await self.bot.delete_message(chat_id=self.chat_id, message_id=msg_id)
            return PublishResult(success=True, external_id=external_id)
        except Exception as e:
            return PublishResult(success=False, error_message=str(e))
