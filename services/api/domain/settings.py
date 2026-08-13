"""Действующие настройки системы — только для показа.

Клиент отсюда ничего не меняет: значения приходят из окружения и вступают в
силу при старте процесса. Единственное, что записывается, — подтверждение
ротации токена, и оно живёт в `app_settings`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

# Ключ, под которым хранится отметка о ротации токена — единственное, что
# интерфейс когда-либо записывает.
TOKEN_ROTATED_KEY = "eis_token.rotated_at"


@dataclass(slots=True)
class LlmSettingsView:
    base_url: str
    model: str
    auth_scheme: str
    reasoning_effort: str
    judge_reasoning_effort: str


@dataclass(slots=True)
class CrawlerSettingsView:
    regions: list[str]
    document_types: list[str]
    interval_minutes: int


@dataclass(slots=True)
class CertificateInfo:
    """Корневой сертификат ЕИС: без него TLS к хранилищу не проходит."""

    subject: str
    fingerprint: str
    not_after: date | None


@dataclass(slots=True)
class TokenState:
    """Токен ЕИС показывается маскированным — целиком он не нужен никому."""

    masked: str
    rotated_at: datetime | None


@dataclass(slots=True)
class EffectiveSettings:
    llm: LlmSettingsView
    crawler: CrawlerSettingsView
    embedding: dict[str, object]
    certificates: list[CertificateInfo]
    eis_token: TokenState
    # Ключи, которые читаются только на старте: правка в .env без перезапуска
    # ничего не изменит, и интерфейс обязан об этом предупредить.
    restart_required_keys: list[str] = field(default_factory=list)
