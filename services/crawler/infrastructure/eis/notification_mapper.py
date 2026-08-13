"""Разбор XML-извещений ЕИС в доменную модель.

Pure Fabrication (GRASP): не домен и не хранилище, а выделенный преобразователь.

Префиксы namespace (`ns2`…`ns15`) сервер раздаёт документу произвольно, поэтому
опираться на них, как это делал прежний код (`ns5:x or x` на каждое поле), нельзя.
Здесь префиксы срезаются один раз при разборе, и дальше используются только
локальные имена.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import xmltodict

from libs.shared.logging import get_logger
from services.crawler.domain.models import Attachment, Tender

log = get_logger(__name__)

Node = dict[str, Any]

# «2026-06-09T00:00:35.324+03:00» / «2026-06-09+03:00» — ЕИС смешивает оба формата.
_TZ_SUFFIX = re.compile(r"([+-]\d{2}:?\d{2}|Z)$")


def strip_namespaces(obj: Any) -> Any:
    """Рекурсивно срезает `nsN:` с ключей. Атрибуты (`@attr`) сохраняются."""
    if isinstance(obj, dict):
        return {key.rsplit(":", 1)[-1]: strip_namespaces(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [strip_namespaces(item) for item in obj]
    return obj


def as_list(value: Any) -> list[Any]:
    """xmltodict сворачивает единственный элемент в словарь — разворачиваем обратно."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def dig(node: Any, *path: str) -> Any:
    """Безопасный проход по вложенным словарям."""
    current = node
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _parse_datetime(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        log.debug("mapper.bad_datetime", value=raw)
        return None


def _parse_date(raw: Any) -> date | None:
    """Разбирает `2026-06-09+03:00` и `2026-06-09T…` в календарную дату.

    Смещение отбрасывается намеренно: это дата по календарю заказчика, а не момент
    времени, и сдвиг в UTC изменил бы её на сутки.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    value = raw.strip()
    if "T" in value:
        parsed = _parse_datetime(value)
        return parsed.date() if parsed else None
    value = _TZ_SUFFIX.sub("", value)
    try:
        return date.fromisoformat(value)
    except ValueError:
        log.debug("mapper.bad_date", value=raw)
        return None


def _parse_price(raw: Any) -> Decimal | None:
    if raw in (None, ""):
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        log.debug("mapper.bad_price", value=raw)
        return None


def _iter_okpd2(purchase_objects: list[Node]) -> Iterator[tuple[str, str | None]]:
    """Достаёт коды ОКПД2 из объектов закупки.

    Код лежит либо прямо в объекте, либо внутри позиции КТРУ. В выгрузках ЕАФ
    практически всегда встречается второй вариант — прежний код искал только
    первый и поэтому оставлял `okpd2_code` пустым.
    """
    for obj in purchase_objects:
        if not isinstance(obj, dict):
            continue
        okpd2 = obj.get("OKPD2") or dig(obj, "KTRU", "OKPD2")
        if not isinstance(okpd2, dict):
            continue
        code = okpd2.get("OKPDCode")
        if isinstance(code, str) and code:
            name = okpd2.get("OKPDName")
            yield code, name if isinstance(name, str) else None


def _extract_attachments(notification: Node) -> list[Attachment]:
    """Вложения извещения — основная документация закупки.

    Криптоподписи (`cryptoSigns`) сюда не попадают: это не документы.
    """
    attachments: list[Attachment] = []
    for raw in as_list(dig(notification, "attachmentsInfo", "attachmentInfo")):
        if not isinstance(raw, dict):
            continue
        attachment_id = raw.get("publishedContentId")
        if not isinstance(attachment_id, str) or not attachment_id:
            continue
        size = raw.get("fileSize")
        attachments.append(
            Attachment(
                attachment_id=attachment_id,
                file_name=raw.get("fileName"),
                url=raw.get("url"),
                file_size=int(size) if str(size).isdigit() else None,
                doc_description=raw.get("docDescription"),
                doc_kind_code=dig(raw, "docKindInfo", "code"),
                doc_kind_name=dig(raw, "docKindInfo", "name"),
            )
        )
    return attachments


class NotificationMapper:
    """XML одного извещения → `Tender`."""

    #: Корневые элементы, которые считаем извещением о закупке.
    NOTIFICATION_PREFIXES = ("epNotification", "notification", "ntfNotification")

    def __init__(self, region_code: str | None = None, law_type: str = "44-FZ") -> None:
        self._region_code = region_code
        self._law_type = law_type

    def map_document(self, xml_dict: Node) -> Tender | None:
        """Возвращает `None`, если документ не является извещением или битый."""
        try:
            normalized = strip_namespaces(xml_dict)
            notification = self._find_notification(normalized)
            if notification is None:
                return None
            return self._build(notification, xml_dict)
        except Exception as exc:
            log.warning("mapper.failed", error=str(exc), exc_info=True)
            return None

    def _find_notification(self, root: Node) -> Node | None:
        """Находит узел извещения независимо от обёртки `export`."""
        candidates: list[Node] = [root]
        export = root.get("export")
        if isinstance(export, dict):
            candidates.append(export)

        for candidate in candidates:
            for key, value in candidate.items():
                if key.startswith(self.NOTIFICATION_PREFIXES) and isinstance(value, dict):
                    return value
        return None

    def _build(self, notification: Node, original: Node) -> Tender | None:
        common = notification.get("commonInfo")
        if not isinstance(common, dict):
            return None

        reg_num = common.get("purchaseNumber")
        if not isinstance(reg_num, str) or not reg_num:
            return None

        description = common.get("purchaseObjectInfo")
        notification_info = notification.get("notificationInfo") or {}
        contract_conditions = dig(notification_info, "contractConditionsInfo") or {}
        max_price_info = contract_conditions.get("maxPriceInfo") or {}
        procedure = notification_info.get("procedureInfo") or {}
        collecting = procedure.get("collectingInfo") or {}
        responsible = dig(notification, "purchaseResponsibleInfo", "responsibleOrgInfo") or {}

        purchase_objects = as_list(
            dig(
                notification_info,
                "purchaseObjectsInfo",
                "notDrugPurchaseObjectsInfo",
                "purchaseObject",
            )
        )
        okpd2_pairs = list(_iter_okpd2(purchase_objects))
        # dict.fromkeys — дедупликация с сохранением порядка появления в извещении.
        codes = list(dict.fromkeys(code for code, _ in okpd2_pairs))
        names_by_code = {code: name for code, name in okpd2_pairs if name}

        return Tender(
            reg_num=reg_num,
            name=common.get("name") or description,
            description=description,
            price=_parse_price(max_price_info.get("maxPrice")),
            currency=dig(max_price_info, "currency", "code") or "RUB",
            publish_date=_parse_datetime(common.get("publishDTInEIS")),
            direct_date=_parse_datetime(common.get("directDT")),
            planned_publish_date=_parse_date(common.get("plannedPublishDate")),
            start_date=_parse_datetime(collecting.get("startDT")),
            end_date=_parse_datetime(collecting.get("endDT")),
            bidding_date=_parse_date(procedure.get("biddingDate")),
            summarizing_date=_parse_date(procedure.get("summarizingDate")),
            contract_end_date=_parse_date(contract_conditions.get("endDate")),
            customer_name=responsible.get("fullName"),
            customer_inn=responsible.get("INN"),
            customer_region=None,
            region_code=self._region_code,
            okpd2_codes=codes,
            okpd2_names=[names_by_code.get(code, "") for code in codes],
            law_type=self._law_type,
            raw_xml=xmltodict.unparse(original, pretty=True),
            attachments=_extract_attachments(notification),
        )
