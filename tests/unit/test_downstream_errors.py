"""Отказ соседа глазами клиента шлюза.

Шлюз ходит к llm-service и recsys-service по HTTP, и его собственный ответ
обязан сохранять смысл чужого. Раньше 4xx уходил голым `httpx.HTTPStatusError`
мимо обработчиков: запрос удалённого фильтра давал 500 «внутренняя ошибка
сервиса», хотя сосед отработал правильно и сказал «такого нет».
"""

from __future__ import annotations

import httpx
import pytest

from services.api.application.errors import (
    Conflict,
    DownstreamRejected,
    DownstreamUnavailable,
    InvalidRequest,
    NotFound,
)
from services.api.infrastructure.clients.downstream import HttpLlmService
from services.api.presentation.errors import status_for


def _service(handler) -> HttpLlmService:
    service = HttpLlmService("http://llm-service:8010")
    service._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return service


def _responds(status: int, body: dict | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body if body is not None else {})

    return handler


class TestStatusesKeepTheirMeaning:
    @pytest.mark.asyncio
    async def test_missing_entity_stays_missing(self) -> None:
        """404 соседа — это 404 клиенту, а не 502 и тем более не 500."""
        service = _service(_responds(404, {"detail": "Фильтр 2524 не найден"}))

        with pytest.raises(NotFound) as caught:
            await service.run_filter(2524, None, None, [])

        assert status_for(caught.value) == 404
        # Сосед объясняет свой отказ лучше, чем мы за него.
        assert caught.value.message == "Фильтр 2524 не найден"

    @pytest.mark.asyncio
    async def test_rejected_input_stays_rejected(self) -> None:
        service = _service(_responds(422, {"detail": "Конец периода раньше начала"}))

        with pytest.raises(InvalidRequest) as caught:
            await service.run_filter(1, None, None, [])

        assert status_for(caught.value) == 422

    @pytest.mark.asyncio
    async def test_conflict_stays_conflict(self) -> None:
        service = _service(_responds(409, {"detail": "Уже запущено"}))

        with pytest.raises(Conflict) as caught:
            await service.run_filter(1, None, None, [])

        assert status_for(caught.value) == 409

    @pytest.mark.asyncio
    async def test_other_4xx_blames_the_neighbour(self) -> None:
        """418 осмысленного перевода не имеет — это уже странность соседа."""
        service = _service(_responds(418, {"detail": "я чайник"}))

        with pytest.raises(DownstreamRejected) as caught:
            await service.run_filter(1, None, None, [])

        assert status_for(caught.value) == 502

    @pytest.mark.asyncio
    async def test_5xx_is_unavailability(self) -> None:
        """503 имеет смысл повторить, поэтому он отделён от 4xx."""
        service = _service(_responds(500))

        with pytest.raises(DownstreamUnavailable) as caught:
            await service.run_filter(1, None, None, [])

        assert status_for(caught.value) == 503

    @pytest.mark.asyncio
    async def test_unreachable_is_unavailability_too(self) -> None:
        def refuse(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("соединение отвергнуто")

        with pytest.raises(DownstreamUnavailable):
            await _service(refuse).run_filter(1, None, None, [])


class TestDetail:
    @pytest.mark.asyncio
    async def test_a_body_without_detail_still_says_something(self) -> None:
        service = _service(_responds(404, {"oops": True}))

        with pytest.raises(NotFound) as caught:
            await service.run_filter(1, None, None, [])

        assert caught.value.message

    @pytest.mark.asyncio
    async def test_a_non_json_body_does_not_break_the_translation(self) -> None:
        def html(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="<html>nginx</html>")

        with pytest.raises(NotFound):
            await _service(html).run_filter(1, None, None, [])

    @pytest.mark.asyncio
    async def test_a_validation_list_is_not_rendered_as_a_python_object(self) -> None:
        """FastAPI отдаёт `detail` списком — клиент не должен увидеть repr."""
        service = _service(
            _responds(422, {"detail": [{"loc": ["body", "since"], "msg": "invalid date"}]})
        )

        with pytest.raises(InvalidRequest) as caught:
            await service.run_filter(1, None, None, [])

        assert "invalid date" in caught.value.message
