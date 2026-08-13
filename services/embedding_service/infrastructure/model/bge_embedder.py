"""Локальная модель эмбеддингов (deepvk/USER-bge-m3)."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Sequence
from typing import Any

from libs.shared.contracts.ports import EmbedderPort
from libs.shared.logging import get_logger
from services.embedding_service.domain.models import MAX_INPUT_CHARS, QUERY_PREFIX

log = get_logger(__name__)


def detect_device() -> str:
    """Выбирает лучшее доступное устройство.

    `mps` — Metal на Apple Silicon; работает только при нативном запуске на macOS.
    Внутри Docker Desktop его нет: контейнер живёт в Linux-VM, куда Metal
    не пробрасывается, поэтому в образе всегда окажется `cpu`.
    """
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available() and torch.backends.mps.is_built():
        return "mps"
    return "cpu"


def _thread_budget() -> int:
    """Сколько потоков может позволить себе инференс.

    `os.cpu_count()` внутри контейнера показывает ядра хоста, а не квоту
    cgroup, поэтому спрашиваем планировщик: `sched_getaffinity` учитывает
    `cpuset`, а `OMP_NUM_THREADS` задаётся в compose вместе с лимитом.
    """
    declared = os.getenv("OMP_NUM_THREADS")
    if declared and declared.isdigit() and int(declared) > 0:
        return int(declared)

    available = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else 0
    return max(1, available or (os.cpu_count() or 1))


class SentenceTransformerEmbedder(EmbedderPort):
    """Обёртка над sentence-transformers.

    Модель весит ~2 ГБ и грузится единожды при старте процесса. Инференс
    синхронный и CPU/GPU-bound, поэтому уводится в пул потоков — иначе один
    запрос блокирует весь событийный цикл сервиса.
    """

    def __init__(self, model_name: str, dim: int, device: str | None = None) -> None:
        self._model_name = model_name
        self._dim = dim
        self._device = device
        self._model: Any | None = None
        # Модель не потокобезопасна на батчах: сериализуем доступ.
        self._lock = asyncio.Lock()

    @property
    def device(self) -> str:
        return self._device or "не определено"

    def load(self) -> None:
        import torch
        from sentence_transformers import SentenceTransformer

        self._device = self._device or detect_device()

        # На CPU torch по умолчанию берёт столько потоков, сколько видит ядер, —
        # а видит он ядра хоста, а не выделенную контейнеру квоту. Под лимитом
        # cgroup это не ускоряет, а замедляет: потоки дерутся за ту же долю CPU.
        # Держим число потоков в пределах квоты.
        if self._device == "cpu":
            torch.set_num_threads(_thread_budget())
            log.info("embedder.threads", threads=torch.get_num_threads())

        log.info("embedder.loading", model=self._model_name, device=self._device)
        self._model = SentenceTransformer(self._model_name, device=self._device)

        # В sentence-transformers 5.x метод переименован; поддерживаем оба имени,
        # чтобы сервис не сломался ни на старой, ни на новой версии.
        get_dim = getattr(
            self._model, "get_embedding_dimension", None
        ) or self._model.get_sentence_embedding_dimension
        actual = get_dim()
        if actual != self._dim:
            # Расхождение с vector(N) в схеме проявилось бы только при вставке —
            # лучше упасть на старте, чем терять сообщения в рантайме.
            raise RuntimeError(
                f"Модель {self._model_name} даёт {actual}-мерные векторы, "
                f"а схема БД ожидает {self._dim}. Поправьте EMBEDDING_DIM и миграцию."
            )
        log.info("embedder.loaded", model=self._model_name, dim=actual)

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def model_name(self) -> str:
        return self._model_name

    async def embed(self, texts: Sequence[str], is_query: bool = False) -> list[list[float]]:
        if self._model is None:
            raise RuntimeError("Модель не загружена: вызовите load()")
        if not texts:
            return []

        prepared = [
            (QUERY_PREFIX + text if is_query else text)[:MAX_INPUT_CHARS] for text in texts
        ]

        async with self._lock:
            vectors = await asyncio.to_thread(self._encode, prepared)
        return vectors

    def _encode(self, texts: list[str]) -> list[list[float]]:
        assert self._model is not None
        # Нормализация обязательна: индексы построены под косинусную метрику.
        result = self._model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return [vector.tolist() for vector in result]
