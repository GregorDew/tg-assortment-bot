import aiohttp
from typing import Any, Dict, List, Optional, Tuple
from app.core.security import validate_safe_url
from app.core.sources.base import BaseDataSource, DataRecord


class HttpApiDataSource(BaseDataSource):
    """Адаптер для отримання даних через зовнішній HTTP API."""

    def __init__(self, config: Dict[str, Any]):
        self.endpoint_url = config.get("endpoint_url", "")
        self.method = config.get("method", "GET").upper()
        self.headers = config.get("headers", {})
        self.auth_token = config.get("auth_token", "")
        self.items_path = config.get("items_path", "")  # e.g. "items" or "" for root list

        if self.auth_token:
            self.headers["Authorization"] = f"Bearer {self.auth_token}"

    async def _make_request(self) -> Any:
        is_safe, err_msg = validate_safe_url(self.endpoint_url)
        if not is_safe:
            raise ValueError(f"SSRF захист: {err_msg}")

        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.request(self.method, self.endpoint_url, headers=self.headers) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    raise RuntimeError(f"HTTP {resp.status}: {text[:200]}")
                return await resp.json()

    def _extract_items(self, json_data: Any) -> List[Dict[str, Any]]:
        if isinstance(json_data, list):
            return [x for x in json_data if isinstance(x, dict)]

        if isinstance(json_data, dict):
            if self.items_path and self.items_path in json_data:
                target = json_data[self.items_path]
                if isinstance(target, list):
                    return [x for x in target if isinstance(x, dict)]

            for key in ("items", "data", "results", "products"):
                if key in json_data and isinstance(json_data[key], list):
                    return [x for x in json_data[key] if isinstance(x, dict)]

            return [json_data]
        return []

    async def test_connection(self) -> Tuple[bool, str]:
        try:
            data = await self._make_request()
            items = self._extract_items(data)
            return True, f"Успішно підключено! Отримано {len(items)} записів."
        except Exception as e:
            return False, f"Помилка HTTP API: {e}"

    async def get_tables_and_views(self) -> List[str]:
        # Для HTTP API "таблицею" є назва ресурсу або endpoint
        return ["api_response"]

    async def get_table_schema(self, table_name: str) -> List[str]:
        try:
            data = await self._make_request()
            items = self._extract_items(data)
            if items:
                return sorted(list(items[0].keys()))
            return ["id", "title", "description", "price"]
        except Exception:
            return ["id", "title", "description", "price"]

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
        data = await self._make_request()
        items = self._extract_items(data)

        records = []
        for item in items[:limit]:
            filtered_data = {k: item.get(k) for k in fields} if fields else item
            rec_id = str(item.get(pk_field, ""))
            records.append(
                DataRecord(
                    id=rec_id,
                    data=filtered_data,
                    row_hash=DataRecord.compute_hash(filtered_data)
                )
            )
        return records
