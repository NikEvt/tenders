"""HTTP-клиенты к внутренним сервисам."""

from __future__ import annotations

from datetime import date

import httpx

from libs.shared.logging import get_logger
from services.api.application.ports import (
    DownstreamUnavailable,
    LlmServicePort,
    RecsysServicePort,
)

log = get_logger(__name__)

# Компиляция фильтра и запуск задания идут через модель — секундами тут не обойтись.
LLM_TIMEOUT = 240.0
RECSYS_TIMEOUT = 30.0


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
            # 4xx — это ответ сервиса, а не его недоступность: пробрасываем как есть.
            if exc.response.status_code < 500:
                raise
            log.warning(
                "downstream.error", service=self._name, status=exc.response.status_code
            )
            raise DownstreamUnavailable(f"{self._name} вернул {exc.response.status_code}") from exc
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
        self, filter_id: int, since: date | None, tender_ids: list[int]
    ) -> dict:
        return await self._request(  # type: ignore[return-value]
            "POST",
            f"/filters/{filter_id}/run",
            json={
                "since": since.isoformat() if since else None,
                "tender_ids": tender_ids,
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
