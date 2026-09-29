"""HTTP-клиенты к внутренним сервисам."""

from __future__ import annotations

from datetime import date

import httpx

from libs.shared.logging import get_logger
from services.api.application.errors import (
    ApplicationError,
    Conflict,
    DownstreamRejected,
    DownstreamUnavailable,
    InvalidRequest,
    NotFound,
)
from services.api.application.ports import LlmServicePort, RecsysServicePort

log = get_logger(__name__)

# Компиляция фильтра и запуск задания идут через модель — секундами тут не обойтись.
LLM_TIMEOUT = 240.0
RECSYS_TIMEOUT = 30.0


def _detail(response: httpx.Response) -> str:
    """Текст отказа соседа. Своё сообщение он объясняет лучше, чем мы за него."""
    try:
        body = response.json()
    except ValueError:
        return response.text.strip()[:500]
    if isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, str):
            return detail
        if detail is not None:
            return str(detail)[:500]
    return response.text.strip()[:500]


def _rejected(service: str, status: int, detail: str) -> ApplicationError:
    """Отказ соседа → ошибка прикладного слоя.

    Статус переводится в словарь приложения, а не пробрасывается числом:
    прикладной слой про HTTP не знает, а клиенту важно различать «сущности
    нет» и «сосед сломался». 404 от соседа означает ровно то же, что 404 от
    нас, — сосед при этом отработал правильно, и 502 был бы напраслиной.
    """
    if status == 404:
        return NotFound(detail or f"{service}: не найдено")
    if status in (400, 422):
        return InvalidRequest(detail or f"{service}: запрос отвергнут")
    if status == 409:
        return Conflict(detail or f"{service}: конфликт состояния")
    return DownstreamRejected(detail or f"{service} вернул {status}", status=status)


class _BaseClient:
    def __init__(self, base_url: str, timeout: float, name: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._name = name
        self._client = httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs) -> dict | list:
        try:
            response = await self._client.request(method, f"{self._base_url}{path}", **kwargs)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status < 500:
                # 4xx — это ответ соседа, а не его недоступность. Раньше здесь
                # стоял голый `raise`, и `httpx.HTTPStatusError` уходил мимо
                # обработчиков: запрос несуществующего фильтра превращался во
                # «внутреннюю ошибку сервиса», где клиент не мог отличить
                # «такого нет» от «шлюз сломался».
                raise _rejected(self._name, status, _detail(exc.response)) from exc
            log.warning("downstream.error", service=self._name, status=status)
            raise DownstreamUnavailable(f"{self._name} вернул {status}") from exc
        except httpx.HTTPError as exc:
            log.warning("downstream.unreachable", service=self._name, error=str(exc))
            raise DownstreamUnavailable(f"{self._name} недоступен: {exc}") from exc
        # 204 и пустое тело — законный ответ на удаление; .json() на нём падает.
        if response.status_code == 204 or not response.content:
            return {}
        return response.json()


class HttpLlmService(_BaseClient, LlmServicePort):
    def __init__(self, base_url: str) -> None:
        super().__init__(base_url, LLM_TIMEOUT, "llm-service")

    async def compile_filter(self, query: str) -> dict:
        return await self._request("POST", "/filters/compile", json={"query": query})  # type: ignore[return-value]

    async def save_filter(self, name: str, query: str, spec: dict | None = None) -> dict:
        body: dict = {"name": name, "query": query}
        if spec is not None:
            body["spec"] = spec
        return await self._request("POST", "/filters", json=body)  # type: ignore[return-value]

    async def patch_filter(self, filter_id: int, patch: dict) -> dict:
        return await self._request("PATCH", f"/filters/{filter_id}", json=patch)  # type: ignore[return-value]

    async def delete_filter(self, filter_id: int) -> None:
        await self._request("DELETE", f"/filters/{filter_id}")

    async def duplicate_filter(self, filter_id: int) -> dict:
        return await self._request("POST", f"/filters/{filter_id}/duplicate")  # type: ignore[return-value]

    async def test_filter(self, filter_id: int, days: int) -> dict:
        return await self._request(  # type: ignore[return-value]
            "POST", f"/filters/{filter_id}/test", json={"days": days}
        )

    async def run_filter(
        self,
        filter_id: int,
        since: date | None,
        until: date | None,
        regions: list[str],
    ) -> dict:
        return await self._request(  # type: ignore[return-value]
            "POST",
            f"/filters/{filter_id}/run",
            json={
                "since": since.isoformat() if since else None,
                "until": until.isoformat() if until else None,
                "regions": regions,
            },
        )

    async def request_digest(self, digest_date: date, force: bool) -> dict:
        return await self._request(  # type: ignore[return-value]
            "POST", f"/digest/{digest_date.isoformat()}", params={"force": force}
        )


class HttpRecsysService(_BaseClient, RecsysServicePort):
    def __init__(self, base_url: str) -> None:
        super().__init__(base_url, RECSYS_TIMEOUT, "recsys-service")

    async def recommendations(self, limit: int) -> list[dict]:
        return await self._request("GET", "/recommendations", params={"limit": limit})  # type: ignore[return-value]

    async def feedback(self, tender_id: int, signal: str, reason: str | None) -> dict:
        return await self._request(  # type: ignore[return-value]
            "POST",
            "/feedback",
            json={"tender_id": tender_id, "signal": signal, "reason": reason},
        )

    async def view(self, tender_id: int, dwell_ms: int | None) -> dict:
        return await self._request(  # type: ignore[return-value]
            "POST", "/views", json={"tender_id": tender_id, "dwell_ms": dwell_ms}
        )

    async def win(self, tender_id: int, payload: dict) -> dict:
        return await self._request("POST", "/wins", json={"tender_id": tender_id, **payload})  # type: ignore[return-value]

    async def profile(self) -> dict:
        return await self._request("GET", "/profile")  # type: ignore[return-value]

    async def profile_weights(self) -> list[dict]:
        return await self._request("GET", "/profile/weights")  # type: ignore[return-value]

    async def set_profile_weight(
        self, facet: str, key: str, weight: float | None
    ) -> list[dict]:
        return await self._request(  # type: ignore[return-value]
            "PATCH", "/profile/weights", json={"facet": facet, "key": key, "weight": weight}
        )

    async def ranker(self) -> dict:
        return await self._request("GET", "/profile/ranker")  # type: ignore[return-value]

    async def delete_rating(self, signal_id: int) -> None:
        await self._request("DELETE", f"/profile/history/{signal_id}")
