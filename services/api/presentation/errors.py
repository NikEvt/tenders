"""Перевод прикладных ошибок в HTTP.

Единственное место, где выбирается статус-код. Хендлеры не ловят исключения
вообще: use case бросает `NotFound`, порт бросает `DownstreamUnavailable`,
а во что это превратится наружу — решается здесь.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from libs.shared.logging import get_correlation_id, get_logger
from services.api.application.errors import (
    ApplicationError,
    Conflict,
    DownstreamRejected,
    DownstreamUnavailable,
    InvalidRequest,
    NotFound,
    ServiceNotReady,
)

log = get_logger(__name__)

# Порядок не важен: поиск идёт по точному типу, затем по MRO.
ERROR_STATUS: dict[type[ApplicationError], int] = {
    NotFound: 404,
    Conflict: 409,
    InvalidRequest: 422,
    DownstreamRejected: 502,
    DownstreamUnavailable: 503,
    ServiceNotReady: 503,
}

DEFAULT_STATUS = 500


def status_for(error: ApplicationError) -> int:
    for klass in type(error).__mro__:
        if klass in ERROR_STATUS:
            return ERROR_STATUS[klass]
    return DEFAULT_STATUS


def _body(detail: str, code: str, details: dict[str, object] | None = None) -> dict[str, object]:
    """Конверт ошибки.

    `detail` остаётся строкой на первом месте: его читает клиент
    (`web/src/shared/api/client.ts`), и менять форму ради красоты нельзя.
    `code` добавлен сверху — по нему клиент различает случаи, не разбирая текст.
    """
    body: dict[str, object] = {"detail": detail, "code": code}
    request_id = get_correlation_id()
    if request_id:
        body["request_id"] = request_id
    if details:
        body["details"] = details
    return body


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApplicationError)
    async def _application_error(_: Request, exc: ApplicationError) -> JSONResponse:
        status = status_for(exc)
        # 5xx — это про нас, его нужно видеть в логах; 4xx — про запрос клиента.
        if status >= 500:
            log.warning("api.error", code=exc.code, status=status, error=exc.message)
        return JSONResponse(status_code=status, content=_body(exc.message, exc.code, exc.details))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.error("api.unhandled", error=str(exc), exc_info=exc)
        return JSONResponse(
            status_code=DEFAULT_STATUS,
            content=_body("Внутренняя ошибка сервиса", "internal_error"),
        )
