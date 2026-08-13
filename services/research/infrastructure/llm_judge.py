"""Судья через llm-service.

Своего клиента к модели у движка отбора нет и быть не должно: ключи, схема
авторизации и структурный вывод — забота `llm-service`, и дублировать их
значило бы держать две настройки одной модели.

Сервисы связаны по HTTP, а не импортом: контракт независимости это и требует.
"""

from __future__ import annotations

import httpx

from libs.shared.logging import get_logger
from services.research.application.ports import ModelJudgePort, ModelUnavailable
from services.research.domain.verdict import ModelVerdict

log = get_logger(__name__)

#: Судья думает над цитатами; минуты здесь — норма, а не признак поломки.
DEFAULT_TIMEOUT = 180.0


class HttpModelJudge(ModelJudgePort):
    def __init__(
        self,
        base_url: str,
        model_name: str = "unknown",
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model_name = model_name
        self._timeout = timeout

    @property
    def model_name(self) -> str:
        return self._model_name

    async def judge(self, system: str, user: str) -> ModelVerdict:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}/judge",
                    json={"system": system, "user": user},
                )
        except httpx.HTTPError as exc:
            # Сеть до модели — это модель. Прогон обязан остановиться, а не
            # перебирать очередь одинаковыми ошибками.
            raise ModelUnavailable(str(exc)) from exc

        if response.status_code >= 500:
            raise ModelUnavailable(f"llm-service ответил {response.status_code}")
        response.raise_for_status()

        return ModelVerdict.model_validate(response.json())
