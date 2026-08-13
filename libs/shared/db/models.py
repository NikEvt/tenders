"""Инфраструктурные таблицы, общие для всех сервисов."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from libs.shared.db.base import Base


class OutboxMessage(Base):
    """Transactional outbox: событие пишется в ту же транзакцию, что и данные.

    Без этого между `commit()` и `publish()` есть окно, в котором падение процесса
    приводит к молчаливой потере события — тендер сохранён, но документы никогда
    не скачаются.
    """

    __tablename__ = "outbox"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True)
    routing_key: Mapped[str] = mapped_column(String(128), index=True)
    payload: Mapped[dict] = mapped_column(JSONB)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ProcessedMessage(Base):
    """Дедупликация: (message_id, consumer) уже обработан.

    RabbitMQ гарантирует at-least-once, поэтому повторная доставка — не исключение,
    а штатный режим.
    """

    __tablename__ = "processed_messages"
    __table_args__ = (UniqueConstraint("message_id", "consumer", name="uq_processed_message"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(String(64), index=True)
    consumer: Mapped[str] = mapped_column(String(128))
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
