"""Точка входа процесса: собирает приложение и связывает порты с реализациями.

Единственный модуль шлюза, который знает и presentation, и bootstrap. Отсюда
`uvicorn services.api.main:app`.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from libs.shared.config import database_settings, embedding_settings, minio_settings
from libs.shared.logging import configure_logging, get_logger
from services.api.bootstrap import build_container
from services.api.presentation.app import create_app

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging("api")

    async with build_container(
        database_settings(),
        minio_settings(),
        embedding_settings(),
        llm_url=os.getenv("LLM_SERVICE_URL", "http://llm-service:8010"),
        recsys_url=os.getenv("RECSYS_SERVICE_URL", "http://recsys-service:8030"),
    ) as container:
        # Состояние приложения, а не глобальная переменная модуля: так тесты
        # подменяют контейнер, не трогая импорты.
        app.state.ports = container
        log.info("api.ready")
        try:
            yield
        finally:
            app.state.ports = None


app = create_app(lifespan=lifespan)
