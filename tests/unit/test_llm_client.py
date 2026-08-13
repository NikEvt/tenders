"""Клиент к OpenAI-совместимому эндпоинту: reasoning-модели и особенности провайдеров."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from openai import APIError
from pydantic import BaseModel, SecretStr

from libs.shared.config import LlmSettings
from services.llm_service.application.ports import LlmUnavailable
from services.llm_service.infrastructure.llm.openai_client import (
    OpenAiCompatibleLlm,
    _is_format_error,
)


class Answer(BaseModel):
    keywords: list[str] = []
    price_max: float | None = None


def settings(**overrides) -> LlmSettings:
    values = {
        "LLM_BASE_URL": "https://example.invalid/v1",
        "LLM_API_KEY": SecretStr("k"),
        "LLM_MODEL": "gpt://folder/qwen/latest",
        "LLM_MAX_CONCURRENCY": 2,
        "LLM_TIMEOUT_SECONDS": 5,
        "LLM_REASONING_EFFORT": "none",
        "LLM_JUDGE_REASONING_EFFORT": "low",
        "LLM_AUTH_SCHEME": "Bearer",
    }
    values.update(overrides)
    return LlmSettings.model_validate(values)


def message(content=None, reasoning=None, finish_reason="stop"):
    msg = SimpleNamespace(content=content, reasoning_content=reasoning)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason=finish_reason)])


def api_error(text: str) -> APIError:
    return APIError(text, httpx.Request("POST", "https://example.invalid"), body=None)


class FakeOpenAI:
    """Подменяет AsyncOpenAI: отдаёт заготовленные ответы и пишет полученные kwargs."""

    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def build(responses: list, **overrides) -> tuple[OpenAiCompatibleLlm, FakeOpenAI]:
    fake = FakeOpenAI(responses)
    return OpenAiCompatibleLlm(settings(**overrides), client=fake), fake  # type: ignore[arg-type]


class TestReasoningModels:
    @pytest.mark.asyncio
    async def test_empty_content_with_reasoning_is_not_passed_off_as_answer(self) -> None:
        """Регрессия: Qwen3.6 отдаёт content=None, спалив бюджет на рассуждения.

        Вернуть пустую строку нельзя — вызывающий код примет её за ответ модели.
        """
        empty = message(content=None, reasoning="Долгие размышления…", finish_reason="length")
        llm, _ = build([empty] * 4)

        with pytest.raises(LlmUnavailable, match="рассужден"):
            await llm.complete("s", "u")

    @pytest.mark.asyncio
    async def test_content_wins_when_both_present(self) -> None:
        llm, _ = build([message(content="Да", reasoning="ход мысли")])
        assert await llm.complete("s", "u") == "Да"

    @pytest.mark.asyncio
    async def test_reasoning_effort_is_sent(self) -> None:
        llm, fake = build([message(content="ок")])
        await llm.complete("s", "u")
        assert fake.calls[0]["reasoning_effort"] == "none"

    @pytest.mark.asyncio
    async def test_call_site_can_override_effort(self) -> None:
        """Судье нужен бюджет на рассуждение, остальным — нет."""
        llm, fake = build([message(content="ок")])
        await llm.complete("s", "u", reasoning_effort="low")
        assert fake.calls[0]["reasoning_effort"] == "low"

    @pytest.mark.asyncio
    async def test_unsupported_reasoning_effort_is_dropped_and_remembered(self) -> None:
        llm, fake = build(
            [
                api_error("Unknown parameter: reasoning_effort"),
                message(content="ок"),
                message(content="ещё раз"),
            ]
        )

        assert await llm.complete("s", "u") == "ок"
        assert "reasoning_effort" not in fake.calls[1]

        # Повторный вызов не должен снова напарываться на тот же отказ.
        assert await llm.complete("s", "u") == "ещё раз"
        assert "reasoning_effort" not in fake.calls[2]


class TestStructuredOutput:
    YANDEX_ERROR = "Invalid JSON Schema: all fields must be required"

    def test_yandex_wording_is_recognised(self) -> None:
        """Яндекс пишет «JSON Schema» с пробелом — одной подстроки мало."""
        assert _is_format_error(api_error(self.YANDEX_ERROR))

    @pytest.mark.parametrize(
        "text",
        [
            "response_format is not supported",
            "json_schema mode unavailable",
            "Structured output not supported for this model",
        ],
    )
    def test_other_providers_wording(self, text: str) -> None:
        assert _is_format_error(api_error(text))

    def test_unrelated_error_is_not_a_format_error(self) -> None:
        assert not _is_format_error(api_error("Rate limit exceeded"))

    @pytest.mark.asyncio
    async def test_falls_back_to_json_object(self) -> None:
        llm, fake = build(
            [api_error(self.YANDEX_ERROR), message(content='{"keywords": ["газ"]}')]
        )

        result = await llm.structured("s", "u", Answer)

        assert result.keywords == ["газ"]
        assert fake.calls[0]["response_format"]["type"] == "json_schema"
        assert fake.calls[1]["response_format"] == {"type": "json_object"}

    @pytest.mark.asyncio
    async def test_fallback_is_sticky_across_calls(self) -> None:
        """Иначе каждый из 200 вердиктов прогона платит провальным запросом."""
        llm, fake = build(
            [
                api_error(self.YANDEX_ERROR),
                message(content='{"keywords": ["газ"]}'),
                message(content='{"keywords": ["лампы"]}'),
                message(content='{"keywords": ["вода"]}'),
            ]
        )

        await llm.structured("s", "u", Answer)
        await llm.structured("s", "u", Answer)
        await llm.structured("s", "u", Answer)

        assert len(fake.calls) == 4, "после отказа не должно быть новых попыток json_schema"
        assert all(c["response_format"] == {"type": "json_object"} for c in fake.calls[1:])

    @pytest.mark.asyncio
    async def test_schema_goes_into_prompt_for_json_object_mode(self) -> None:
        llm, fake = build([api_error(self.YANDEX_ERROR), message(content='{"keywords": []}')])
        await llm.structured("Разбери запрос", "поставка газа", Answer)

        system = fake.calls[1]["messages"][0]["content"]
        assert "JSON-схеме" in system
        assert "keywords" in system, "в json_object режиме схема живёт только в промпте"

    @pytest.mark.asyncio
    async def test_json_wrapped_in_code_fence_is_parsed(self) -> None:
        llm, _ = build([message(content='```json\n{"keywords": ["газ"]}\n```')])
        assert (await llm.structured("s", "u", Answer)).keywords == ["газ"]

    @pytest.mark.asyncio
    async def test_invalid_json_raises_llm_unavailable(self) -> None:
        llm, _ = build([message(content="это не json")])
        with pytest.raises(LlmUnavailable):
            await llm.structured("s", "u", Answer)


class TestAuth:
    def test_bearer_adds_no_custom_header(self) -> None:
        from services.llm_service.infrastructure.llm.openai_client import _auth_headers

        assert _auth_headers(settings(LLM_AUTH_SCHEME="Bearer")) is None

    def test_api_key_scheme_sets_header(self) -> None:
        from services.llm_service.infrastructure.llm.openai_client import _auth_headers

        headers = _auth_headers(settings(LLM_AUTH_SCHEME="Api-Key"))
        assert headers == {"Authorization": "Api-Key k"}
