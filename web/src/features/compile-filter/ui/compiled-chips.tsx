"use client";

import { Chip } from "@/shared/ui/chip";
import { ru } from "@/shared/i18n/ru";
import { money, regionName } from "@/shared/lib/format";
import type { CriteriaSpec } from "@/shared/api/types";

export type CompiledCondition = {
  id: string;
  /**
   * Три части критерия, и порядок здесь тот же, в каком работает конвейер:
   * где искать → что искать → как отличить своё.
   */
  kind: "structural" | "term" | "rule";
  label: string;
  /** Что убрать из спецификации, если условие снимут. */
  remove: (spec: CriteriaSpec) => CriteriaSpec;
};

/**
 * Разбор запроса моделью, показанный целиком.
 *
 * Любую часть можно снять одним кликом — и тогда видно, что изменилось. Роль
 * термина показана прямо в подписи: вспомогательный сам по себе ничего не
 * значит, и скрывать это от пользователя нельзя, иначе снятие основного
 * термина выглядит безобидным.
 */
export function compiledConditions(spec: CriteriaSpec): CompiledCondition[] {
  const items: CompiledCondition[] = [];

  spec.terms?.forEach((term) => {
    items.push({
      id: `term:${term.name}`,
      kind: "term",
      label:
        term.role === "supporting"
          ? `${term.name} · ${ru.filters.roleSupporting}`
          : term.name,
      remove: (s) => ({ ...s, terms: s.terms.filter((t) => t.name !== term.name) }),
    });
  });

  spec.context_rules?.forEach((rule) => {
    items.push({
      id: `rule:${rule.name}`,
      kind: "rule",
      label:
        rule.verdict === "rejected"
          ? `${ru.filters.ruleAgainst}: ${rule.name}`
          : `${ru.filters.ruleFor}: ${rule.name}`,
      remove: (s) => ({
        ...s,
        context_rules: s.context_rules.filter((r) => r.name !== rule.name),
      }),
    });
  });

  spec.okpd2_prefixes?.forEach((code) => {
    items.push({
      id: `okpd:${code}`,
      kind: "structural",
      label: `ОКПД2 ${code}`,
      remove: (s) => ({
        ...s,
        okpd2_prefixes: s.okpd2_prefixes.filter((c) => c !== code),
      }),
    });
  });

  spec.structural?.regions?.forEach((region) => {
    items.push({
      id: `region:${region}`,
      kind: "structural",
      label: regionName(region),
      remove: (s) => ({
        ...s,
        structural: {
          ...s.structural,
          regions: s.structural.regions.filter((r) => r !== region),
        },
      }),
    });
  });

  spec.structural?.customer_inns?.forEach((inn) => {
    items.push({
      id: `inn:${inn}`,
      kind: "structural",
      label: `ИНН ${inn}`,
      remove: (s) => ({
        ...s,
        structural: {
          ...s.structural,
          customer_inns: s.structural.customer_inns.filter((i) => i !== inn),
        },
      }),
    });
  });

  if (spec.structural?.price_max) {
    items.push({
      id: "price_max",
      kind: "structural",
      label: `${ru.filters.priceUpTo} ${money(Number(spec.structural.price_max))}`,
      remove: (s) => ({ ...s, structural: { ...s.structural, price_max: null } }),
    });
  }

  if (spec.structural?.price_min) {
    items.push({
      id: "price_min",
      kind: "structural",
      label: `${ru.filters.priceFrom} ${money(Number(spec.structural.price_min))}`,
      remove: (s) => ({ ...s, structural: { ...s.structural, price_min: null } }),
    });
  }

  return items;
}

export function CompiledChips({
  spec,
  onChange,
}: {
  spec: CriteriaSpec;
  onChange: (spec: CriteriaSpec) => void;
}) {
  const items = compiledConditions(spec);
  if (items.length === 0) return null;

  return (
    <ul className="flex flex-wrap gap-1.5">
      {items.map((item) => (
        <li key={item.id}>
          <Chip kind={item.kind} onRemove={() => onChange(item.remove(spec))}>
            {item.label}
          </Chip>
        </li>
      ))}
    </ul>
  );
}
