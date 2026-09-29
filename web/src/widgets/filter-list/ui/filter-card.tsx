"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/shared/ui/button";
import { Card } from "@/shared/ui/card";
import { DefinitionList } from "@/shared/ui/definition-list";
import { ErrorPanel } from "@/shared/ui/error-panel";
import { PageHeader } from "@/shared/ui/section";
import { TextSkeleton } from "@/shared/ui/skeleton";
import { endpoints } from "@/shared/api/endpoints";
import { qk } from "@/shared/api/query-keys";
import type { Filter, CriteriaSpec } from "@/shared/api/types";
import { ru } from "@/shared/i18n/ru";
import { dateLong } from "@/shared/lib/format";
import { compiledConditions } from "@/features/compile-filter/ui/compiled-chips";
import { Chip } from "@/shared/ui/chip";
import { FilterFunnel } from "@/features/test-filter/ui/funnel";
import { RunResearchForm } from "@/features/run-research/ui/run-research-form";

/** Карточка сохранённого фильтра: что он ищет, когда работал, как проверить. */
export function FilterCard({ filterId }: { filterId: number }) {
  const filter = useQuery<Filter>({
    queryKey: qk.filters.byId(filterId),
    queryFn: ({ signal }) => endpoints.getFilter(filterId, signal),
  });

  if (filter.isLoading) return <TextSkeleton lines={10} />;
  if (filter.error) {
    return <ErrorPanel error={filter.error} reset={() => void filter.refetch()} />;
  }
  if (!filter.data) return null;

  const data = filter.data;
  const spec = data.spec as unknown as CriteriaSpec;
  const conditions = compiledConditions(spec);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={data.name}
        meta={data.query || undefined}
        actions={
          <Button asChild variant="secondary">
            <Link href={`/tenders?filter_id=${data.filter_id}`}>Открыть выдачу</Link>
          </Button>
        }
      />

      <Card className="flex flex-col gap-4">
        <h2 className="text-h3">{ru.filters.stepWhat}</h2>
        {conditions.length ? (
          <div className="flex flex-wrap gap-2">
            {conditions.map((condition) => (
              <Chip key={condition.id}>{condition.label}</Chip>
            ))}
          </div>
        ) : (
          <p className="text-body-sm text-text-muted">{ru.filters.noConditions}</p>
        )}

        <DefinitionList
          items={[
            {
              label: ru.filters.stepTell,
              // Правил может не быть: тогда всё спорное уйдёт судье. Это
              // законное состояние, но дорогое — и сказать об этом надо.
              value: spec.context_rules?.length
                ? `${spec.context_rules.length}`
                : "—",
            },
            {
              label: ru.filters.stepWhere,
              value: spec.card_pattern || "—",
            },
            {
              label: ru.filters.lastRun,
              value: data.last_run_at ? dateLong(data.last_run_at) : "не запускался",
            },
            { label: "Создан", value: dateLong(data.created_at) },
            {
              label: ru.filters.matches7d,
              value: String(
                data.match_counts.reduce((sum, c) => sum + c.count, 0),
              ),
            },
            { label: ru.filters.inDigest, value: data.in_digest ? "да" : "нет" },
            { label: ru.filters.notify, value: data.notify ? "да" : "нет" },
            { label: "Идентификатор", value: String(data.filter_id), mono: true },
          ]}
        />
      </Card>

      <FilterFunnel filterId={data.filter_id} />

      {/* Тест рядом с настоящим прогоном: «работает ли критерий» и «прогнать
          по этому охвату» — соседние намерения. */}
      <RunResearchForm filterId={data.filter_id} />
    </div>
  );
}
