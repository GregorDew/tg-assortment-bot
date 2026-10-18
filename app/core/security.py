import base64
import hashlib
import ipaddress
import socket
from urllib.parse import urlparse
from cryptography.fernet import Fernet
from app.config import settings

_fernet_instance: Fernet | None = None


def _get_fernet() -> Fernet:
    """Отримує або ініціалізує симетричний шифрувальник Fernet."""
    global _fernet_instance
    if _fernet_instance is not None:
        return _fernet_instance

    key = settings.ENCRYPTION_KEY.strip()
    if not key:
        # Створюємо детермінований ключ на основі BOT_TOKEN, щоб розшифрування працювало після перезапуску
        salt = b"tg_universal_bot_salt_2026"
        derived = hashlib.pbkdf2_hmac("sha256", settings.BOT_TOKEN.encode(), salt, 100000)
        key = base64.urlsafe_b64encode(derived[:32]).decode()

    # Переконуємось, що ключ валідний base64 розміром 32 байти
    try:
        _fernet_instance = Fernet(key.encode())
    except Exception:
        # Якщо вказаний у .env ключ не відповідав формату Fernet
        derived = hashlib.sha256(key.encode()).digest()
        safe_key = base64.urlsafe_b64encode(derived)
        _fernet_instance = Fernet(safe_key)

    return _fernet_instance


def encrypt_secret(plain_text: str | None) -> str:
    """Шифрує чутливий рядок (пароль, токен, API ключ)."""
    if not plain_text:
        return ""
    fernet = _get_fernet()
    return fernet.encrypt(plain_text.encode("utf-8")).decode("utf-8")


def decrypt_secret(cipher_text: str | None) -> str:
    """Розшифровує чутливий рядок. Якщо не вдалося — повертає оригінал."""
    if not cipher_text:
        return ""
    try:
        fernet = _get_fernet()
        return fernet.decrypt(cipher_text.encode("utf-8")).decode("utf-8")
    except Exception:
        # Можливо рядок не був зашифрований
        return cipher_text


def mask_secret(secret: str | None) -> str:
    """Маскує чутливі дані для безпечного відображення в інтерфейсі або логах."""
    if not secret:
        return ""
    s = str(secret)
    if len(s) <= 4:
        return "****"
    return f"{s[:2]}****{s[-2:]}"


def validate_safe_url(url: str) -> tuple[bool, str]:
    """
    Захист від SSRF (Server-Side Request Forgery).
    Перевіряє, що URL не веде на приватні, петлеві чи локальні адреси.
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False, "Дозволені лише протоколи http та https."

        hostname = parsed.hostname
        if not hostname:
            return False, "Не вказано ім'я хоста."

        # Перевірка локальних імен
        lower_host = hostname.lower()
        if lower_host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            return False, "Звернення до локальних адрес заборонено."

        # Резолвимо IP адресу хоста
        try:
            ip_str = socket.gethostbyname(hostname)
            ip_obj = ipaddress.ip_address(ip_str)
        except Exception:
            # Якщо не вдалося резолвити, але це валідне доменне ім'я
            return True, ""

        if (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_multicast
            or ip_obj.is_reserved
        ):
            return False, f"Звернення до внутрішніх та приватних IP адрес заборонено ({ip_str})."

        return True, ""
    except Exception as e:
        return False, f"Невалідний URL: {e}"
