import asyncpg
from typing import Any, Dict, List, Optional, Tuple
from app.core.sources.base import BaseDataSource, DataRecord


class PostgresDataSource(BaseDataSource):
    """Адаптер для роботи з PostgreSQL через asyncpg."""

    def __init__(self, config: Dict[str, Any]):
        self.host = config.get("host", "localhost")
        self.port = int(config.get("port", 5432))
        self.user = config.get("user", "postgres")
        self.password = config.get("password", "")
        self.database = config.get("database", "postgres")
        self.ssl = config.get("ssl", False)

    async def _get_connection(self):
        return await asyncpg.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database,
            ssl=self.ssl,
            timeout=10
        )

    async def test_connection(self) -> Tuple[bool, str]:
        try:
            conn = await self._get_connection()
            try:
                version = await conn.fetchval("SELECT version();")
                return True, f"Успішно підключено до PostgreSQL! ({version.split(',')[0]})"
            finally:
                await conn.close()
        except Exception as e:
            return False, f"Помилка підключення до PostgreSQL: {e}"

    async def get_tables_and_views(self) -> List[str]:
        conn = await self._get_connection()
        try:
            query = """
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                  AND table_type IN ('BASE TABLE', 'VIEW')
                ORDER BY table_name;
            """
            rows = await conn.fetch(query)
            return [r["table_name"] for r in rows]
        finally:
            await conn.close()

    async def get_table_schema(self, table_name: str) -> List[str]:
        conn = await self._get_connection()
        try:
            query = """
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = $1
                  AND table_schema NOT IN ('pg_catalog', 'information_schema')
                ORDER BY ordinal_position;
            """
            rows = await conn.fetch(query, table_name)
            return [r["column_name"] for r in rows]
        finally:
            await conn.close()

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
        conn = await self._get_connection()
        try:
            # Валідація назв колонок (захист від SQL Injection в ідентифікаторах)
            safe_cols = ", ".join([f'"{f}"' for f in fields])
            safe_table = f'"{table_name}"'
            safe_pk = f'"{pk_field}"'

            params = []
            where_clause = ""

            track_col = tracking_field or pk_field
            safe_track_col = f'"{track_col}"'

            if last_tracking_value is not None and tracking_mode in ("incremental_id", "updated_at"):
                params.append(last_tracking_value)
                where_clause = f"WHERE {safe_track_col} > $1"
                order_clause = f"ORDER BY {safe_track_col} ASC"
                params.append(limit)
                limit_clause = f"LIMIT $2"
            else:
                order_clause = f"ORDER BY {safe_pk} DESC"
                params.append(limit)
                limit_clause = f"LIMIT $1"

            query = f"SELECT {safe_cols} FROM {safe_table} {where_clause} {order_clause} {limit_clause};"
            rows = await conn.fetch(query, *params)

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
        finally:
            await conn.close()
