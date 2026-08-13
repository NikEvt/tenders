import type { FilterSpec } from "@/shared/api/types";
import type { CatalogParams } from "./use-catalog-params";

/**
 * Разобранный моделью фильтр → параметры каталога.
 *
 * Не всё переносится: `/tenders` принимает один префикс ОКПД2 и один ИНН, а
 * критерий для судьи вообще не параметр выборки — он работает только у
 * сохранённого фильтра, через `filter_id`. Обе потери видны в интерфейсе, а не
 * замолчаны: лишние префиксы остаются чипами, критерий подсвечен как
 * требующий сохранения.
 */
export function specToParams(spec: FilterSpec): Partial<CatalogParams> {
  const next: Partial<CatalogParams> = {
    q: [spec.semantic_query, ...(spec.keywords ?? [])].filter(Boolean).join(" ").trim(),
    region: spec.regions ?? [],
    okpd2: spec.okpd2_prefixes?.[0] ?? "",
    customer_inn: spec.customer_inns?.[0] ?? "",
    price_min: toNumberOrNull(spec.price_min),
    price_max: toNumberOrNull(spec.price_max),
    since: spec.date_range?.since ?? "",
    until: spec.date_range?.until ?? "",
    only_active: Boolean(spec.only_active),
    page: 0,
  };
  return next;
}

/** Условия, которые каталог применить не может — их показывают отдельно. */
export function unappliedConditions(spec: FilterSpec): string[] {
  const extra: string[] = [];
  if ((spec.okpd2_prefixes?.length ?? 0) > 1) {
    extra.push(...spec.okpd2_prefixes.slice(1).map((code) => `ОКПД2 ${code}`));
  }
  if ((spec.customer_inns?.length ?? 0) > 1) {
    extra.push(...spec.customer_inns.slice(1).map((inn) => `ИНН ${inn}`));
  }
  return extra;
}

function toNumberOrNull(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}
