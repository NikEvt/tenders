"use client";

import { useQuery } from "@tanstack/react-query";
import { EmptyState } from "@/shared/ui/empty-state";
import { ErrorPanel } from "@/shared/ui/error-panel";
import { Mono } from "@/shared/ui/mono";
import { Pill } from "@/shared/ui/pill";
import { TextSkeleton } from "@/shared/ui/skeleton";
import { endpoints } from "@/shared/api/endpoints";
import { STALE } from "@/shared/api/query-keys";
import type { TenderEvents } from "@/shared/api/types";
import { dateLong } from "@/shared/lib/format";

const TONE: Record<string, "moss" | "oak" | "signal" | "neutral"> = {
  consumed: "moss",
  published: "neutral",
  pending: "neutral",
  retry: "oak",
  dead: "signal",
};

const LABEL: Record<string, string> = {
  consumed: "обработано",
  published: "отправлено",
  pending: "ожидает отправки",
  retry: "повтор",
  dead: "не доставлено",
};

/**
 * Событийный след закупки.
 *
 * Статус выводится из outbox и таблицы обработанных сообщений — отдельной
 * колонки статуса нет, и заводить её ради экрана значило бы дублировать то,
 * что уже следует из данных.
 */
export function EventsTab({ regNum }: { regNum: string }) {
  const events = useQuery<TenderEvents>({
    queryKey: ["tenders", regNum, "events"],
    queryFn: ({ signal }) => endpoints.tenderEvents(regNum, signal),
    staleTime: STALE.list,
  });

  if (events.isLoading) return <TextSkeleton lines={6} />;
  if (events.error) return <ErrorPanel error={events.error} reset={() => void events.refetch()} />;

  const items = events.data?.items ?? [];
  if (!items.length) {
    return (
      <EmptyState
        title="Событий нет"
        body="След появляется, когда закупку подхватывает обработка: загрузка документов, векторизация, фильтры."
      />
    );
  }

  return (
    <ol className="flex flex-col divide-y divide-hairline">
      {items.map((event) => (
        <li key={event.message_id} className="flex flex-wrap items-center gap-3 py-3">
          <Mono className="w-56 shrink-0">{event.event}</Mono>
          <Pill tone={TONE[event.status] ?? "neutral"} dot>
            {LABEL[event.status] ?? event.status}
          </Pill>
          {event.attempt > 0 ? (
            <span className="text-body-sm text-text-muted">
              попытка {event.attempt}
              {event.retry_stage ? ` · следующая через ${event.retry_stage}` : ""}
            </span>
          ) : null}
          <span className="ml-auto text-body-sm text-text-subtle">
            {dateLong(event.occurred_at)}
          </span>
          {event.error ? (
            <p role="alert" className="w-full text-body-sm text-signal-fg">
              {event.error}
            </p>
          ) : null}
        </li>
      ))}
    </ol>
  );
}
