"""Подбор порога векторной близости по реальным данным.

Векторный поиск возвращает N ближайших независимо от того, насколько они
близки. Пока эмбеддингов меньше, чем размер пула, «ближайшие» — это вообще все,
и любой запрос отдаёт весь корпус. Нужен порог, ниже которого совпадение
считается шумом.

Порог нельзя выбрать из общих соображений: он зависит от модели и от того, как
устроены тексты. Скрипт печатает распределение близости по набору запросов и
предлагает границу — решение остаётся за человеком, читающим таблицу.

Запуск:  python -m scripts.calibrate_similarity
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.request

from sqlalchemy import text

from libs.shared.config import database_settings, embedding_settings
from libs.shared.db.base import create_engine

# Запросы подобраны так, чтобы охватить оба края: у одних в корпусе есть точный
# ответ, у других — заведомо нет.
QUERIES = [
    "поставка офисной мебели",
    "мебель",
    "бумага для принтера",
    "медицинские перчатки",
    "ремонт кровли",
    "программное обеспечение",
    "услуги охраны",
    "поставка кислорода в баллонах",
    # Заведомо чужие для этого корпуса: их лучшие совпадения задают уровень шума.
    "запуск спутника на орбиту",
    "дрессировка служебных собак",
]

# Доли, по которым видно форму распределения.
PERCENTILES = (0.999, 0.99, 0.95, 0.9, 0.5)


async def _embed(query: str) -> list[float]:
    url = os.getenv("EMBEDDING_SERVICE_URL", embedding_settings().service_url)
    request = urllib.request.Request(
        f"{url.rstrip('/')}/embed",
        data=json.dumps({"texts": [query], "is_query": True}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read())["vectors"][0]


async def main() -> None:
    engine = create_engine(database_settings().async_dsn)
    rows: list[tuple[str, float, float, list[float]]] = []

    async with engine.connect() as connection:
        total = await connection.scalar(text("select count(*) from tender_embeddings"))
        print(f"Закупок с эмбеддингом: {total}\n")
        print(f"{'запрос':32} {'лучшее':>7} {'2-е':>7} " + " ".join(f"{p:>7}" for p in PERCENTILES))
        print("-" * 96)

        for query in QUERIES:
            vector = await _embed(query)
            sims = list(
                await connection.scalars(
                    text(
                        "select (1 - (embedding <=> :v))::float as sim "
                        "from tender_embeddings order by sim desc"
                    ),
                    {"v": str(vector)},
                )
            )
            if not sims:
                continue
            quantiles = [sims[min(len(sims) - 1, int(len(sims) * (1 - p)))] for p in PERCENTILES]
            rows.append((query, sims[0], sims[1] if len(sims) > 1 else 0.0, quantiles))
            print(
                f"{query[:32]:32} {sims[0]:7.3f} {rows[-1][2]:7.3f} "
                + " ".join(f"{q:7.3f}" for q in quantiles)
            )

    await engine.dispose()

    # Уровень шума — то, что лучший результат даёт на заведомо чужом запросе.
    noise = max(best for query, best, _, _ in rows if query in QUERIES[-2:])
    hits = [best for query, best, _, _ in rows if query not in QUERIES[-2:]]
    print(
        f"\nПотолок шума (лучшее на чужих запросах): {noise:.3f}"
        f"\nХудшее попадание на своих запросах:      {min(hits):.3f}"
        f"\nПорог посередине:                        {(noise + min(hits)) / 2:.3f}"
    )
    print(
        "\nЕсли «худшее попадание» ниже «потолка шума», разделить их одним числом"
        "\nнельзя — значит, порог отсечёт часть верных совпадений, и выбирать"
        "\nпридётся, чем жертвовать."
    )


if __name__ == "__main__":
    asyncio.run(main())
