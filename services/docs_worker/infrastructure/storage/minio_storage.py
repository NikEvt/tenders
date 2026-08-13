"""Адаптер объектного хранилища поверх MinIO."""

from __future__ import annotations

import io
from datetime import timedelta
from typing import BinaryIO

from minio import Minio
from minio.error import S3Error

from libs.shared.config import MinioSettings
from libs.shared.contracts.ports import ObjectStoragePort
from libs.shared.logging import get_logger

log = get_logger(__name__)


class MinioObjectStorage(ObjectStoragePort):
    """Хранит исходники документов. Бакет создаётся при старте, если его нет."""

    def __init__(self, settings: MinioSettings) -> None:
        self._bucket = settings.bucket
        self._client = Minio(
            settings.endpoint,
            access_key=settings.access_key,
            secret_key=settings.secret_key.get_secret_value(),
            secure=settings.secure,
        )

    def ensure_bucket(self) -> None:
        if not self._client.bucket_exists(self._bucket):
            self._client.make_bucket(self._bucket)
            log.info("minio.bucket_created", bucket=self._bucket)

    def put(
        self,
        key: str,
        data: BinaryIO,
        size: int,
        content_type: str | None = None,
    ) -> None:
        self._client.put_object(
            self._bucket,
            key,
            data,
            length=size,
            content_type=content_type or "application/octet-stream",
        )

    def put_bytes(self, key: str, content: bytes, content_type: str | None = None) -> None:
        self.put(key, io.BytesIO(content), len(content), content_type)

    def get(self, key: str) -> bytes:
        response = self._client.get_object(self._bucket, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def exists(self, key: str) -> bool:
        try:
            self._client.stat_object(self._bucket, key)
            return True
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject"}:
                return False
            raise

    def presigned_url(self, key: str, expires_seconds: int = 3600) -> str:
        return self._client.presigned_get_object(
            self._bucket, key, expires=timedelta(seconds=expires_seconds)
        )
