"""Чтение извлечённого текста из объектного хранилища."""

from __future__ import annotations

import asyncio

from minio import Minio

from libs.shared.config import MinioSettings
from libs.shared.text_objects import decode_text
from services.research.application.ports import TextStoragePort


class MinioTextStorage(TextStoragePort):
    """Только чтение: писать тексты — дело docs-worker.

    Клиент MinIO синхронный, поэтому чтение уходит в тред: движок перебирает
    тысячи документов, и блокировать на них событийный цикл нельзя.
    """

    def __init__(self, settings: MinioSettings) -> None:
        self._bucket = settings.bucket
        self._client = Minio(
            settings.endpoint,
            access_key=settings.access_key,
            secret_key=settings.secret_key.get_secret_value(),
            secure=settings.secure,
        )

    async def read(self, text_key: str) -> str:
        return decode_text(await asyncio.to_thread(self._read, text_key))

    def _read(self, text_key: str) -> bytes:
        response = None
        try:
            response = self._client.get_object(self._bucket, text_key)
            return response.read()
        finally:
            if response is not None:
                response.close()
                response.release_conn()
