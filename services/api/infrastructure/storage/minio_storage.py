"""Доступ к файлам документов из шлюза.

Шлюзу нужна только выдача presigned-ссылок: сами файлы через него не текут,
клиент скачивает их напрямую из MinIO.
"""

from __future__ import annotations

from datetime import timedelta
from typing import BinaryIO

from minio import Minio

from libs.shared.config import MinioSettings
from libs.shared.contracts.ports import ObjectStoragePort


class MinioReadStorage(ObjectStoragePort):
    def __init__(self, settings: MinioSettings) -> None:
        self._bucket = settings.bucket
        self._client = Minio(
            settings.endpoint,
            access_key=settings.access_key,
            secret_key=settings.secret_key.get_secret_value(),
            secure=settings.secure,
        )

    def put(self, key: str, data: BinaryIO, size: int, content_type: str | None = None) -> None:
        raise NotImplementedError("Шлюз файлы не пишет — это дело docs-worker")

    def put_bytes(self, key: str, content: bytes, content_type: str | None = None) -> None:
        raise NotImplementedError("Шлюз файлы не пишет — это дело docs-worker")

    def get(self, key: str) -> bytes:
        response = self._client.get_object(self._bucket, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def exists(self, key: str) -> bool:
        from minio.error import S3Error

        try:
            self._client.stat_object(self._bucket, key)
            return True
        except S3Error:
            return False

    def presigned_url(self, key: str, expires_seconds: int = 3600) -> str:
        return self._client.presigned_get_object(
            self._bucket, key, expires=timedelta(seconds=expires_seconds)
        )
