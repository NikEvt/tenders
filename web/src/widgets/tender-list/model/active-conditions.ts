import { ru } from "@/shared/i18n/ru";
import { compactMoney, dateShort, regionName } from "@/shared/lib/format";
import type { CatalogParams } from "./use-catalog-params";

export type ActiveCondition = {
  id: string;
  label: string;
  /** Что записать в параметры, чтобы условие исчезло. */
  clear: Partial<CatalogParams>;
};

/** Каждое применённое условие — снимаемый чип. Скрытых условий не бывает. */
export function activeConditions(params: CatalogParams): ActiveCondition[] {
  const items: ActiveCondition[] = [];

  if (params.q) {
    items.push({ id: "q", label: `«${params.q}»`, clear: { q: "", page: 0 } });
  }
  for (const region of params.region) {
    items.push({
      id: `region:${region}`,
      label: regionName(region),
      clear: { region: params.region.filter((r) => r !== region), page: 0 },
    });
  }
  if (params.okpd2) {
    items.push({
      id: "okpd2",
      label: `${ru.tender.okpd2} ${params.okpd2}`,
      clear: { okpd2: "", page: 0 },
    });
  }
  if (params.customer_inn) {
    items.push({
      id: "customer_inn",
      label: `${ru.tender.inn} ${params.customer_inn}`,
      clear: { customer_inn: "", page: 0 },
    });
  }
  if (params.price_min !== null) {
    items.push({
      id: "price_min",
      label: `${ru.catalog.facets.price} ${ru.catalog.facets.from} ${compactMoney(params.price_min)}`,
      clear: { price_min: null, page: 0 },
    });
  }
  if (params.price_max !== null) {
    items.push({
      id: "price_max",
      label: `${ru.catalog.facets.price} ${ru.catalog.facets.to} ${compactMoney(params.price_max)}`,
      clear: { price_max: null, page: 0 },
    });
  }
  if (params.since) {
    items.push({
      id: "since",
      label: `${ru.tender.published} ${ru.catalog.facets.from} ${dateShort(params.since)}`,
      clear: { since: "", page: 0 },
    });
  }
  if (params.until) {
    items.push({
      id: "until",
      label: `${ru.tender.published} ${ru.catalog.facets.to} ${dateShort(params.until)}`,
      clear: { until: "", page: 0 },
    });
  }
  if (params.only_active) {
    items.push({
      id: "only_active",
      label: ru.catalog.facets.onlyActive,
      clear: { only_active: false, page: 0 },
    });
  }
  if (params.deadline_changed) {
    items.push({
      id: "deadline_changed",
      label: ru.catalog.facets.deadlineChanged,
      clear: { deadline_changed: false, page: 0 },
    });
  }
  if (params.has_text) {
    items.push({
      id: "has_text",
      label: ru.catalog.facets.hasText,
      clear: { has_text: false, page: 0 },
    });
  }
  if (params.filter_id !== null) {
    items.push({
      id: "filter_id",
      label: `${ru.nav.filters}: #${params.filter_id}`,
      clear: { filter_id: null, page: 0 },
    });
  }

  return items;
}
