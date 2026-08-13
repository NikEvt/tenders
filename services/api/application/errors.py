"""Ошибки прикладного слоя — единственный источник кодов для шлюза.

Прикладной слой не знает про HTTP: он говорит «не найдено», «сосед недоступен»,
а перевод в статус-код делает presentation. Благодаря этому use case можно
вызвать из теста или из другого транспорта, не втаскивая FastAPI.
"""

from __future__ import annotations

from typing import ClassVar


class ApplicationError(Exception):
    """Ожидаемый отказ. Всё, что не наследует его, — это дефект, а не сценарий."""

    code: ClassVar[str] = "internal_error"

    def __init__(self, message: str, **details: object) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class NotFound(ApplicationError):
    """Запрошенной сущности нет. Порт вернул None — решение принимает use case."""

    code: ClassVar[str] = "not_found"


class Conflict(ApplicationError):
    """Состояние не позволяет выполнить операцию (повторное создание, гонка)."""

    code: ClassVar[str] = "conflict"


class InvalidRequest(ApplicationError):
    """Запрос синтаксически верен, но бессмыслен: например, битый курсор."""

    code: ClassVar[str] = "invalid_request"


class ServiceNotReady(ApplicationError):
    """Контейнер ещё не собран — lifespan не отработал."""

    code: ClassVar[str] = "not_ready"


class DownstreamUnavailable(ApplicationError):
    """Сервис за шлюзом недоступен — отвечаем 503, а не 500.

    Разница с `DownstreamRejected` существенна для клиента: 503 имеет смысл
    повторить, 502 — нет.
    """

    code: ClassVar[str] = "downstream_unavailable"


class DownstreamRejected(ApplicationError):
    """Сосед ответил осмысленной ошибкой — повторять запрос бесполезно."""

    code: ClassVar[str] = "downstream_rejected"
