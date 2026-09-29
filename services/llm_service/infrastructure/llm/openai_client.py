"""Клиент к OpenAI-совместимому эндпоинту (qwen3.6-35B-A3B и любой другой)."""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import TypeVar

from openai import APIError, APITimeoutError, AsyncOpenAI, RateLimitError
from pydantic import BaseModel, ValidationError

from libs.shared.config import LlmSettings
from libs.shared.logging import get_logger
from services.llm_service.application.ports import LlmPort, LlmUnavailable

log = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

RETRYABLE = (RateLimitError, APITimeoutError, APIError)
MAX_ATTEMPTS = 4

# Бюджеты подобраны под reasoning-модели: даже с выключенными рассуждениями
# вердикт судьи с цитатами не укладывается в пару сотен токенов, а обрыв по
# длине даёт невалидный JSON.
DEFAULT_MAX_TOKENS = 2000
DEFAULT_STRUCTURED_MAX_TOKENS = 4000

# Модель под нагрузкой иногда оборачивает JSON в ```json ... ``` вопреки
# инструкции — выковыриваем, а не падаем.
_JSON_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class CircuitBreaker:
    """Размыкается после серии отказов и не пускает запросы к упавшей модели.

    Без него каждая заявка на фильтрацию будет минутами висеть в таймаутах,
    забивая очередь и пул соединений.
    """

    def __init__(self, failure_threshold: int = 5, recovery_seconds: float = 60.0) -> None:
        self._threshold = failure_threshold
        self._recovery = recovery_seconds
        self._failures = 0
        self._opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if time.monotonic() - self._opened_at >= self._recovery:
            # Полуоткрытое состояние: пропускаем пробный запрос.
            self._opened_at = None
            self._failures = self._threshold - 1
            return False
        return True

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self._threshold and self._opened_at is None:
            self._opened_at = time.monotonic()
            log.warning("llm.circuit_opened", failures=self._failures)


class OpenAiCompatibleLlm(LlmPort):
    """Единственная точка обращения к языковой модели.

    Ограничивает конкурентность: локальный инференс-сервер деградирует лавинообразно,
    если бросить в него сотню запросов разом.
    """

    def __init__(self, settings: LlmSettings, client: AsyncOpenAI | None = None) -> None:
        self._model = settings.model
        self._default_reasoning = settings.reasoning_effort
        self._client = client or AsyncOpenAI(
            base_url=settings.base_url,
            api_key=settings.api_key.get_secret_value(),
            timeout=settings.timeout_seconds,
            max_retries=0,  # ретраи свои, с учётом circuit breaker
            default_headers=_auth_headers(settings),
        )
        self._semaphore = asyncio.Semaphore(settings.max_concurrency)
        self._breaker = CircuitBreaker()
        # Что сервер уже отверг — запоминаем на весь срок жизни клиента.
        # Иначе каждый вызов платит одним заведомо провальным запросом:
        # на прогоне фильтра по 200 тендерам это 200 лишних обращений.
        self._structured_format_supported = True
        self._reasoning_supported = True

    @property
    def model_name(self) -> str:
        return self._model

    async def complete(
        self,
        system: str,
        user: str,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        reasoning_effort: str | None = None,
    ) -> str:
        response = await self._call(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
        )
        return response or ""

    async def structured(
        self,
        system: str,
        user: str,
        schema: type[T],
        max_tokens: int = DEFAULT_STRUCTURED_MAX_TOKENS,
        reasoning_effort: str | None = None,
    ) -> T:
        """Структурный вывод по JSON-схеме.

        Сначала пробуем `json_schema` — если сервер его поддерживает, модель физически
        не может вернуть невалидный объект. Иначе откатываемся на `json_object`
        со схемой в промпте: поддержка у провайдеров разная (Yandex Cloud, например,
        требует, чтобы все поля схемы были обязательными, и отвергает нашу).
        """
        json_schema = schema.model_json_schema()
        instructions = (
            f"{system}\n\nОтвет обязан соответствовать JSON-схеме:\n"
            f"{json.dumps(json_schema, ensure_ascii=False)}"
        )

        raw = await self._call(
            messages=[
                {"role": "system", "content": instructions},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "schema": json_schema,
                    "strict": False,
                },
            }
            if self._structured_format_supported
            else {"type": "json_object"},
            fallback_response_format={"type": "json_object"},
        )

        return self._parse(raw or "", schema)

    @staticmethod
    def _parse(raw: str, schema: type[T]) -> T:
        text = raw.strip()
        block = _JSON_BLOCK.search(text)
        if block:
            text = block.group(1).strip()
        if not text.startswith("{"):
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end > start:
                text = text[start : end + 1]

        try:
            return schema.model_validate_json(text)
        except ValidationError as exc:
            log.warning("llm.invalid_structured_output", error=str(exc), raw=raw[:500])
            raise LlmUnavailable(f"Модель вернула невалидный ответ: {exc}") from exc

    async def _call(
        self,
        messages: list[dict],
        max_tokens: int,
        reasoning_effort: str | None = None,
        response_format: dict | None = None,
        fallback_response_format: dict | None = None,
    ) -> str | None:
        if self._breaker.is_open:
            raise LlmUnavailable("Модель недоступна (circuit breaker разомкнут)")

        last_error: Exception | None = None
        current_format = response_format
        effort = reasoning_effort or self._default_reasoning

        for attempt in range(MAX_ATTEMPTS):
            async with self._semaphore:
                try:
                    kwargs: dict = {
                        "model": self._model,
                        "messages": messages,
                        "max_tokens": max_tokens,
                        "temperature": 0.1,  # решения фильтрации должны быть воспроизводимы
                    }
                    if current_format:
                        kwargs["response_format"] = current_format
                    if effort and self._reasoning_supported:
                        kwargs["reasoning_effort"] = effort

                    response = await self._client.chat.completions.create(**kwargs)
                    self._breaker.record_success()
                    return _extract_content(response)
                except APIError as exc:
                    # Сервер не знает json_schema — переходим на простой режим
                    # и больше к строгой схеме не возвращаемся.
                    if current_format and fallback_response_format and _is_format_error(exc):
                        log.info("llm.structured_format_unsupported", error=str(exc)[:200])
                        self._structured_format_supported = False
                        current_format = fallback_response_format
                        continue
                    # То же для reasoning_effort: параметр нестандартный.
                    if effort and self._reasoning_supported and _is_unknown_parameter(exc):
                        log.info("llm.reasoning_effort_unsupported", error=str(exc)[:200])
                        self._reasoning_supported = False
                        continue
                    last_error = exc
                except RETRYABLE as exc:
                    last_error = exc

            self._breaker.record_failure()
            if attempt < MAX_ATTEMPTS - 1:
                delay = min(2**attempt, 30)
                log.warning("llm.retry", attempt=attempt + 1, delay=delay, error=str(last_error))
                await asyncio.sleep(delay)

        raise LlmUnavailable(f"Модель не ответила за {MAX_ATTEMPTS} попыток: {last_error}")


def _auth_headers(settings: LlmSettings) -> dict[str, str] | None:
    """Заголовок авторизации для провайдеров с нестандартной схемой.

    По умолчанию SDK шлёт `Bearer`. Yandex Cloud принимает и его, но с
    API-ключом штатной схемой считается `Api-Key`.
    """
    if settings.auth_scheme.lower() == "bearer":
        return None
    key = settings.api_key.get_secret_value()
    return {"Authorization": f"{settings.auth_scheme} {key}"}


def _extract_content(response: object) -> str | None:
    """Достаёт текст ответа с учётом reasoning-моделей.

    У Qwen3.6 и подобных при исчерпании бюджета токенов весь ответ уходит в
    `reasoning_content`, а `content` приходит пустым. Молча вернуть пустую
    строку нельзя: вызывающий код примет её за валидный ответ модели.
    """
    choice = response.choices[0]  # type: ignore[attr-defined]
    message = choice.message
    content = getattr(message, "content", None)
    finish_reason = getattr(choice, "finish_reason", None)

    if content:
        # Оборванный ответ — не «невалидный»: структурный вывод держит форму
        # JSON, но не длину строки внутри него, и модель умеет зациклиться
        # прямо в значении. Наблюдалось на шаблоне: `газ(?!овый|…|опроводник`
        # повторялся, пока не кончился бюджет, и JSON оборвался на середине
        # строки. Сказать «модель ответила ерундой» здесь значило бы соврать
        # про причину и увести чинящего не туда.
        if finish_reason == "length":
            log.warning(
                "llm.response_truncated",
                content_chars=len(content),
                finish_reason=finish_reason,
            )
            raise LlmUnavailable(
                "Ответ модели оборван: кончился бюджет токенов. "
                "Увеличьте max_tokens или упростите запрос."
            )
        return content

    reasoning = getattr(message, "reasoning_content", None)
    if reasoning:
        log.warning(
            "llm.content_empty_reasoning_only",
            reasoning_chars=len(reasoning),
            finish_reason=finish_reason,
        )
        raise LlmUnavailable(
            "Модель израсходовала бюджет токенов на рассуждения и не выдала ответ. "
            "Увеличьте max_tokens или снизьте reasoning_effort."
        )
    return content


def _is_format_error(exc: APIError) -> bool:
    """Признаки того, что сервер не принял `response_format`.

    Формулировки у провайдеров разные: Yandex Cloud отвечает
    «Invalid JSON Schema: all fields must be required» — без подчёркивания,
    поэтому проверять одну подстроку `json_schema` недостаточно.
    """
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "response_format",
            "json_schema",
            "json schema",
            "must be required",
            "structured output",
            # Сервер компилирует схему в грамматику и спотыкается о regex,
            # который сгенерировал pydantic (например, look-ahead у Decimal).
            "json grammar",
            "grammar",
        )
    )


def _is_unknown_parameter(exc: APIError) -> bool:
    message = str(exc).lower()
    return "reasoning_effort" in message or (
        "unknown" in message and "parameter" in message
    )
