from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, Boolean, DateTime, Integer, ForeignKey
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
    """Наявна таблиця товарів / оновлень асортименту (збережено для зворотної сумісності)."""
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
    photo_file_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    photo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    photo_blob: Mapped[Optional[bytes]] = mapped_column(nullable=True)

    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    source: Mapped[str] = mapped_column(String(50), default="db", nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    moderated_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    def __repr__(self) -> str:
        return f"<Product id={self.id} title='{self.title}' status='{self.status}'>"


# ===========================================================================
# НОВІ УНІВЕРСАЛЬНІ МОДЕЛІ СИСТЕМИ
# ===========================================================================

class DataSourceModel(Base):
    """Підключення до зовнішніх джерел даних (PostgreSQL, MySQL, SQL, HTTP API)."""
    __tablename__ = "data_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # postgres, mysql, sqlite, http_api
    config_json: Mapped[str] = mapped_column(Text, nullable=False)  # Зашифровані параметри підключення

    selected_table: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    selected_fields: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON-масив назв полів
    pk_field: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # Primary key

    # Спосіб виявлення змін: incremental_id, updated_at, row_hash
    change_tracking_mode: Mapped[str] = mapped_column(String(50), default="incremental_id", nullable=False)
    tracking_field: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # поле дати або id

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<DataSource id={self.id} name='{self.name}' type='{self.type}'>"


class PublishChannelModel(Base):
    """Канали публікації (Telegram, Discord, HTTP API, Email)."""
    __tablename__ = "publish_channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # telegram, discord, http_api, email
    config_json: Mapped[str] = mapped_column(Text, nullable=False)  # Зашифровані налаштування каналу
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<PublishChannel id={self.id} name='{self.name}' type='{self.type}'>"


class TemplateModel(Base):
    """Універсальні шаблони повідомлень."""
    __tablename__ = "templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    platform: Mapped[str] = mapped_column(String(50), default="universal", nullable=False)
    title_template: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # Email Subject, Discord Title
    body_template: Mapped[str] = mapped_column(Text, nullable=False)  # Основний текст шаблону
    extra_config_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON додаткових параметрів
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<Template id={self.id} name='{self.name}' platform='{self.platform}'>"


class PublishRuleModel(Base):
    """Правила обробки та маршрутизації публікацій."""
    __tablename__ = "publish_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    data_source_id: Mapped[int] = mapped_column(Integer, ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False)
    template_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("templates.id", ondelete="SET NULL"), nullable=True)
    
    # Список ID каналів призначення: JSON-масив цілих чисел, напр. [1, 2]
    channel_ids_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    
    # Події для запуску: JSON-масив ["new", "updated", "deleted"]
    trigger_events: Mapped[str] = mapped_column(String(100), default='["new"]', nullable=False)
    
    # Фільтри записів: JSON-масив умов
    filters_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Режим: 'approval' (потрібне погодження адмінів), 'auto' (миттєвий автопост), 'disabled' (вимкнено)
    mode: Mapped[str] = mapped_column(String(50), default="approval", nullable=False)
    
    # Поведінка при зміні: 'new_post', 'update_post', 'approval', 'ignore'
    on_update_action: Mapped[str] = mapped_column(String(50), default="approval", nullable=False)
    
    # Поведінка при видаленні: 'ignore', 'notify_delete', 'delete_post'
    on_delete_action: Mapped[str] = mapped_column(String(50), default="ignore", nullable=False)

    check_interval_seconds: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<PublishRule id={self.id} name='{self.name}' mode='{self.mode}'>"


class PendingPublicationModel(Base):
    """Публікації, що очікують погодження адміністратором."""
    __tablename__ = "pending_publications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_id: Mapped[int] = mapped_column(Integer, ForeignKey("publish_rules.id", ondelete="CASCADE"), nullable=False)
    source_id: Mapped[int] = mapped_column(Integer, ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False)
    record_id: Mapped[str] = mapped_column(String(100), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), default="new", nullable=False)

    raw_data_json: Mapped[str] = mapped_column(Text, nullable=False)
    prepared_data_json: Mapped[str] = mapped_column(Text, nullable=False)

    # Статус: 'pending', 'published', 'rejected'
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    moderated_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    moderated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class DeliveryLogModel(Base):
    """Журнал публікацій та помилок доставки."""
    __tablename__ = "delivery_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    channel_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    record_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    event_type: Mapped[str] = mapped_column(String(50), default="new", nullable=False)
    
    # Статус: 'success', 'failed', 'pending_approval', 'skipped'
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    external_message_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ProcessedRecordModel(Base):
    """Захист від дублікатів та збереження стану оброблених записів."""
    __tablename__ = "processed_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_id: Mapped[int] = mapped_column(Integer, ForeignKey("publish_rules.id", ondelete="CASCADE"), nullable=False)
    record_id: Mapped[str] = mapped_column(String(100), nullable=False)
    row_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    external_ids_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)  # {channel_id: message_id}
