"""HTTP-шлюз: сборка приложения.

Здесь нет ни одной реализации: ни SQL, ни HTTP-клиентов, ни настроек подключения.
Приложение объявляет маршруты и сквозное поведение, а чем закрыты порты — решает
`services/api/main.py`. Благодаря этому `create_app()` поднимается в тесте за
миллисекунды, без базы и соседних сервисов.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from libs.shared.logging import get_logger
from services.api.presentation.errors import install_error_handlers
from services.api.presentation.middleware import REQUEST_ID_HEADER, RequestContextMiddleware
from services.api.presentation.routers import ROUTERS

log = get_logger(__name__)


def create_app(lifespan: Callable[[FastAPI], Any] | None = None) -> FastAPI:
    app = FastAPI(
        title="zakupki API",
        description="Каталог, поиск, LLM-фильтрация, сводки и рекомендации по закупкам 44-ФЗ",
        lifespan=lifespan,
    )

    install_error_handlers(app)

    # Порядок обратен порядку вызовов: добавленное последним оборачивает
    # остальное. CORS должен быть снаружи, иначе браузер не увидит заголовков на
    # ответе 500, а идентификатор запроса — внутри, чтобы попасть и в тело ошибки.
    app.add_middleware(RequestContextMiddleware)
    # Фронт живёт на другом порту; список источников сузьте под свой домен на проде.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
        allow_methods=["*"],
        allow_headers=["*"],
        # Без этого браузер спрячет заголовок от клиента, и «Скопировать детали»
        # приложит ошибку без идентификатора — то есть бесполезную для поиска в логах.
        expose_headers=[REQUEST_ID_HEADER],
    )

    for router in ROUTERS:
        app.include_router(router)

    return app
