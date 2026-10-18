import aiomysql
from typing import Any, Dict, List, Optional, Tuple
from app.core.sources.base import BaseDataSource, DataRecord


class MySQLDataSource(BaseDataSource):
    """Адаптер для роботи з MySQL / MariaDB через aiomysql."""

    def __init__(self, config: Dict[str, Any]):
        self.host = config.get("host", "localhost")
        self.port = int(config.get("port", 3306))
        self.user = config.get("user", "root")
        self.password = config.get("password", "")
        self.database = config.get("database", "")

    async def _get_connection(self):
        return await aiomysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            db=self.database,
            connect_timeout=10,
            cursorclass=aiomysql.DictCursor
        )

    async def test_connection(self) -> Tuple[bool, str]:
        try:
            conn = await self._get_connection()
            try:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT VERSION();")
                    row = await cur.fetchone()
                    version = list(row.values())[0] if row else "Unknown"
                    return True, f"Успішно підключено до MySQL! ({version})"
            finally:
                conn.close()
        except Exception as e:
            return False, f"Помилка підключення до MySQL: {e}"

    async def get_tables_and_views(self) -> List[str]:
        conn = await self._get_connection()
        try:
            async with conn.cursor() as cur:
                query = """
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = %s
                    ORDER BY table_name;
                """
                await cur.execute(query, (self.database,))
                rows = await cur.fetchall()
                return [r["TABLE_NAME"] if "TABLE_NAME" in r else r["table_name"] for r in rows]
        finally:
            conn.close()

    async def get_table_schema(self, table_name: str) -> List[str]:
        conn = await self._get_connection()
        try:
            async with conn.cursor() as cur:
                query = """
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_schema = %s AND table_name = %s
                    ORDER BY ordinal_position;
                """
                await cur.execute(query, (self.database, table_name))
                rows = await cur.fetchall()
                return [r["COLUMN_NAME"] if "COLUMN_NAME" in r else r["column_name"] for r in rows]
        finally:
            conn.close()

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
            async with conn.cursor() as cur:
                safe_cols = ", ".join([f"`{f}`" for f in fields])
                safe_table = f"`{table_name}`"
                safe_pk = f"`{pk_field}`"

                params = []
                where_clause = ""
                track_col = tracking_field or pk_field
                safe_track_col = f"`{track_col}`"

                if last_tracking_value is not None and tracking_mode in ("incremental_id", "updated_at"):
                    params.append(last_tracking_value)
                    where_clause = f"WHERE {safe_track_col} > %s"
                    order_clause = f"ORDER BY {safe_track_col} ASC"
                else:
                    order_clause = f"ORDER BY {safe_pk} DESC"

                params.append(limit)
                query = f"SELECT {safe_cols} FROM {safe_table} {where_clause} {order_clause} LIMIT %s;"
                await cur.execute(query, tuple(params))
                rows = await cur.fetchall()

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
            conn.close()
