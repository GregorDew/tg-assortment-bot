from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class DataRecord:
    """Уніфікований запис, отриманий з будь-якого джерела даних."""
    id: str
    data: Dict[str, Any]
    row_hash: str = ""
    timestamp: Optional[datetime] = None

    def __post_init__(self):
        if not self.row_hash:
            self.row_hash = self.compute_hash(self.data)

    @staticmethod
    def compute_hash(data: Dict[str, Any]) -> str:
        """Обчислює детермінований MD5/SHA256 хеш рядка для виявлення змін."""
        # Сортуємо ключі для стабільності
        serialized = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class BaseDataSource(ABC):
    """Абстрактний базовий клас для всіх адаптерів джерел даних."""

    @abstractmethod
    async def test_connection(self) -> Tuple[bool, str]:
        """
        Перевіряє з'єднання та доступні дозволи.
        Повертає: (is_success, status_or_error_message).
        """
        pass

    @abstractmethod
    async def get_tables_and_views(self) -> List[str]:
        """Отримує список доступних таблиць і представлень (views)."""
        pass

    @abstractmethod
    async def get_table_schema(self, table_name: str) -> List[str]:
        """Отримує перелік стовпців для вказаної таблиці."""
        pass

    @abstractmethod
    async def fetch_records(
        self,
        table_name: str,
        fields: List[str],
        pk_field: str,
        tracking_mode: str = "incremental_id",
        tracking_field: Optional[str] = None,
        last_tracking_value: Optional[Any] = None,
        limit: int = 100
    ) -> List[DataRecord]:
        """
        Отримує записи з джерела з урахуванням режиму відстеження змін.
        """
        pass
