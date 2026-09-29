"""Сценарии вкладки «Данные»: состав корпуса и ход его обогащения."""

from __future__ import annotations

from datetime import date, timedelta

from services.api.application.errors import InvalidRequest
from services.api.application.ports.corpus import CorpusStatsPort
from services.api.application.ports.monitoring import DocumentPipelinePort, QueueAdminPort
from services.api.domain.corpus import CorpusOverview, CorpusProcessing

#: Окно по умолчанию. Квартал — тот срок, на котором сезонность видна, а
#: гистограмма ещё читается по дням.
DEFAULT_DAYS = 90

#: Потолок окна. Дальше групповой запрос по всей `tenders` перестаёт быть
#: дешёвым, а гистограмма из тысячи столбцов — читаемой.
MAX_DAYS = 366

DEFAULT_TOP = 12
MAX_TOP = 50

#: Очередь сервиса эмбеддингов. Имя дублируется из
#: `embedding_service/presentation/app.py` не по недосмотру: сервисы не
#: импортируют друг друга, и общее у них — брокер, а не код.
EMBEDDING_QUEUE = "embedding-service.enrichment"


class CorpusOverviewUseCase:
    """Состав корпуса за период.

    Период один на все разрезы — и это решение о честности, а не об экономии:
    «топ регионов за всё время» рядом со столбиками за 90 дней описывали бы
    разные множества, выглядя одним разрезом.
    """

    def __init__(self, corpus: CorpusStatsPort) -> None:
        self._corpus = corpus

    async def execute(
        self, days: int = DEFAULT_DAYS, limit: int = DEFAULT_TOP, today: date | None = None
    ) -> CorpusOverview:
        if days < 1 or days > MAX_DAYS:
            raise InvalidRequest(f"Период должен быть от 1 до {MAX_DAYS} дней")
        if limit < 1 or limit > MAX_TOP:
            raise InvalidRequest(f"Верхушка разреза — от 1 до {MAX_TOP} значений")

        until = today or date.today()
        return await self._corpus.overview(until - timedelta(days=days - 1), until, limit)


class CorpusProcessingUseCase:
    """Что происходит с корпусом прямо сейчас.

    Собирается из трёх портов, а не из одного запроса: воронка документов уже
    посчитана мониторингом, глубина очереди — брокером. Считать их здесь заново
    значило бы завести второй источник тех же чисел.
    """

    def __init__(
        self,
        corpus: CorpusStatsPort,
        pipeline: DocumentPipelinePort,
        queues: QueueAdminPort,
    ) -> None:
        self._corpus = corpus
        self._pipeline = pipeline
        self._queues = queues

    async def execute(self, today: date | None = None) -> CorpusProcessing:
        day = today or date.today()
        embeddings = await self._corpus.embeddings()
        embeddings.queue_depth = await self._queue_depth()
        funnel = await self._pipeline.funnel()

        return CorpusProcessing(
            embeddings=embeddings,
            today=await self._corpus.today(day),
            documents_downloaded=funnel.downloaded,
            documents_extracted=funnel.extracted,
        )

    async def _queue_depth(self) -> int | None:
        """Хвост очереди эмбеддингов — или честное «не знаю».

        Брокер может не ответить, и это факт о брокере. Ноль на его месте
        читался бы как «работы нет», то есть как «всё посчитано».
        """
        try:
            snapshot = await self._queues.snapshot()
        except Exception:
            return None
        for queue in snapshot.queues:
            if queue.name == EMBEDDING_QUEUE:
                return queue.depth
        return None
