"""Состояние очередей через management API RabbitMQ.

Глубины очередей нет в базе — она есть только у брокера. Имена очередей и
лестница повторов берутся из `libs.shared.messaging.topology`, а не выписываются
строками: разъехавшись с топологией, мониторинг показывал бы несуществующие
очереди и молчал бы о настоящих.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from libs.shared.logging import get_logger
from libs.shared.messaging.topology import RETRY_DELAYS_MS
from services.api.application.ports.monitoring import QueueAdminPort
from services.api.domain.monitoring import (
    DeadLetter,
    QueuesSnapshot,
    QueueStat,
    RetryStage,
)

log = get_logger(__name__)

MANAGEMENT_TIMEOUT = 5.0
DEAD_LETTER_SAMPLE = 20

def _humanize(milliseconds: int) -> str:
    seconds = milliseconds // 1000
    if seconds < 60:
        return f"{seconds}с"
    if seconds < 3600:
        return f"{seconds // 60}м"
    return f"{seconds // 3600}ч"


# Подписи ступеней в том виде, в каком их читает человек: 5с → 30с → 2м → 10м → 1ч.
STAGE_LABELS = tuple(_humanize(ms) for ms in RETRY_DELAYS_MS)


class RabbitManagementClient(QueueAdminPort):
    def __init__(self, base_url: str, user: str, password: str, vhost: str = "/") -> None:
        self._base_url = base_url.rstrip("/")
        self._vhost = vhost
        self._client = httpx.AsyncClient(
            timeout=MANAGEMENT_TIMEOUT, auth=(user, password)
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def snapshot(self) -> QueuesSnapshot:
        queues = await self._queues()
        by_name = {q["name"]: q for q in queues}

        work: list[QueueStat] = []
        ladder: dict[str, int] = {label: 0 for label in STAGE_LABELS}

        for queue in queues:
            name = queue["name"]
            if ".retry." in name:
                index = _retry_index(name)
                if index is not None and index < len(STAGE_LABELS):
                    ladder[STAGE_LABELS[index]] += int(queue.get("messages", 0) or 0)
                continue
            if name.endswith(".dead"):
                continue

            work.append(
                QueueStat(
                    name=name,
                    depth=int(queue.get("messages", 0) or 0),
                    consumers=int(queue.get("consumers", 0) or 0),
                    dead_letters=int(
                        (by_name.get(f"{name}.dead") or {}).get("messages", 0) or 0
                    ),
                )
            )

        return QueuesSnapshot(
            queues=sorted(work, key=lambda q: q.name),
            retry_ladder=[RetryStage(stage=s, depth=ladder[s]) for s in STAGE_LABELS],
            dead_letters=await self._dead_letters(by_name),
        )

    async def requeue_dead_letter(self, message_id: str) -> bool:
        """Перекладывает сообщение из dead-letter обратно в рабочую очередь.

        Management API умеет только «достать сверху», поэтому конкретное
        сообщение ищется перебором головы очереди. Для ручного разбора десятка
        застрявших этого достаточно; массовый разбор — не задача интерфейса.
        """
        for queue in await self._queues():
            name = queue["name"]
            if not name.endswith(".dead") or not queue.get("messages"):
                continue

            messages = await self._get_messages(name, count=DEAD_LETTER_SAMPLE, ack=False)
            if not any(_message_id(m) == message_id for m in messages):
                continue

            target = name.removesuffix(".dead")
            # Достаём с подтверждением и публикуем в рабочую очередь заново.
            taken = await self._get_messages(name, count=DEAD_LETTER_SAMPLE, ack=True)
            for message in taken:
                destination = target if _message_id(message) == message_id else name
                await self._publish(destination, message)
            return True

        return False

    async def _queues(self) -> list[dict]:
        try:
            response = await self._client.get(f"{self._base_url}/api/queues")
            response.raise_for_status()
            return list(response.json())
        except Exception as exc:
            # Брокер недоступен — раздел покажет пустое состояние с ошибкой,
            # но остальная страница мониторинга обязана открыться.
            log.warning("monitoring.queues_unavailable", error=str(exc))
            return []

    async def _dead_letters(self, by_name: dict[str, dict]) -> list[DeadLetter]:
        result: list[DeadLetter] = []
        for name, queue in by_name.items():
            if not name.endswith(".dead") or not queue.get("messages"):
                continue
            for message in await self._get_messages(name, DEAD_LETTER_SAMPLE, ack=False):
                headers = (message.get("properties") or {}).get("headers") or {}
                result.append(
                    DeadLetter(
                        message_id=_message_id(message) or "—",
                        event=message.get("routing_key") or "—",
                        error=headers.get("x-error") or headers.get("error"),
                        retry_stage=_stage_of(headers),
                        failed_at=_timestamp_of(message),
                    )
                )
        return result

    async def _get_messages(self, queue: str, count: int, ack: bool) -> list[dict]:
        payload = {
            "count": count,
            # `ack_requeue_true` возвращает сообщения на место — так их можно
            # посмотреть, не изымая из очереди.
            "ackmode": "ack_requeue_false" if ack else "ack_requeue_true",
            "encoding": "auto",
        }
        try:
            response = await self._client.post(
                f"{self._base_url}/api/queues/{_quote(self._vhost)}/{queue}/get", json=payload
            )
            response.raise_for_status()
            return list(response.json())
        except Exception as exc:
            log.warning("monitoring.queue_read_failed", queue=queue, error=str(exc))
            return []

    async def _publish(self, queue: str, message: dict) -> None:
        payload = {
            "properties": message.get("properties") or {},
            "routing_key": queue,
            "payload": message.get("payload", ""),
            "payload_encoding": message.get("payload_encoding", "string"),
        }
        await self._client.post(
            f"{self._base_url}/api/exchanges/{_quote(self._vhost)}/amq.default/publish",
            json=payload,
        )


def _quote(vhost: str) -> str:
    return "%2F" if vhost == "/" else vhost


def _retry_index(queue_name: str) -> int | None:
    tail = queue_name.rsplit(".", 1)[-1]
    return int(tail) if tail.isdigit() else None


def _message_id(message: dict) -> str | None:
    properties = message.get("properties") or {}
    headers = properties.get("headers") or {}
    return properties.get("message_id") or headers.get("event_id")


def _stage_of(headers: dict) -> str | None:
    death = headers.get("x-death")
    if isinstance(death, list) and death:
        count = death[0].get("count")
        if isinstance(count, int) and 0 < count <= len(STAGE_LABELS):
            return STAGE_LABELS[count - 1]
    return None


def _timestamp_of(message: dict) -> datetime | None:
    properties = message.get("properties") or {}
    stamp = properties.get("timestamp")
    if isinstance(stamp, int):
        return datetime.fromtimestamp(stamp, tz=UTC)
    return None
