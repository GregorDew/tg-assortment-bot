import asyncio
import aiohttp
from typing import Any, Dict, Optional, Tuple
from app.core.connectors.base import BasePublisherConnector, PreparedPost, PublishResult
from app.core.security import validate_safe_url


class DiscordPublisherConnector(BasePublisherConnector):
    """Конектор для публікації в Discord через Webhook або Bot API."""

    def __init__(self, config: Dict[str, Any]):
        self.webhook_url = config.get("webhook_url", "").strip()
        self.bot_token = config.get("bot_token", "").strip()
        self.channel_id = config.get("channel_id", "").strip()
        self.username = config.get("username", "Store Bot")
        self.avatar_url = config.get("avatar_url", "")

    async def _send_with_retry(self, method: str, url: str, payload: Dict[str, Any], headers: Dict[str, str]) -> Tuple[int, Dict[str, Any], str]:
        """Відправляє HTTP запит з обробкою rate limits (HTTP 429)."""
        is_safe, err_msg = validate_safe_url(url)
        if not is_safe:
            raise ValueError(f"SSRF захист: {err_msg}")

        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for attempt in range(3):
                async with session.request(method, url, json=payload, headers=headers) as resp:
                    resp_text = await resp.text()
                    if resp.status == 429:
                        # Обробка лімітів Discord
                        try:
                            rate_data = await resp.json()
                            retry_after = float(rate_data.get("retry_after", 1.0))
                        except Exception:
                            retry_after = 1.0
                        await asyncio.sleep(min(retry_after, 5.0))
                        continue

                    try:
                        data = await resp.json() if resp_text else {}
                    except Exception:
                        data = {}
                    return resp.status, data, resp_text
            return 429, {}, "Exceeded rate limit retries"

    async def test_connection(self) -> Tuple[bool, str]:
        try:
            if self.webhook_url:
                is_safe, err_msg = validate_safe_url(self.webhook_url)
                if not is_safe:
                    return False, err_msg

                timeout = aiohttp.ClientTimeout(total=10)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(self.webhook_url) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            channel_name = data.get("name", "Discord Webhook")
                            return True, f"Успішно підключено до Discord Webhook: «{channel_name}»!"
                        return False, f"Помилка перевірки Discord Webhook: HTTP {resp.status}"

            elif self.bot_token and self.channel_id:
                url = f"https://discord.com/api/v10/channels/{self.channel_id}"
                headers = {"Authorization": f"Bot {self.bot_token}"}
                status, data, text = await self._send_with_retry("GET", url, {}, headers)
                if status == 200:
                    ch_name = data.get("name", self.channel_id)
                    return True, f"Успішно підключено до каналу Discord #{ch_name}!"
                return False, f"Помилка Discord Bot API: HTTP {status} ({text[:100]})"

            return False, "Не вказано Webhook URL або Bot Token + Channel ID"
        except Exception as e:
            return False, f"Помилка підключення до Discord: {e}"

    def _build_payload(self, post: PreparedPost) -> Dict[str, Any]:
        embed: Dict[str, Any] = {
            "title": post.title or "Оновлення асортименту",
            "description": post.body,
            "color": 0x3498DB
        }

        if post.photo_url:
            embed["image"] = {"url": post.photo_url}

        if post.manager_button_url:
            embed["footer"] = {"text": f"Замовити: {post.manager_button_url}"}

        payload: Dict[str, Any] = {
            "embeds": [embed]
        }
        if self.username:
            payload["username"] = self.username
        if self.avatar_url:
            payload["avatar_url"] = self.avatar_url

        return payload

    async def publish(self, post: PreparedPost) -> PublishResult:
        try:
            payload = self._build_payload(post)

            if self.webhook_url:
                # Додаємо ?wait=true, щоб Discord повернув об'єкт створеного повідомлення з id
                url = self.webhook_url + ("&wait=true" if "?" in self.webhook_url else "?wait=true")
                status, data, text = await self._send_with_retry("POST", url, payload, {})
                if status in (200, 204):
                    msg_id = str(data.get("id", ""))
                    return PublishResult(success=True, external_id=msg_id, raw_response=text[:200])
                return PublishResult(success=False, error_message=f"Discord HTTP {status}: {text[:200]}")

            elif self.bot_token and self.channel_id:
                url = f"https://discord.com/api/v10/channels/{self.channel_id}/messages"
                headers = {"Authorization": f"Bot {self.bot_token}"}
                status, data, text = await self._send_with_retry("POST", url, payload, headers)
                if status in (200, 201):
                    msg_id = str(data.get("id", ""))
                    return PublishResult(success=True, external_id=msg_id, raw_response=text[:200])
                return PublishResult(success=False, error_message=f"Discord HTTP {status}: {text[:200]}")

            return PublishResult(success=False, error_message="Не налаштовано параметри підключення Discord.")
        except Exception as e:
            return PublishResult(success=False, error_message=str(e))

    async def update(self, external_id: str, post: PreparedPost) -> PublishResult:
        try:
            if not external_id:
                return PublishResult(success=False, error_message="Відсутній external_id для оновлення.")

            payload = self._build_payload(post)

            if self.webhook_url:
                url = f"{self.webhook_url}/messages/{external_id}"
                status, _, text = await self._send_with_retry("PATCH", url, payload, {})
                if status in (200, 204):
                    return PublishResult(success=True, external_id=external_id)
                return PublishResult(success=False, error_message=f"Discord PATCH {status}: {text[:200]}")

            elif self.bot_token and self.channel_id:
                url = f"https://discord.com/api/v10/channels/{self.channel_id}/messages/{external_id}"
                headers = {"Authorization": f"Bot {self.bot_token}"}
                status, _, text = await self._send_with_retry("PATCH", url, payload, headers)
                if status in (200, 204):
                    return PublishResult(success=True, external_id=external_id)
                return PublishResult(success=False, error_message=f"Discord PATCH {status}: {text[:200]}")

            return PublishResult(success=False, error_message="Не налаштовано Discord для оновлення.")
        except Exception as e:
            return PublishResult(success=False, error_message=str(e))

    async def delete(self, external_id: str) -> PublishResult:
        try:
            if not external_id:
                return PublishResult(success=False, error_message="Відсутній external_id для видалення.")

            if self.webhook_url:
                url = f"{self.webhook_url}/messages/{external_id}"
                status, _, text = await self._send_with_retry("DELETE", url, {}, {})
                if status in (200, 204):
                    return PublishResult(success=True, external_id=external_id)
                return PublishResult(success=False, error_message=f"Discord DELETE {status}: {text[:200]}")

            elif self.bot_token and self.channel_id:
                url = f"https://discord.com/api/v10/channels/{self.channel_id}/messages/{external_id}"
                headers = {"Authorization": f"Bot {self.bot_token}"}
                status, _, text = await self._send_with_retry("DELETE", url, {}, headers)
                if status in (200, 204):
                    return PublishResult(success=True, external_id=external_id)
                return PublishResult(success=False, error_message=f"Discord DELETE {status}: {text[:200]}")

            return PublishResult(success=False, error_message="Не налаштовано Discord для видалення.")
        except Exception as e:
            return PublishResult(success=False, error_message=str(e))
