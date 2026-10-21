import asyncio
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional, Tuple
import aiosmtplib
from app.core.connectors.base import BasePublisherConnector, PreparedPost, PublishResult


class EmailPublisherConnector(BasePublisherConnector):
    """Конектор для відправлення повідомлень електронною поштою (SMTP)."""

    def __init__(self, config: Dict[str, Any]):
        self.smtp_host = config.get("smtp_host", "smtp.gmail.com").strip()
        self.smtp_port = int(config.get("smtp_port", 587))
        self.smtp_user = config.get("smtp_user", "").strip()
        self.smtp_password = config.get("smtp_password", "").strip()
        self.use_tls = bool(config.get("use_tls", False))  # SSL на порті 465
        self.start_tls = bool(config.get("start_tls", True))  # STARTTLS на порті 587
        self.from_email = config.get("from_email", self.smtp_user).strip()
        
        recipients_raw = config.get("recipients", "")
        if isinstance(recipients_raw, list):
            self.recipients = [str(r).strip() for r in recipients_raw if str(r).strip()]
        elif isinstance(recipients_raw, str):
            self.recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]
        else:
            self.recipients = []

    async def _get_client(self) -> aiosmtplib.SMTP:
        client = aiosmtplib.SMTP(
            hostname=self.smtp_host,
            port=self.smtp_port,
            use_tls=self.use_tls,
            start_tls=self.start_tls and not self.use_tls,
            timeout=15
        )
        await client.connect()
        if self.smtp_user and self.smtp_password:
            await client.login(self.smtp_user, self.smtp_password)
        return client

    async def test_connection(self) -> Tuple[bool, str]:
        if not self.recipients:
            return False, "Немає отримувачів. У кінці рядка вкажіть email через кому."
        try:
            probe = PreparedPost(
                title="Тест SMTP від бота",
                body="Якщо цей лист дійшов — Email-канал працює.",
            )
            result = await self.publish(probe)
            if result.success:
                return True, f"Тестовий лист надіслано через {self.smtp_host}:{self.smtp_port}."
            return False, f"SMTP не відправив лист: {result.error_message}"
        except Exception as e:
            return False, f"Помилка підключення до SMTP: {e}"

    def _create_message(self, post: PreparedPost) -> MIMEMultipart:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = post.title or "Оновлення асортименту"
        msg["From"] = self.from_email
        msg["To"] = ", ".join(self.recipients)

        # Текстова частина
        text_content = post.body
        if post.manager_button_url:
            text_content += f"\n\nЗв'язок з менеджером: {post.manager_button_url}"
        part1 = MIMEText(text_content, "plain", "utf-8")
        msg.attach(part1)

        # HTML частина
        html_body = f"<html><body><h2>{post.title or ''}</h2><p>{post.body.replace('\n', '<br>')}</p>"
        if post.photo_url:
            html_body += f'<p><img src="{post.photo_url}" style="max-width:500px;border-radius:8px;" /></p>'
        if post.manager_button_url:
            html_body += f'<p><a href="{post.manager_button_url}" style="display:inline-block;padding:10px 20px;background:#0088cc;color:#fff;text-decoration:none;border-radius:4px;">Написати продавцю</a></p>'
        html_body += "</body></html>"

        part2 = MIMEText(html_body, "html", "utf-8")
        msg.attach(part2)
        return msg

    async def publish(self, post: PreparedPost) -> PublishResult:
        if not self.recipients:
            return PublishResult(success=False, error_message="Список отримувачів (recipients) порожній.")

        try:
            msg = self._create_message(post)
            client = await self._get_client()
            try:
                resp = await client.send_message(msg)
                ext_id = f"email_{msg['Subject']}_{len(self.recipients)}"
                return PublishResult(success=True, external_id=ext_id, raw_response=str(resp))
            finally:
                await client.quit()
        except Exception as e:
            return PublishResult(success=False, error_message=str(e))

    async def update(self, external_id: str, post: PreparedPost) -> PublishResult:
        # Для Email оновлення відправляє лист із приміткою [ОНОВЛЕНО]
        post_copy = PreparedPost(
            title=f"[ОНОВЛЕНО] {post.title or ''}",
            body=post.body,
            photo_url=post.photo_url,
            manager_button_url=post.manager_button_url,
            extra_data=post.extra_data
        )
        return await self.publish(post_copy)

    async def delete(self, external_id: str) -> PublishResult:
        # Email не підтримує фізичне відкликання після доставки
        return PublishResult(success=True, external_id=external_id, raw_response="Email deletion not supported by SMTP protocol")
