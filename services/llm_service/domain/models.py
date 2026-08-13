"""Доменные модели LLM-сервиса."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, WithJsonSchema

from libs.shared.contracts.criteria_spec import CriteriaSpec

# Версия промпта входит в ключ кэша вердиктов: правка промпта обязана
# инвалидировать прежние решения, а не смешиваться с ними.
FILTER_COMPILE_PROMPT_VERSION = "compile-v1"
FILTER_JUDGE_PROMPT_VERSION = "judge-v1"
DIGEST_PROMPT_VERSION = "digest-v1"


# Pydantic описывает Decimal через строковый паттерн с look-ahead
# (`^(?!^[-+.]*$)…`). Серверы структурного вывода компилируют JSON-схему в
# грамматику и на look-ahead падают: «regex parse error: look-around … is not
# supported». Деньги остаются Decimal в Python — модели отдаём простое число.
Money = Annotated[Decimal | None, WithJsonSchema({"type": ["number", "null"]})]


class DateRange(BaseModel):
    since: date | None = None
    until: date | None = None


class SavedFilterView(BaseModel):
    """Карточка сохранённого фильтра для списка и страницы фильтра."""

    filter_id: int
    name: str
    query: str
    spec: CriteriaSpec
    in_digest: bool
    notify: bool
    is_active: bool
    created_at: datetime
    last_run_at: datetime | None = None


class FilterPatch(BaseModel):
    """Частичное изменение фильтра. None означает «не трогать это поле»."""

    name: str | None = None
    spec: CriteriaSpec | None = None
    in_digest: bool | None = None
    notify: bool | None = None
    is_active: bool | None = None

    @property
    def is_empty(self) -> bool:
        return not self.model_dump(exclude_none=True)


class FilterFunnel(BaseModel):
    """Сколько закупок отсеял каждый этап отбора.

    Ключевой ответ страницы конструктора: без разбивки непонятно, что именно
    сузило выдачу — цена, вектор или судья.
    """

    total: int
    after_structural: int
    after_semantic: int
    after_judge: int


class EvidenceItem(BaseModel):
    """Ссылка на фрагмент документа, обосновывающий вердикт."""

    document_id: int | None = None
    chunk_id: int | None = None
    page: int | None = None
    quote: str = ""


class Verdict(BaseModel):
    """Решение LLM-судьи по одному тендеру."""

    match: bool
    score: float = Field(ge=0.0, le=1.0, default=0.0)
    reasoning: str = ""
    evidence: list[EvidenceItem] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class CandidateChunk:
    """Фрагмент документа тендера, отобранный для передачи модели."""

    chunk_id: int
    document_id: int
    file_name: str | None
    page_from: int | None
    text: str


@dataclass(slots=True)
class TenderCandidate:
    """Тендер-кандидат вместе с релевантными фрагментами документации."""

    tender_id: int
    reg_num: str
    name: str | None
    description: str | None
    price: Decimal | None
    customer_name: str | None
    okpd2_code: str | None
    end_date: date | None
    chunks: list[CandidateChunk] = field(default_factory=list)
    lexical_rank: int | None = None
    semantic_rank: int | None = None

    def render_card(self) -> str:
        lines = [
            f"Реестровый номер: {self.reg_num}",
            f"Наименование: {self.name or '—'}",
            f"Объект закупки: {self.description or '—'}",
            f"НМЦК: {self.price if self.price is not None else '—'} руб.",
            f"Заказчик: {self.customer_name or '—'}",
            f"ОКПД2: {self.okpd2_code or '—'}",
            f"Приём заявок до: {self.end_date.isoformat() if self.end_date else '—'}",
        ]
        return "\n".join(lines)

    def render_documents(self, max_chars: int = 12000) -> str:
        """Фрагменты документации с указанием источника.

        Идентификаторы в заголовке позволяют модели сослаться на конкретный чанк,
        а нам — проверить, что цитата не выдумана.
        """
        if not self.chunks:
            return "Документация недоступна."

        parts: list[str] = []
        total = 0
        for chunk in self.chunks:
            page = f", стр. {chunk.page_from}" if chunk.page_from else ""
            header = f"[chunk_id={chunk.chunk_id}] {chunk.file_name or 'документ'}{page}"
            block = f"{header}\n{chunk.text}"
            if total + len(block) > max_chars:
                break
            parts.append(block)
            total += len(block)
        return "\n\n---\n\n".join(parts)


@dataclass(slots=True)
class DigestInput:
    """Материал для ежедневной сводки."""

    digest_date: date
    total: int
    total_price: Decimal
    top_by_price: list[TenderCandidate]
    clusters: dict[str, list[TenderCandidate]]
    deadline_changes: list[TenderCandidate]
    new_customers: list[str]
