from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, Boolean, DateTime, Integer
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class BotSettings(Base):
    """Таблиця системних налаштувань бота (запис-сінглтон з id=1)."""
    __tablename__ = "bot_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    auto_post_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<BotSettings auto_post_enabled={self.auto_post_enabled}>"


class Product(Base):
    """Таблиця товарів / оновлень асортименту з підтримкою фото."""
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
    # Медіа: підтримуємо як Telegram file_id, так і зовнішнє посилання / шлях
    photo_file_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    photo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Статуси: 'pending' (очікує), 'published' (опубліковано), 'rejected' (відхилено)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    
    # Джерело: 'db' (додано в БД/імпортовано), 'manual' (створено адміном через FSM)
    source: Mapped[str] = mapped_column(String(50), default="db", nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    moderated_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    def __repr__(self) -> str:
        return f"<Product id={self.id} title='{self.title}' status='{self.status}'>"
