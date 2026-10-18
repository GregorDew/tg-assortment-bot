from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import text, inspect
from sqlalchemy.ext.asyncio import create_async_engine
from app.core.sources.base import BaseDataSource, DataRecord


class GenericSQLDataSource(BaseDataSource):
    """Адаптер для будь-яких SQL баз даних через SQLAlchemy (SQLite, PostgreSQL, тощо)."""

    def __init__(self, config: Dict[str, Any]):
        self.url = config.get("url", "")
        self.engine = create_async_engine(self.url, echo=False)

    async def test_connection(self) -> Tuple[bool, str]:
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1;"))
            return True, "Успішно підключено до бази даних!"
        except Exception as e:
            return False, f"Помилка підключення: {e}"

    async def get_tables_and_views(self) -> List[str]:
        async with self.engine.connect() as conn:
            def _inspect(sync_conn):
                inspector = inspect(sync_conn)
                tables = inspector.get_table_names()
                views = inspector.get_view_names()
                return sorted(list(set(tables + views)))
            return await conn.run_sync(_inspect)

    async def get_table_schema(self, table_name: str) -> List[str]:
        async with self.engine.connect() as conn:
            def _inspect_cols(sync_conn):
                inspector = inspect(sync_conn)
                columns = inspector.get_columns(table_name)
                return [c["name"] for c in columns]
            return await conn.run_sync(_inspect_cols)

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
        safe_cols = ", ".join([f"{f}" for f in fields])
        safe_table = f"{table_name}"
        track_col = tracking_field or pk_field

        bind_params = {}
        where_clause = ""

        if last_tracking_value is not None and tracking_mode in ("incremental_id", "updated_at"):
            where_clause = f"WHERE {track_col} > :val"
            order_clause = f"ORDER BY {track_col} ASC"
            bind_params["val"] = last_tracking_value
        else:
            order_clause = f"ORDER BY {pk_field} DESC"

        bind_params["limit_val"] = limit
        query_str = f"SELECT {safe_cols} FROM {safe_table} {where_clause} {order_clause} LIMIT :limit_val"

        async with self.engine.connect() as conn:
            result = await conn.execute(text(query_str), bind_params)
            rows = result.mappings().all()

            records = []
            for r in rows:
                row_dict = dict(r)
                rec_id = str(row_dict.get(pk_field, ""))
                records.append(
                    DataRecord(
                        id=rec_id,
                        data=row_dict,
                        row_hash=DataRecord.compute_hash(row_dict)
                    )
                )
            return records
