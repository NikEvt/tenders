"""Действующие настройки: то, с чем процесс работает прямо сейчас.

Читаются из тех же объектов конфигурации, что и в рантайме, — иначе экран
показывал бы содержимое `.env`, а не то, что реально применилось. Секреты
маскируются здесь, а не в схеме ответа: значение не должно покидать этот слой
в открытом виде даже внутри процесса.
"""

from __future__ import annotations

import os
import ssl
from datetime import date, datetime
from pathlib import Path

from libs.shared.config import EisSettings, EmbeddingSettings, LlmSettings
from libs.shared.logging import get_logger
from services.api.application.ports.settings import RuntimeSettingsPort
from services.api.domain.settings import (
    CertificateInfo,
    CrawlerSettingsView,
    EffectiveSettings,
    LlmSettingsView,
    TokenState,
)

log = get_logger(__name__)

CERT_DIR = Path("/usr/local/share/ca-certificates")

# Читаются один раз при старте процесса: правка без перезапуска не подействует.
RESTART_REQUIRED_KEYS = (
    "LLM_BASE_URL",
    "LLM_MODEL",
    "LLM_AUTH_SCHEME",
    "EMBEDDING_MODEL",
    "EMBEDDING_DIM",
    "EMBEDDING_DEVICE",
    "EIS_TOKEN",
    "EIS_REGIONS",
    "EIS_DOCUMENT_TYPES",
    "DOCS_WORKER_PREFETCH",
    "EMBEDDING_PREFETCH",
)


class EnvRuntimeSettings(RuntimeSettingsPort):
    def __init__(
        self, llm: LlmSettings, eis: EisSettings, embedding: EmbeddingSettings
    ) -> None:
        self._llm = llm
        self._eis = eis
        self._embedding = embedding

    def effective(self) -> EffectiveSettings:
        return EffectiveSettings(
            llm=LlmSettingsView(
                base_url=self._llm.base_url,
                model=self._llm.model,
                auth_scheme=self._llm.auth_scheme,
                reasoning_effort=self._llm.reasoning_effort,
                judge_reasoning_effort=self._llm.judge_reasoning_effort,
            ),
            crawler=CrawlerSettingsView(
                regions=self._eis.region_list,
                document_types=self._eis.document_type_list,
                interval_minutes=self._eis.crawl_interval_minutes,
            ),
            embedding={
                "model": self._embedding.model,
                "dim": self._embedding.dim,
                "device": self._embedding.device or "автоопределение",
            },
            certificates=_certificates(),
            eis_token=TokenState(masked=_mask(_secret(self._eis.token)), rotated_at=None),
            restart_required_keys=[
                key for key in RESTART_REQUIRED_KEYS if os.getenv(key) is not None
            ],
        )


def _secret(value: object) -> str:
    getter = getattr(value, "get_secret_value", None)
    return getter() if callable(getter) else str(value or "")


def _mask(token: str) -> str:
    """Хвост нужен, чтобы отличить один токен от другого, и только.

    Короткое значение не маскируется частично — из четырёх символов «хвост»
    восстановил бы почти весь секрет.
    """
    if not token:
        return "не задан"
    if len(token) <= 8:
        return "•" * len(token)
    return f"{'•' * 8}{token[-4:]}"


def _certificates() -> list[CertificateInfo]:
    """Сертификаты ЕИС, установленные в образ.

    Показываются вместе со сроком: истёкший корень — это отказ всей выгрузки,
    и узнать о нём заранее дешевле, чем по остановившемуся краулеру.
    """
    if not CERT_DIR.exists():
        return []

    result: list[CertificateInfo] = []
    for path in sorted(CERT_DIR.glob("*.crt")):
        try:
            parsed = ssl._ssl._test_decode_cert(str(path))  # type: ignore[attr-defined]
        except Exception as exc:
            log.info("settings.cert_unreadable", path=str(path), error=str(exc))
            continue

        result.append(
            CertificateInfo(
                subject=_common_name(parsed.get("subject", ())) or path.stem,
                fingerprint=path.stem,
                not_after=_parse_date(parsed.get("notAfter")),
            )
        )
    return result


def _common_name(subject: tuple) -> str | None:
    for group in subject:
        for key, value in group:
            if key == "commonName":
                return value
    return None


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%b %d %H:%M:%S %Y %Z").date()
    except ValueError:
        return None
