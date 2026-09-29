"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { endpoints } from "@/shared/api/endpoints";
import { STALE } from "@/shared/api/query-keys";
import type { CorpusProcessing } from "@/shared/api/types";
import { ru } from "@/shared/i18n/ru";
import { timeOnly } from "@/shared/lib/format";
import { formatCount } from "@/shared/lib/plural";
import { Card } from "@/shared/ui/card";
import { Progress } from "@/shared/ui/progress";
import { SectionHeading } from "@/shared/ui/section";
import { TextSkeleton } from "@/shared/ui/skeleton";

/** Как часто спрашиваем. Обработка идёт непрерывно, состав корпуса — нет. */
const POLL_MS = 15_000;

/**
 * Что происходит с корпусом прямо сейчас: векторизация и сегодняшняя выгрузка.
 *
 * Опрашивается часто и потому вынесено в отдельный запрос: считать групповые
 * разрезы по всей таблице каждые пятнадцать секунд незачем.
 */
export function ProcessingPanel() {
  const state = useQuery<CorpusProcessing>({
    queryKey: ["data", "processing"],
    queryFn: ({ signal }) => endpoints.corpusProcessing(signal),
    staleTime: STALE.health,
    // Опрос замирает вместе с вкладкой: пятнадцатисекундные запросы из фонового
    // окна — это нагрузка на ту же машину, чей уровень пользователь и настраивает.
    refetchInterval: POLL_MS,
    refetchIntervalInBackground: false,
  });

  if (state.isLoading) return <TextSkeleton lines={6} />;
  if (!state.data) return null;

  const { embeddings, today } = state.data;

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card className="flex flex-col gap-4">
        <SectionHeading title={ru.data.processing} />

        <Share
          title={ru.data.embeddingChunks}
          done={embeddings.chunks_embedded}
          total={embeddings.chunks_total}
          note={
            embeddings.queue_depth === null
              ? ru.data.queueUnknown
              : ru.data.queueDepth(formatCount(embeddings.queue_depth))
          }
        />

        <Share
          title={ru.data.embeddingTenders}
          done={embeddings.tenders_embedded}
          total={embeddings.tenders_total}
        />

        <p className="text-caption text-text-subtle">
          {ru.data.documents(
            formatCount(state.data.documents_downloaded),
            formatCount(state.data.documents_extracted),
          )}{" "}
          ·{" "}
          <Link href="/monitoring/documents" className="text-gos-fg hover:underline">
            {ru.data.moreInMonitoring}
          </Link>
        </p>
      </Card>

      <Card className="flex flex-col gap-3">
        <SectionHeading title={ru.data.today} />

        {today.runs_succeeded + today.runs_failed + today.runs_running === 0 ? (
          <p className="text-body-sm text-text-muted">{ru.data.todayNoRuns}</p>
        ) : (
          <>
            <p className="text-body-sm tnum text-text">
              {ru.data.todayRuns(
                formatCount(today.runs_succeeded),
                formatCount(today.runs_failed),
                formatCount(today.runs_running),
              )}
            </p>
            <p className="text-body-sm tnum text-text-muted">
              {ru.data.todaySaved(formatCount(today.saved))}
              {today.last_run_at ? ` · ${ru.data.lastRun(timeOnly(today.last_run_at))}` : ""}
            </p>
          </>
        )}

        <p className="text-body-sm tnum text-text-muted">
          {ru.data.todayPublished(formatCount(today.published_today))}
        </p>

        {/* Правило домена, а не оговорка: суточный архив ЕИС дописывается до
            полуночи, поэтому «выгружено 42 из 42» не означает «за сегодня всё».
            Сервер сообщает это полем `final`, клиент его не выводит сам. */}
        {!today.final ? (
          <p className="text-caption text-text-subtle">{ru.data.todayNotFinal}</p>
        ) : null}
      </Card>
    </div>
  );
}

/**
 * Доля со знаменателем.
 *
 * При нулевом знаменателе шкала неопределённая и процента нет: «0 %» на пустом
 * корпусе — выдуманное число, а не факт о работе.
 */
function Share({
  title,
  done,
  total,
  note,
}: {
  title: string;
  done: number;
  total: number;
  note?: string;
}) {
  const label = total > 0 ? ru.data.embeddingOf(formatCount(done), formatCount(total)) : ru.data.noChunks;

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-body-sm text-text">{title}</span>
        <span className="text-caption tnum text-text-muted">{label}</span>
      </div>
      <Progress value={total > 0 ? done / total : undefined} label={label} />
      {note ? <span className="text-caption tnum text-text-subtle">{note}</span> : null}
    </div>
  );
}
