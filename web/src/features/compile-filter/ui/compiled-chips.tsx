"use client";

import { Chip } from "@/shared/ui/chip";
import { ru } from "@/shared/i18n/ru";
import { money, regionName } from "@/shared/lib/format";
import type { FilterSpec } from "@/shared/api/types";

export type CompiledCondition = {
  id: string;
  kind: "structural" | "semantic" | "llm";
  label: string;
  /** Что убрать из спецификации, если условие снимут. */
  remove: (spec: FilterSpec) => FilterSpec;
};

/**
 * Разбор запроса моделью, показанный целиком: структурные условия — синим,
 * семантический запрос — в кавычках, критерий для судьи — на бумаге.
 * Любую часть можно снять одним кликом, и тогда видно, что изменилось.
 */
export function compiledConditions(spec: FilterSpec): CompiledCondition[] {
  const items: CompiledCondition[] = [];

  spec.keywords?.forEach((keyword) => {
    items.push({
      id: `kw:${keyword}`,
      kind: "structural",
      label: keyword,
      remove: (s) => ({ ...s, keywords: s.keywords.filter((k) => k !== keyword) }),
    });
  });

  spec.okpd2_prefixes?.forEach((code) => {
    items.push({
      id: `okpd2:${code}`,
      kind: "structural",
      label: `${ru.tender.okpd2} ${code}`,
      remove: (s) => ({ ...s, okpd2_prefixes: s.okpd2_prefixes.filter((c) => c !== code) }),
    });
  });

  spec.regions?.forEach((region) => {
    items.push({
      id: `region:${region}`,
      kind: "structural",
      label: regionName(region),
      remove: (s) => ({ ...s, regions: s.regions.filter((r) => r !== region) }),
    });
  });

  spec.customer_inns?.forEach((inn) => {
    items.push({
      id: `inn:${inn}`,
      kind: "structural",
      label: `${ru.tender.inn} ${inn}`,
      remove: (s) => ({ ...s, customer_inns: s.customer_inns.filter((i) => i !== inn) }),
    });
  });

  if (spec.price_min !== null && spec.price_min !== undefined) {
    items.push({
      id: "price_min",
      kind: "structural",
      label: `${ru.catalog.facets.price} ${ru.catalog.facets.from} ${money(spec.price_min)}`,
      remove: (s) => ({ ...s, price_min: null }),
    });
  }

  if (spec.price_max !== null && spec.price_max !== undefined) {
    items.push({
      id: "price_max",
      kind: "structural",
      label: `${ru.catalog.facets.price} ${ru.catalog.facets.to} ${money(spec.price_max)}`,
      remove: (s) => ({ ...s, price_max: null }),
    });
  }

  if (spec.only_active) {
    items.push({
      id: "only_active",
      kind: "structural",
      label: ru.catalog.facets.onlyActive,
      remove: (s) => ({ ...s, only_active: false }),
    });
  }

  if (spec.semantic_query?.trim()) {
    items.push({
      id: "semantic",
      kind: "semantic",
      label: `«${spec.semantic_query}»`,
      remove: (s) => ({ ...s, semantic_query: "" }),
    });
  }

  if (spec.llm_criteria?.trim()) {
    items.push({
      id: "llm",
      kind: "llm",
      label: spec.llm_criteria,
      remove: (s) => ({ ...s, llm_criteria: "" }),
    });
  }

  return items;
}

export function CompiledChips({
  spec,
  onChange,
  className,
}: {
  spec: FilterSpec;
  onChange: (spec: FilterSpec) => void;
  className?: string;
}) {
  const conditions = compiledConditions(spec);
  if (conditions.length === 0) return null;

  return (
    <ul className={className}>
      {conditions.map((condition) => (
        <li key={condition.id} className="inline-block max-w-full">
          <Chip
            kind={condition.kind}
            title={condition.label}
            onRemove={() => onChange(condition.remove(spec))}
          >
            {condition.label}
          </Chip>
        </li>
      ))}
    </ul>
  );
}
