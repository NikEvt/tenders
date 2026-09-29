import type { CriteriaSpec } from "@/shared/api/types";
import type { CatalogParams } from "./use-catalog-params";

/**
 * Критерий отбора → параметры каталога.
 *
 * Переносится только то, что каталог умеет: структурные условия и один префикс
 * ОКПД2. Термины и правила по контексту параметрами выборки не выражаются —
 * они работают по тексту документов, а каталог ищет по карточке. Поэтому в
 * `q` уходят имена терминов: это грубее настоящего отбора, зато честно
 * показывает, где искать, пока критерий не сохранён и не прогнан.
 *
 * Потери не замалчиваются: `unappliedConditions` возвращает всё, что каталог
 * применить не смог, и интерфейс показывает это списком.
 */
export function specToParams(spec: CriteriaSpec): Partial<CatalogParams> {
  const structural = spec.structural;
  return {
    q: spec.terms
      .filter((term) => term.role === "primary")
      .map((term) => term.name)
      .join(" ")
      .trim(),
    region: structural?.regions ?? [],
    okpd2: spec.okpd2_prefixes?.[0] ?? "",
    customer_inn: structural?.customer_inns?.[0] ?? "",
    price_min: toNumberOrNull(structural?.price_min),
    price_max: toNumberOrNull(structural?.price_max),
    since: "",
    until: "",
    only_active: Boolean(structural?.only_active),
    page: 0,
  };
}

/** Условия, которые каталог применить не может — их показывают отдельно. */
export function unappliedConditions(spec: CriteriaSpec): string[] {
  const extra: string[] = [];

  if ((spec.okpd2_prefixes?.length ?? 0) > 1) {
    extra.push(...spec.okpd2_prefixes.slice(1).map((code) => `ОКПД2 ${code}`));
  }
  if ((spec.structural?.customer_inns?.length ?? 0) > 1) {
    extra.push(...spec.structural.customer_inns.slice(1).map((inn) => `ИНН ${inn}`));
  }
  // Главное, чего каталог не умеет: он ищет по карточке, а термины и правила
  // работают по тексту документов.
  if (spec.context_rules.length > 0) {
    extra.push(`правил по контексту: ${spec.context_rules.length}`);
  }
  const supporting = spec.terms.filter((term) => term.role === "supporting");
  if (supporting.length > 0) {
    extra.push(...supporting.map((term) => `вспомогательный «${term.name}»`));
  }
  return extra;
}

function toNumberOrNull(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}
