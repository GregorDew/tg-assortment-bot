from typing import List, Union
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator


class Settings(BaseSettings):
    """Налаштування застосунку, які зчитуються з .env або оточення."""

    BOT_TOKEN: str = "123456789:ABCdefGHIjklMNOpqrSTUvwxYZ"
    ADMIN_IDS: Union[List[int], str] = []
    TARGET_CHAT_ID: Union[int, str] = "-100123456789"
    DATABASE_URL: str = "sqlite+aiosqlite:///bot.db"
    DB_CHECK_INTERVAL_SECONDS: int = 60
    MANAGER_USERNAME: str = ""
    ENCRYPTION_KEY: str = ""

    @field_validator("MANAGER_USERNAME", mode="before")
    @classmethod
    def clean_manager_username(cls, v: Union[str, None]) -> str:
        if isinstance(v, str):
            return v.strip().lstrip("@")
        return ""

    @field_validator("ADMIN_IDS", mode="before")
    @classmethod
    def parse_admin_ids(cls, v: Union[str, List[int], int]) -> List[int]:
        if isinstance(v, list):
            return [int(x) for x in v]
        if isinstance(v, int):
            return [v]
        if isinstance(v, str):
            if not v.strip():
                return []
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return []

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
