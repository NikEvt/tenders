"""Структурное логирование с correlation-id, общее для всех сервисов."""

import contextvars
import logging
import sys
import uuid
from typing import Any

import structlog

from libs.shared.config import log_settings

_correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)


def set_correlation_id(value: str | None = None) -> str:
    cid = value or str(uuid.uuid4())
    _correlation_id.set(cid)
    return cid


def get_correlation_id() -> str | None:
    return _correlation_id.get()


def _add_correlation_id(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    cid = _correlation_id.get()
    if cid:
        event_dict["correlation_id"] = cid
    return event_dict


def configure_logging(service: str) -> None:
    settings = log_settings()
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.level.upper(), logging.INFO),
    )

    renderer: Any = (
        structlog.processors.JSONRenderer(ensure_ascii=False)
        if settings.json_output
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _add_correlation_id,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    structlog.contextvars.bind_contextvars(service=service)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
