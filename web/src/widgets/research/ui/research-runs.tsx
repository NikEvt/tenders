"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Card } from "@/shared/ui/card";
import { EmptyState } from "@/shared/ui/empty-state";
import { TextSkeleton } from "@/shared/ui/skeleton";
import { Pill } from "@/shared/ui/pill";
import { endpoints } from "@/shared/api/endpoints";
import type { ResearchRun } from "@/shared/api/types";
import { ru } from "@/shared/i18n/ru";
import { dateLong } from "@/shared/lib/format";
import { formatCount } from "@/shared/lib/plural";
import { regionName } from "@/shared/lib/format";

/**
 * Список прогонов.
 *
 * У каждого — воронка одной строкой. Числа поданы в том же порядке, что и на
 * странице прогона: подтверждено / отклонено / спорно, и рядом «не прочитано».
 * Последнее не украшение: прогон, где непрочитанным остался весь корпус, и
 * прогон, где не нашлось ничего, — разные вещи, и по списку это должно быть
 * видно сразу.
 */
export function ResearchRuns() {
  const runs = useQuery<ResearchRun[]>({
    queryKey: ["research", "runs"],
    queryFn: ({ signal }) => endpoints.researchRuns(50, signal),
    // Пока хоть один прогон идёт — список живой.
    refetchInterval: (query) =>
      query.state.data?.some((r) => r.status === "running") ? 5000 : false,
  });

  if (runs.isLoading) return <TextSkeleton lines={6} />;
  if (!runs.data?.length) {
    return <EmptyState title={ru.research.empty} body={ru.research.emptyBody} />;
  }

  return (
    <ul className="flex flex-col gap-3">
      {runs.data.map((run) => (
        <li key={run.run_id}>
          <Card className="flex flex-col gap-3">
            <div className="flex flex-wrap items-baseline justify-between gap-3">
              <Link
                href={`/research/${run.run_id}`}
                className="text-h3 hover:underline"
              >
                {run.name}
              </Link>
              <StatusPill status={run.status} />
            </div>

            <p className="text-body-sm text-text-muted">
              {run.regions.length ? run.regions.map(regionName).join(", ") : "все регионы"}
              {run.date_from ? ` · с ${run.date_from}` : ""}
              {run.date_to ? ` по ${run.date_to}` : ""}
              {run.started_at ? ` · ${dateLong(run.started_at)}` : ""}
            </p>

            <dl className="flex flex-wrap gap-x-6 gap-y-1 text-body-sm">
              <Metric label={ru.research.confirmed} value={run.confirmed} />
              <Metric label={ru.research.rejected} value={run.rejected} />
              <Metric label={ru.research.disputed} value={run.funnel.disputed} />
              {/* Знаменатель: без него число находок читается как исчерпывающее. */}
              <Metric
                label={ru.filters.funnelPending}
                value={run.funnel.documents_pending}
                muted
              />
            </dl>

            {run.error_message ? (
              <p role="alert" className="text-body-sm text-signal-fg">
                {run.error_message}
              </p>
            ) : null}
          </Card>
        </li>
      ))}
    </ul>
  );
}

function Metric({
  label,
  value,
  muted,
}: {
  label: string;
  value: number;
  muted?: boolean;
}) {
  return (
    <div className="flex items-baseline gap-1.5">
      <dt className={muted ? "text-text-subtle" : "text-text-muted"}>{label}</dt>
      <dd className={`tnum ${muted ? "text-text-subtle" : "text-text"}`}>
        {formatCount(value)}
      </dd>
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  if (status === "done") return <Pill tone="moss">{ru.research.done}</Pill>;
  if (status === "failed") return <Pill tone="signal">{ru.research.failed}</Pill>;
  return <Pill tone="oak">{ru.research.running}</Pill>;
}
