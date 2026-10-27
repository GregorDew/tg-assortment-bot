from typing import Any, Dict, Optional, Tuple

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

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
            inline_keyboard=[[InlineKeyboardButton(text="💬 Написати продавцю", url=manager_url)]]
        )

    async def _check_post_rights(self) -> Tuple[bool, str]:
        try:
            chat = await self.bot.get_chat(chat_id=self.chat_id)
        except Exception as exc:
            return False, f"Не вдалося відкрити чат {self.chat_id}: {exc}"

        title = chat.title or chat.username or str(chat.id)
        resolved_id = chat.id
        me = await self.bot.get_me()
        try:
            member = await self.bot.get_chat_member(chat_id=resolved_id, user_id=me.id)
        except Exception as exc:
            return False, (
                f"Чат «{title}» знайдено, але бота там немає або немає прав. "
                f"Додайте @{me.username} адміністратором з правом публікації. Деталі: {exc}"
            )

        status = getattr(member, "status", None)
        if status in ("left", "kicked"):
            return False, (
                f"Бот не є учасником «{title}». Додайте @{me.username} у канал/групу "
                "як адміністратора з правом «Публікація повідомлень»."
            )

        chat_type = getattr(chat, "type", "")
        if chat_type == "channel":
            can_post = bool(getattr(member, "can_post_messages", False))
            if status != "administrator" or not can_post:
                return False, (
                    f"Бот бачить канал «{title}», але НЕ може публікувати.\n"
                    f"1) Додайте @{me.username} в адміністратори каналу.\n"
                    "2) Увімкніть право «Публікація повідомлень».\n"
                    "Перевірка з'єднання без тестового посту раніше це пропускала."
                )

        self.chat_id = resolved_id
        return True, f"Успішно: «{title}» (id={resolved_id}). Бот може публікувати."

    async def test_connection(self) -> Tuple[bool, str]:
        ok, msg = await self._check_post_rights()
        if not ok:
            return False, msg
        probe = PreparedPost(
            title="Тест підключення",
            body=(
                "✅ <b>Тестове повідомлення від бота</b>\n"
                "Якщо ви це бачите в каналі — публікація працює.\n"
                "Далі сюди приходитимуть погоджені пости."
            ),
        )
        result = await self.publish(probe)
        if not result.success:
            return False, f"Права ніби є, але відправка не вдалася: {result.error_message}"
        return True, msg + " Тестовий пост надіслано в канал."

    async def _send(self, post: PreparedPost, parse_mode: Optional[str]) -> Any:
        reply_markup = self._build_keyboard(post.manager_button_url)
        caption = post.body
        if (post.photo_file_id or post.photo_url or post.photo_blob) and caption and len(caption) > 1024:
            caption = caption[:1000] + "…"

        # 1. Якщо є бінарний файл прямо з БД
        if post.photo_blob:
            try:
                from aiogram.types import BufferedInputFile
                input_file = BufferedInputFile(post.photo_blob, filename="photo.jpg")
                return await self.bot.send_photo(
                    chat_id=self.chat_id,
                    photo=input_file,
                    caption=caption,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                )
            except Exception:
                pass

        # 2. Якщо є file_id
        if post.photo_file_id:
            try:
                return await self.bot.send_photo(
                    chat_id=self.chat_id,
                    photo=post.photo_file_id,
                    caption=caption,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                )
            except Exception:
                # Фолбек на текст, якщо file_id недійсний
                return await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=caption,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                )
        if post.photo_url:
            try:
                return await self.bot.send_photo(
                    chat_id=self.chat_id,
                    photo=post.photo_url,
                    caption=caption,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                )
            except Exception:
                return await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=caption,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                )
        return await self.bot.send_message(
            chat_id=self.chat_id,
            text=caption,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )

    async def publish(self, post: PreparedPost) -> PublishResult:
        try:
            try:
                msg = await self._send(post, "HTML")
            except TelegramBadRequest as parse_err:
                if "parse" in str(parse_err).lower() or "entities" in str(parse_err).lower():
                    msg = await self._send(post, None)
                else:
                    raise
            return PublishResult(
                success=True,
                external_id=str(msg.message_id),
                raw_response=f"Telegram message_id={msg.message_id} chat={self.chat_id}",
            )
        except (TelegramBadRequest, TelegramForbiddenError, Exception) as exc:
            return PublishResult(success=False, error_message=str(exc))

    async def update(self, external_id: str, post: PreparedPost) -> PublishResult:
        try:
            msg_id = int(external_id)
            reply_markup = self._build_keyboard(post.manager_button_url)
            try:
                await self.bot.edit_message_caption(
                    chat_id=self.chat_id,
                    message_id=msg_id,
                    caption=post.body,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                )
            except Exception:
                await self.bot.edit_message_text(
                    chat_id=self.chat_id,
                    message_id=msg_id,
                    text=post.body,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                )
            return PublishResult(success=True, external_id=external_id)
        except Exception as exc:
            return PublishResult(success=False, error_message=str(exc))

    async def delete(self, external_id: str) -> PublishResult:
        try:
            msg_id = int(external_id)
            await self.bot.delete_message(chat_id=self.chat_id, message_id=msg_id)
            return PublishResult(success=True, external_id=external_id)
        except Exception as exc:
            return PublishResult(success=False, error_message=str(exc))
