"""Опрос состояния соседних сервисов.

Все шесть опрашиваются параллельно и с коротким таймаутом: страница мониторинга
должна открываться за секунду, а не за сумму ожиданий. Сервис, который не
ответил, помечается `down` — это факт, а не ошибка страницы.
"""

from __future__ import annotations

import asyncio
import time

import httpx

from libs.shared.logging import get_logger
from services.api.application.ports.monitoring import ServiceProbePort
from services.api.domain.monitoring import ServiceHealth

log = get_logger(__name__)

# Живой сервис отвечает за миллисекунды. Полторы секунды — это уже «плохо»,
# и ждать дольше незачем: страница обновляется, а не ставит диагноз.
PROBE_TIMEOUT = 1.5
# Дольше этого — сервис жив, но нездоров.
DEGRADED_MS = 500.0


class HttpServiceProbe(ServiceProbePort):
    def __init__(self, endpoints: dict[str, str]) -> None:
        # {имя сервиса: базовый URL}. Сервисы без HTTP (crawler, docs-worker)
        # сюда не попадают — их состояние видно по данным, а не по порту.
        self._endpoints = endpoints
        self._client = httpx.AsyncClient(timeout=PROBE_TIMEOUT)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def probe_all(self) -> list[ServiceHealth]:
        results = await asyncio.gather(
            *(self._probe(name, url) for name, url in self._endpoints.items())
        )
        return list(results)

    async def _probe(self, name: str, base_url: str) -> ServiceHealth:
        started = time.perf_counter()
        try:
            response = await self._client.get(f"{base_url.rstrip('/')}/health/ready")
            elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
            if response.status_code >= 500:
                return ServiceHealth(name=name, status="down", p95_ms=elapsed_ms)

            body = response.json()
            facts = {k: v for k, v in body.items() if k != "status"}
            status = "degraded" if elapsed_ms > DEGRADED_MS else "ok"
            return ServiceHealth(
                name=name,
                status=status,
                port=_port_of(base_url),
                p95_ms=elapsed_ms,
                facts=facts,
            )
        except Exception as exc:
            log.info("monitoring.probe_failed", service=name, error=str(exc))
            return ServiceHealth(name=name, status="down", port=_port_of(base_url))


def _port_of(base_url: str) -> int | None:
    tail = base_url.rsplit(":", 1)[-1].split("/")[0]
    return int(tail) if tail.isdigit() else None
