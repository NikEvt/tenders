import type { GroupBucket, Tender } from "@/shared/api/types";
import { sortField } from "@/entities/tender/model/sort";

export const HEADER_HEIGHT = 40;
export const GROUP_ROW_HEIGHT = 72;

export type FlatHeader = {
  kind: "header";
  /** Устойчивый ключ строки: поле + значение категории. */
  id: string;
  /** Значение категории — оно же попадает в `?collapsed=`. */
  groupKey: string;
  label: string;
  count: number;
  totalPrice: number | null;
  collapsed: boolean;
};

export type FlatRow = { kind: "row"; id: string; groupKey: string; tender: Tender };

export type FlatItem = FlatHeader | FlatRow;

/** Значение ключа группировки у строки. Пустое — «без категории». */
export function groupValue(tender: Tender, field: string): string {
  if (field === "okpd") return tender.okpd2_code ?? "";
  if (field === "customer") return tender.customer_name ?? "";
  if (field === "region") return tender.region_code ?? "";
  return "";
}

/**
 * Плоский список «шапка / строка» для одного виртуализатора.
 *
 * Вложенные виртуализаторы здесь не годятся: у каждого свой скроллер и своя
 * оценка высоты, а группа может быть длиннее экрана. Один список с разной
 * высотой по индексу — и прокрутка остаётся одна.
 *
 * Порядок строк не меняется: он пришёл с сервера, где ключ группы стоит
 * первым в сортировке. Здесь только расставляются шапки на смене ключа —
 * это не перегруппировка страницы, а разметка уже готового порядка.
 */
export function flattenGroups(
  items: readonly Tender[],
  field: string,
  buckets: readonly GroupBucket[],
  collapsed: ReadonlySet<string>,
): FlatItem[] {
  const byKey = new Map(buckets.map((bucket) => [bucket.key, bucket]));
  const flat: FlatItem[] = [];

  let current: string | null = null;
  let isCollapsed = false;

  for (const tender of items) {
    const key = groupValue(tender, field);

    if (key !== current) {
      current = key;
      const id = `${field}:${key}`;
      isCollapsed = collapsed.has(id);

      const bucket = byKey.get(key);
      flat.push({
        kind: "header",
        id,
        groupKey: key,
        label: bucket?.label || key || "",
        // Счётчик и сумма — из оглавления, посчитанного по всей выдаче.
        // Пока оглавление не пришло, считать по загруженным строкам нельзя:
        // такое число выглядит достоверным и врёт.
        count: bucket?.count ?? 0,
        totalPrice: bucket?.total_price != null ? Number(bucket.total_price) : null,
        collapsed: isCollapsed,
      });
    }

    if (!isCollapsed) {
      flat.push({ kind: "row", id: tender.reg_num, groupKey: key, tender });
    }
  }

  return flat;
}

/** Высота по индексу: виртуализатору нужна оценка до отрисовки. */
export function estimateSize(items: readonly FlatItem[], index: number): number {
  return items[index]?.kind === "header" ? HEADER_HEIGHT : GROUP_ROW_HEIGHT;
}

/** Подпись группы для шапки: «ОКПД2 · 32.50.13». */
export function groupHeading(field: string, header: FlatHeader): string {
  const label = sortField(field)?.groupLabel ?? field;
  if (!header.groupKey) return `${label} · —`;
  return header.label && header.label !== header.groupKey
    ? `${header.groupKey} · ${header.label}`
    : header.groupKey;
}
