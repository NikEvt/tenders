"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { Button } from "@/shared/ui/button";
import { Card } from "@/shared/ui/card";
import { Field, Input, Textarea } from "@/shared/ui/field";
import { Chip } from "@/shared/ui/chip";
import { Banner } from "@/shared/ui/banner";
import { Mono } from "@/shared/ui/mono";
import { PageHeader } from "@/shared/ui/section";
import { useToast } from "@/shared/ui/toast";
import { ru } from "@/shared/i18n/ru";
import { cn } from "@/shared/lib/cn";
import { money, regionName } from "@/shared/lib/format";
import { endpoints } from "@/shared/api/endpoints";
import type { FilterSpec } from "@/shared/api/types";
import { useCompileFilter } from "@/features/compile-filter/model/use-compile-filter";
import { compiledConditions } from "@/features/compile-filter/ui/compiled-chips";
import { FilterFunnel } from "@/features/test-filter/ui/funnel";

const EMPTY_SPEC: FilterSpec = {
  keywords: [],
  okpd2_prefixes: [],
  price_min: null,
  price_max: null,
  regions: [],
  customer_inns: [],
  date_range: null,
  only_active: true,
  semantic_query: "",
  llm_criteria: "",
};

/**
 * Конструктор фильтра: три панели в том порядке, в котором работает конвейер.
 * Дешёвый SQL → векторный отбор → дорогой судья. Порядок панелей и есть
 * объяснение, почему судья читает десятки документов, а не всю базу.
 */
export function FilterBuilder() {
  const router = useRouter();
  const toast = useToast();
  const compile = useCompileFilter();

  const [name, setName] = React.useState("");
  const [query, setQuery] = React.useState("");
  const [spec, setSpec] = React.useState<FilterSpec>(EMPTY_SPEC);
  const [edited, setEdited] = React.useState(false);

  const [savedId, setSavedId] = React.useState<number | null>(null);

  const save = useMutation({
    // Правленый spec уходит на сервер как есть: перекомпиляция текста откатила
    // бы снятый критерий, убранный регион и поправленный порог.
    mutationFn: () => endpoints.saveFilter(name.trim(), query.trim(), edited ? spec : undefined),
    onSuccess: (result) => {
      toast.show({ title: ru.filters.saved, tone: "moss" });
      setSavedId(result.filter_id);
    },
  });

  const patch = (next: FilterSpec) => {
    setSpec(next);
    setEdited(true);
  };

  const conditions = compiledConditions(spec);
  const structural = conditions.filter((c) => c.kind === "structural");

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={ru.filters.builderTitle} />

      <Card className="flex flex-col gap-3">
        <Field label={ru.filters.describe} htmlFor="describe">
          <Textarea
            id="describe"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={ru.filters.describePlaceholder}
            rows={2}
          />
        </Field>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="primary"
            loading={compile.isPending}
            disabled={query.trim().length < 3}
            onClick={() =>
              compile.mutate(query.trim(), {
                onSuccess: (result) => {
                  setSpec(result.spec);
                  setEdited(false);
                },
              })
            }
          >
            {ru.filters.compile}
          </Button>
          <Button
            variant="ghost"
            onClick={() => {
              setSpec(EMPTY_SPEC);
              setQuery("");
              setEdited(false);
            }}
          >
            {ru.common.reset}
          </Button>
          {compile.isError ? (
            <p role="alert" className="text-body-sm text-signal-fg">
              {ru.errors.llmTimeout}
            </p>
          ) : null}
        </div>
      </Card>

      {edited ? (
        <Banner
          tone="moss"
          title={ru.filters.editsSaved}
          body={ru.filters.editsSavedWhy}
        />
      ) : null}

      <Panel
        step={1}
        title={ru.filters.stepStructural}
        hint={ru.filters.stepStructuralHint}
      >
        {structural.length === 0 ? (
          <p className="text-body-sm text-text-subtle">{ru.filters.noConditions}</p>
        ) : (
          <ul className="flex flex-wrap gap-1.5">
            {structural.map((condition) => (
              <li key={condition.id}>
                <Chip kind="structural" onRemove={() => patch(condition.remove(spec))}>
                  {condition.label}
                </Chip>
              </li>
            ))}
          </ul>
        )}

        <details className="mt-4">
          <summary className="cursor-pointer text-body-sm text-gos-fg">
            {ru.filters.sqlPreview}
          </summary>
          <Mono className="mt-2 block whitespace-pre-wrap rounded-[6px] bg-surface-sunken p-3 text-text">
            {sqlPreview(spec)}
          </Mono>
        </details>
      </Panel>

      <Panel step={2} title={ru.filters.stepSemantic} hint={ru.filters.semanticHint}>
        <Textarea
          value={spec.semantic_query}
          onChange={(event) => patch({ ...spec, semantic_query: event.target.value })}
          placeholder={ru.filters.semanticPlaceholder}
          rows={2}
        />
      </Panel>

      <Panel
        step={3}
        title={ru.filters.stepJudge}
        hint={ru.filters.judgeCost(40, 2)}
        vellum
      >
        <Textarea
          value={spec.llm_criteria}
          onChange={(event) => patch({ ...spec, llm_criteria: event.target.value })}
          placeholder={ru.filters.judgePlaceholder}
          rows={2}
          className="bg-transparent"
        />
      </Panel>

      <FilterFunnel filterId={savedId} />

      <Card className="flex flex-wrap items-end gap-3">
        <Field label={ru.filters.name} htmlFor="filter-name" className="min-w-64 flex-1">
          <Input
            id="filter-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder={ru.filters.namePlaceholder}
          />
        </Field>
        <Button
          variant="primary"
          loading={save.isPending}
          disabled={!name.trim() || query.trim().length < 3}
          onClick={() => save.mutate()}
        >
          {ru.filters.saveFilter}
        </Button>
        {savedId !== null ? (
          <Button variant="secondary" onClick={() => router.push(`/tenders?filter_id=${savedId}`)}>
            Открыть выдачу
          </Button>
        ) : null}
      </Card>
    </div>
  );
}

function Panel({
  step,
  title,
  hint,
  vellum,
  children,
}: {
  step: number;
  title: string;
  hint: string;
  vellum?: boolean;
  children: React.ReactNode;
}) {
  return (
    <section
      className={cn(
        "relative rounded-[10px] border p-6",
        vellum ? "border-vellum-edge surface-vellum pl-[27px]" : "border-hairline bg-surface",
      )}
    >
      {vellum ? (
        <span className="absolute left-0 top-0 h-full w-[3px] bg-oak-fg" aria-hidden="true" />
      ) : null}
      {/* Нумерация здесь настоящая: это порядок работы конвейера. */}
      <h2 className="flex items-baseline gap-2 text-h3">
        <span className="font-mono text-mono tnum text-text-subtle">{step}</span>
        {title}
      </h2>
      <p className="mb-3 mt-1 text-body-sm text-text-muted">{hint}</p>
      {children}
    </section>
  );
}

/** Читаемый эквивалент структурных условий. Только предпросмотр, не исполняется. */
function sqlPreview(spec: FilterSpec): string {
  const where: string[] = [];

  if (spec.keywords?.length) {
    where.push(`search_vector @@ plainto_tsquery('russian', '${spec.keywords.join(" ")}')`);
  }
  for (const prefix of spec.okpd2_prefixes ?? []) {
    where.push(`okpd2_code LIKE '${prefix}%'`);
  }
  if (spec.regions?.length) {
    where.push(`region_code IN (${spec.regions.map((r) => `'${r}'`).join(", ")})  -- ${spec.regions.map(regionName).join(", ")}`);
  }
  for (const inn of spec.customer_inns ?? []) {
    where.push(`customer_inn = '${inn}'`);
  }
  if (spec.price_min !== null && spec.price_min !== undefined) {
    where.push(`price >= ${spec.price_min}  -- ${money(spec.price_min)}`);
  }
  if (spec.price_max !== null && spec.price_max !== undefined) {
    where.push(`price <= ${spec.price_max}  -- ${money(spec.price_max)}`);
  }
  if (spec.only_active) where.push("end_date > now()");

  return `SELECT * FROM tenders\nWHERE ${where.length ? where.join("\n  AND ") : "true"}`;
}
