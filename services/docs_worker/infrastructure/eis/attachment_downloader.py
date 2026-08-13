"""Скачивание вложений из файлового хранилища ЕИС."""

from __future__ import annotations

import threading
import time

import requests

from libs.shared.http.eis_session import build_session
from libs.shared.logging import get_logger
from services.docs_worker.application.ports import AttachmentDownloaderPort

log = get_logger(__name__)

# ЕИС не публикует лимиты, но легко отдаёт 429 при агрессивной выкачке.
# Одно извещение — до десятка файлов, а извещений за день сотни.
DEFAULT_REQUESTS_PER_SECOND = 2.0
MAX_DOCUMENT_BYTES = 300 * 1024 * 1024


class DownloadError(RuntimeError):
    """Скачать не удалось; имеет смысл повторить."""


class RateLimiter:
    """Простой лимитер: не чаще N запросов в секунду на процесс."""

    def __init__(self, requests_per_second: float) -> None:
        self._interval = 1.0 / requests_per_second if requests_per_second > 0 else 0.0
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def acquire(self) -> None:
        if self._interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            wait = max(0.0, self._next_allowed - now)
            self._next_allowed = max(now, self._next_allowed) + self._interval
        if wait:
            time.sleep(wait)


class EisAttachmentDownloader(AttachmentDownloaderPort):
    """Качает файл по прямой ссылке из `attachmentInfo/url`.

    Использует тот же TLS-адаптер, что и SOAP-клиент: файловое хранилище ЕИС живёт
    на том же наборе сертификатов и шифров.
    """

    def __init__(
        self,
        token: str,
        requests_per_second: float = DEFAULT_REQUESTS_PER_SECOND,
        timeout: int = 300,
    ) -> None:
        self._token = token
        self._session = build_session()
        self._limiter = RateLimiter(requests_per_second)
        self._timeout = timeout

    def download(self, url: str) -> tuple[bytes, str | None]:
        self._limiter.acquire()
        try:
            response = self._session.get(
                url,
                headers={"individualPerson_token": self._token},
                timeout=self._timeout,
                stream=True,
            )
            response.raise_for_status()

            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_content(chunk_size=64 * 1024):
                size += len(chunk)
                if size > MAX_DOCUMENT_BYTES:
                    raise DownloadError(f"Файл больше {MAX_DOCUMENT_BYTES} байт: {url}")
                chunks.append(chunk)
        except requests.RequestException as exc:
            raise DownloadError(f"Не удалось скачать {url}: {exc}") from exc

        content_type = response.headers.get("Content-Type")
        # ЕИС отдаёт имя файла в Content-Disposition, а тип — почти всегда octet-stream,
        # поэтому на content-type в выборе экстрактора не опираемся.
        return b"".join(chunks), content_type
