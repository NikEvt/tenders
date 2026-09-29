"use client";

import { useQuery } from "@tanstack/react-query";
import { parseAsInteger, useQueryState } from "nuqs";

import { endpoints } from "@/shared/api/endpoints";
import { STALE } from "@/shared/api/query-keys";
import type { CorpusOverview } from "@/shared/api/types";
import { ru } from "@/shared/i18n/ru";
import { dateShort } from "@/shared/lib/format";
import { formatCount } from "@/shared/lib/plural";
import { Card } from "@/shared/ui/card";
import { EmptyState } from "@/shared/ui/empty-state";
import { PageHeader, SectionHeading } from "@/shared/ui/section";
import { Segmented } from "@/shared/ui/segmented";
import { TextSkeleton } from "@/shared/ui/skeleton";
import { Database } from "lucide-react";

import { DateHistogram } from "./date-histogram";
import { ProcessingPanel } from "./processing";
import { TopList } from "./top-list";

const PERIODS = [
  { value: "30", label: ru.data.period30 },
  { value: "90", label: ru.data.period90 },
  { value: "365", label: ru.data.period365 },
];

const TOP = 12;

/**
 * Вкладка «Данные» — ответ на вопрос «с чем я работаю».
 *
 * На «что сломано» отвечает мониторинг, и числа оттуда сюда не переезжают:
 * воронка документов берётся тем же портом, а не считается заново. Две
 * реализации одного счётчика в этом проекте однажды уже разошлись.
 */
export function DataOverview() {
  const [days, setDays] = useQueryState("days", parseAsInteger.withDefault(90));

  const overview = useQuery<CorpusOverview>({
    queryKey: ["data", "overview", days],
    queryFn: ({ signal }) => endpoints.corpusOverview(days, TOP, signal),
    staleTime: STALE.detail,
  });

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={ru.data.title}
        meta={ru.data.subtitle}
        actions={
          <Segmented
            label={ru.data.period}
            value={String(days)}
            onChange={(value) => void setDays(Number(value))}
            options={PERIODS}
          />
        }
      />

      <ProcessingPanel />

      {overview.isLoading ? <TextSkeleton lines={8} /> : null}

      {overview.data ? <Corpus view={overview.data} /> : null}
    </div>
  );
}

function Corpus({ view }: { view: CorpusOverview }) {
  return (
    <div className="flex flex-col gap-6">
      <Card className="flex flex-col gap-4">
        <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
          <SectionHeading title={ru.data.byDate} />
          {/* Знаменатель периода: сколько корпуса вообще видно на экране.
              Без него «30 тыс. закупок» читается как весь корпус. */}
          <span className="text-body-sm tnum text-text-muted">
            {ru.data.inCorpus(formatCount(view.total), formatCount(view.total_all_time))}
          </span>
        </div>

        {view.total === 0 ? (
          <EmptyState
            icon={<Database strokeWidth={1.5} />}
            title={ru.data.emptyPeriod}
            body={ru.data.emptyPeriodHint}
          />
        ) : (
          <DateHistogram days={view.by_day} />
        )}

        <p className="text-caption text-text-subtle">
          {ru.data.periodNote(dateShort(view.since), dateShort(view.until))}
          {view.earliest && view.latest
            ? ` · ${ru.data.corpusSpan(dateShort(view.earliest), dateShort(view.latest))}`
            : ""}
        </p>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="flex flex-col gap-3">
          <SectionHeading title={ru.data.byRegion} />
          <TopList distribution={view.by_region} unknownLabel={ru.data.unknownRegion} />
        </Card>

        <Card className="flex flex-col gap-3">
          <SectionHeading title={ru.data.byOkpd2} />
          {/* Коды набираются моноширинным: это данные, а не слова (§2.5). */}
          <TopList distribution={view.by_okpd2} mono />
        </Card>
      </div>
    </div>
  );
}
