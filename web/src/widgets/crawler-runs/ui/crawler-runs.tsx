"use client";

import { useQuery } from "@tanstack/react-query";
import { Card } from "@/shared/ui/card";
import { Mono } from "@/shared/ui/mono";
import { Pill } from "@/shared/ui/pill";
import { Table, TBody, TD, TH, THead, TR } from "@/shared/ui/table";
import { TextSkeleton } from "@/shared/ui/skeleton";
import { EmptyState } from "@/shared/ui/empty-state";
import { endpoints } from "@/shared/api/endpoints";
import { STALE } from "@/shared/api/query-keys";
import type { CrawlerRuns } from "@/shared/api/types";
import { dateShort } from "@/shared/lib/format";

const TONE: Record<string, "moss" | "oak" | "signal" | "neutral"> = {
  success: "moss",
  running: "neutral",
  failed: "signal",
};

/**
 * Журнал выгрузок из ЕИС.
 *
 * Код отказа показывается рядом с текстом: по одному тексту не отличить
 * «организация заблокирована» (код 34, чинится в личном кабинете) от обрыва
 * сети, а чинятся они совершенно по-разному.
 */
export function CrawlerRunsTable() {
  const runs = useQuery<CrawlerRuns>({
    queryKey: ["monitoring", "crawler-runs"],
    queryFn: ({ signal }) => endpoints.crawlerRuns(60, signal),
    staleTime: STALE.health,
  });

  if (runs.isLoading) return <TextSkeleton lines={8} />;

  const items = runs.data?.items ?? [];
  if (!items.length) {
    return <EmptyState title="Выгрузок ещё не было" body="Краулер запускается по расписанию." />;
  }

  return (
    <Card padded={false}>
      <Table>
        <THead>
          <TR>
            <TH>Дата</TH>
            <TH>Статус</TH>
            <TH numeric>Получено</TH>
            <TH numeric>Сохранено</TH>
            <TH>Отказ</TH>
          </TR>
        </THead>
        <TBody>
          {items.map((run) => (
            <TR key={run.run_id}>
              <TD>
                <Mono>{run.target_date ?? "—"}</Mono>
              </TD>
              <TD>
                <Pill tone={TONE[run.status] ?? "neutral"} dot>
                  {run.status}
                </Pill>
              </TD>
              <TD numeric>{run.fetched}</TD>
              <TD numeric>{run.saved}</TD>
              <TD className="text-body-sm text-text-muted">
                {run.error_message ? (
                  <span title={run.error_message}>
                    {run.error_code !== null ? <Mono>код {run.error_code}</Mono> : null}{" "}
                    <span className="line-clamp-2">{run.error_message}</span>
                  </span>
                ) : (
                  <span className="text-text-subtle">{dateShort(run.started_at)}</span>
                )}
              </TD>
            </TR>
          ))}
        </TBody>
      </Table>
    </Card>
  );
}
