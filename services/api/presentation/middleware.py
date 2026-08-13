"""Сквозной идентификатор запроса.

Клиент показывает его в кнопке «Скопировать детали», а в логах он лежит как
`correlation_id` — по одной строке из интерфейса находится весь путь запроса
через сервисы.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

import structlog

from libs.shared.logging import get_logger, set_correlation_id

log = get_logger(__name__)

REQUEST_ID_HEADER = "x-request-id"

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]


class RequestContextMiddleware:
    """Чистый ASGI, а не BaseHTTPMiddleware.

    BaseHTTPMiddleware гоняет ответ через анонимную задачу, и contextvar,
    выставленный в нём, до обработчика исключений не доезжает.
    """

    def __init__(self, app: Callable[[Scope, Receive, Send], Awaitable[None]]) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        request_id = _incoming_request_id(scope) or str(uuid.uuid4())
        set_correlation_id(request_id)
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=scope.get("method"),
            path=scope.get("path"),
        )
        started = time.perf_counter()
        status_holder: dict[str, int] = {}

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                headers = list(message.get("headers", []))
                headers.append((REQUEST_ID_HEADER.encode(), request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self._app(scope, receive, send_with_request_id)
        finally:
            log.info(
                "api.request",
                status=status_holder.get("status"),
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )
            structlog.contextvars.unbind_contextvars("request_id", "method", "path")


def _incoming_request_id(scope: Scope) -> str | None:
    """Свой идентификатор клиента уважаем: так след не рвётся на границе."""
    for name, value in scope.get("headers", []):
        if name.decode().lower() == REQUEST_ID_HEADER:
            candidate = value.decode().strip()
            # Заголовок приходит снаружи — в лог и в ответ пускаем только
            # разумную длину, чтобы не таскать за собой чужой мусор.
            if candidate and len(candidate) <= 128:
                return candidate
    return None
