from typing import Any, Dict
from app.core.sources.base import BaseDataSource
from app.core.sources.postgres import PostgresDataSource
from app.core.sources.mysql import MySQLDataSource
from app.core.sources.sqlalchemy_src import GenericSQLDataSource
from app.core.sources.http_api import HttpApiDataSource


def create_data_source(ds_type: str, config: Dict[str, Any]) -> BaseDataSource:
    """Фабрика для створення екземпляра джерела даних за його типом."""
    t = ds_type.lower()
    if t in ("postgres", "postgresql"):
        return PostgresDataSource(config)
    elif t in ("mysql", "mariadb"):
        return MySQLDataSource(config)
    elif t in ("sqlite", "sql", "sqlalchemy"):
        return GenericSQLDataSource(config)
    elif t in ("http", "http_api", "api"):
        return HttpApiDataSource(config)
    else:
        raise ValueError(f"Невідомий тип джерела даних: '{ds_type}'")
