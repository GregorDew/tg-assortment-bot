import asyncio
import base64
import aiohttp
from typing import Any, Dict, Optional, Tuple
from app.core.connectors.base import BasePublisherConnector, PreparedPost, PublishResult
from app.core.security import validate_safe_url


class HttpApiPublisherConnector(BasePublisherConnector):
    """Універсальний конектор для публікації на сторонні сервери/сайти через HTTP API."""

    def __init__(self, config: Dict[str, Any]):
        self.endpoint_url = config.get("endpoint_url", "").strip()
        self.method = config.get("method", "POST").upper()
        self.headers = config.get("headers", {})
        self.auth_type = config.get("auth_type", "none").lower()  # none, bearer, basic, api_key
        self.auth_token = config.get("auth_token", "")
        self.auth_user = config.get("auth_user", "")
        self.auth_pass = config.get("auth_pass", "")
        self.api_key_header = config.get("api_key_header", "X-API-Key")
        self.timeout_sec = int(config.get("timeout_sec", 15))
        self.max_retries = int(config.get("max_retries", 2))

        # Налаштування авторизації
        if self.auth_type == "bearer" and self.auth_token:
            self.headers["Authorization"] = f"Bearer {self.auth_token}"
        elif self.auth_type == "basic" and self.auth_user:
            creds = f"{self.auth_user}:{self.auth_pass}".encode()
            b64_creds = base64.b64encode(creds).decode()
            self.headers["Authorization"] = f"Basic {b64_creds}"
        elif self.auth_type == "api_key" and self.auth_token:
            self.headers[self.api_key_header] = self.auth_token

        if "Content-Type" not in self.headers:
            self.headers["Content-Type"] = "application/json"

    async def _request(self, method: str, url: str, json_data: Dict[str, Any]) -> Tuple[int, str]:
        is_safe, err_msg = validate_safe_url(url)
        if not is_safe:
            raise ValueError(f"SSRF захист: {err_msg}")

        timeout = aiohttp.ClientTimeout(total=self.timeout_sec)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for attempt in range(self.max_retries + 1):
                try:
                    async with session.request(method, url, json=json_data, headers=self.headers) as resp:
                        resp_text = await resp.text()
                        return resp.status, resp_text
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    if attempt == self.max_retries:
                        raise e
                    await asyncio.sleep(1.0 * (attempt + 1))
        return 0, "No response"

    async def test_connection(self) -> Tuple[bool, str]:
        if not self.endpoint_url:
            return False, "Не вказано endpoint_url. Потрібен ваш URL, який приймає JSON."
        try:
            probe = PreparedPost(
                title="Тест підключення",
                body="Тестовий запит від бота (поле extra_data.test=true).",
                extra_data={"test": True},
            )
            result = await self.publish(probe)
            if result.success:
                return True, f"HTTP API прийняв тестовий запит ({self.method} {self.endpoint_url})."
            return False, (
                "Сервер не прийняв тестовий POST/запит. "
                f"{result.error_message}\n"
                "Бот не хостить HTTP API сам — потрібен ваш endpoint."
            )
        except Exception as e:
            return False, f"Помилка з'єднання з HTTP API: {e}"

    def _build_payload(self, post: PreparedPost) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "title": post.title,
            "body": post.body,
            "photo_url": post.photo_url,
            "manager_button_url": post.manager_button_url,
            "extra_data": post.extra_data
        }
        return payload

    async def publish(self, post: PreparedPost) -> PublishResult:
        try:
            payload = self._build_payload(post)
            status, text = await self._request(self.method, self.endpoint_url, payload)
            if 200 <= status < 300:
                import json
                ext_id = None
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        ext_id = str(parsed.get("id") or parsed.get("item_id") or "")
                except Exception:
                    pass
                return PublishResult(success=True, external_id=ext_id, raw_response=text[:250])
            return PublishResult(success=False, error_message=f"HTTP {status}: {text[:200]}")
        except Exception as e:
            return PublishResult(success=False, error_message=str(e))

    async def update(self, external_id: str, post: PreparedPost) -> PublishResult:
        try:
            url = f"{self.endpoint_url}/{external_id}" if external_id else self.endpoint_url
            payload = self._build_payload(post)
            status, text = await self._request("PUT", url, payload)
            if 200 <= status < 300:
                return PublishResult(success=True, external_id=external_id, raw_response=text[:200])
            return PublishResult(success=False, error_message=f"HTTP PUT {status}: {text[:200]}")
        except Exception as e:
            return PublishResult(success=False, error_message=str(e))

    async def delete(self, external_id: str) -> PublishResult:
        try:
            url = f"{self.endpoint_url}/{external_id}" if external_id else self.endpoint_url
            status, text = await self._request("DELETE", url, {})
            if 200 <= status < 300:
                return PublishResult(success=True, external_id=external_id)
            return PublishResult(success=False, error_message=f"HTTP DELETE {status}: {text[:200]}")
        except Exception as e:
            return PublishResult(success=False, error_message=str(e))
