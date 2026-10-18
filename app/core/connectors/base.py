from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple


@dataclass
class PreparedPost:
    """Підготовлений вміст публікації для відправлення конектором."""
    title: Optional[str] = None
    body: str = ""
    photo_url: Optional[str] = None
    photo_file_id: Optional[str] = None
    manager_button_url: Optional[str] = None
    extra_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PublishResult:
    """Результат відправлення публікації в канал призначення."""
    success: bool
    external_id: Optional[str] = None
    error_message: Optional[str] = None
    raw_response: Optional[str] = None


class BasePublisherConnector(ABC):
    """Спільний абстрактний інтерфейс для всіх конекторів публікації."""

    @abstractmethod
    async def test_connection(self) -> Tuple[bool, str]:
        """Перевіряє доступність каналу та права на публікацію."""
        pass

    @abstractmethod
    async def publish(self, post: PreparedPost) -> PublishResult:
        """Публікує новий пост та повертає результат."""
        pass

    @abstractmethod
    async def update(self, external_id: str, post: PreparedPost) -> PublishResult:
        """Оновлює раніше опублікований пост (якщо підтримується платформою)."""
        pass

    @abstractmethod
    async def delete(self, external_id: str) -> PublishResult:
        """Видаляє раніше опублікований пост (якщо підтримується платформою)."""
        pass
