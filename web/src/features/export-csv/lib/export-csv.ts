import type { Tender } from "@/shared/api/types";
import { dateShort, regionName } from "@/shared/lib/format";
import { tenderStatus } from "@/entities/tender/model/status";
import { ru } from "@/shared/i18n/ru";

const COLUMNS: { header: string; value: (tender: Tender) => string }[] = [
  { header: ru.tender.regNum, value: (t) => t.reg_num },
  { header: "Наименование", value: (t) => t.name ?? "" },
  { header: ru.tender.customer, value: (t) => t.customer_name ?? "" },
  { header: ru.tender.inn, value: (t) => t.customer_inn ?? "" },
  { header: ru.tender.priceShort, value: (t) => (t.price === null ? "" : String(t.price)) },
  { header: ru.tender.okpd2, value: (t) => t.okpd2_code ?? "" },
  { header: ru.tender.region, value: (t) => regionName(t.region_code) },
  { header: ru.tender.published, value: (t) => dateShort(t.publish_date) },
  { header: ru.tender.deadline, value: (t) => dateShort(t.end_date) },
  { header: "Статус (вычислен)", value: (t) => tenderStatus(t).label },
  { header: ru.tender.documentCount, value: (t) => String(t.document_count) },
];

/**
 * CSV с разделителем «;» и BOM — иначе Excel в русской локали открывает файл
 * одной колонкой и с испорченной кириллицей.
 */
export function tendersToCsv(tenders: Tender[]): string {
  const escape = (value: string) => `"${value.replace(/"/g, '""')}"`;
  const rows = [
    COLUMNS.map((column) => escape(column.header)).join(";"),
    ...tenders.map((tender) => COLUMNS.map((column) => escape(column.value(tender))).join(";")),
  ];
  // BOM: без него Excel в русской локали открывает файл с испорченной кириллицей.
  return `\ufeff${rows.join("\r\n")}`;
}

export function downloadCsv(tenders: Tender[], fileName: string): void {
  const blob = new Blob([tendersToCsv(tenders)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  link.click();
  URL.revokeObjectURL(url);
}
