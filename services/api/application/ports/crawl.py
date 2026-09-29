"""Заказ выгрузки из ЕИС.

Шлюз здесь впервые не только читает, но и отдаёт команду. Это осознанно:
краулер — воркер без HTTP-порта, и заказать у него выгрузку можно только
событием. Проксировать заявку через llm-service было бы враньём про владельца —
выгрузкой он не владеет.

Инвариант «сервисы связаны только событиями и HTTP» это не нарушает, а
исполняет: шлюз принимает команду от человека и передаёт её владельцу
принятым в системе способом.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import date


class CrawlPublisherPort(ABC):
    @abstractmethod
    async def request(
        self,
        job_id: uuid.UUID,
        regions: Sequence[str],
        date_from: date,
        date_to: date,
    ) -> None:
        """Публикует заявку на выгрузку периода.

        Пустые регионы означают «все настроенные у краулера»: шлюз не знает и
        не должен знать, какие именно тот качает.
        """
