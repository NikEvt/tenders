"use client";

import { Button } from "@/shared/ui/button";
import { Progress } from "@/shared/ui/progress";
import { ru } from "@/shared/i18n/ru";
import { cn } from "@/shared/lib/cn";
import { formatCount } from "@/shared/lib/plural";
import { duration } from "@/shared/api/job-progress";
import { useProgress } from "@/shared/api/use-progress";
import type { Job } from "@/shared/api/types";

/**
 * Ожидание долгой операции — на месте будущего результата, а не в тосте.
 * Ошибка тоже остаётся здесь: пользователь смотрит именно сюда.
 *
 * Раньше здесь стоял волчок и приписка «· 42 %». Ни фазы, ни счётчика, ни
 * времени — то есть на вопрос «чего я жду и сколько ещё» ответа не было, а при
 * неизвестном объёме работы не было и процента: экран показывал бесконечное
 * вращение и ничего больше.
 */
export function PendingBlock({
  title,
  job,
  error,
  onRetry,
  className,
}: {
  title: string;
  job?: Job;
  error?: string | null;
  onRetry?: () => void;
  className?: string;
}) {
  const progress = useProgress(job);
  const failed = error ?? (job?.status === "failed" ? (job.error ?? ru.errors.title) : null);

  if (failed) {
    return (
      <div
        role="alert"
        className={cn(
          "flex flex-wrap items-center gap-3 rounded-[10px] border border-signal-fg/30 surface-signal-tint px-4 py-3",
          className,
        )}
      >
        <p className="min-w-0 flex-1 text-body-sm text-text">{failed}</p>
        {onRetry ? (
          <Button size="sm" variant="secondary" onClick={onRetry}>
            {ru.common.retry}
          </Button>
        ) : null}
      </div>
    );
  }

  return (
    <div
      aria-live="polite"
      className={cn(
        "flex flex-col gap-2 rounded-[10px] border border-hairline bg-surface-sunken px-4 py-3",
        className,
      )}
    >
      <p className="text-body-sm text-text">{title}</p>
      {/* Фаза стоит отдельной строкой и мельче названия операции: это не то,
          что запустили, а то, что происходит прямо сейчас. */}
      {progress?.phase ? (
        <p className="text-caption text-text-muted">{progress.phase}</p>
      ) : null}

      <Progress value={progress?.share} label={scaleLabel(progress)} />

      <p className="flex flex-wrap items-baseline gap-x-3 text-caption text-text-subtle">
        <span className="tnum">{countLabel(progress)}</span>
        {progress ? (
          <span className="tnum">{ru.waiting.elapsed(duration(progress.elapsedMs))}</span>
        ) : null}
        {/* Оценка появляется только тогда, когда её есть из чего сложить:
            десятая доля работы и десять секунд времени. Раньше — гадание по
            двум точкам, дающее «осталось четыре часа» на ровном месте. */}
        {progress?.remainingMs ? (
          <span className="tnum">{ru.waiting.remaining(duration(progress.remainingMs))}</span>
        ) : null}
      </p>
    </div>
  );
}

type Progress = ReturnType<typeof useProgress>;

/** Текстовая версия шкалы. Уходит в `aria-valuetext`, поэтому словами. */
function scaleLabel(progress: Progress): string {
  if (!progress || progress.total === null) return ru.waiting.scaleUnknown;
  return ru.waiting.scale(formatCount(progress.processed), formatCount(progress.total));
}

/** Счётчик всегда со знаменателем — или честное «знаменателя ещё нет». */
function countLabel(progress: Progress): string {
  if (!progress || progress.total === null) return ru.waiting.counting;
  return ru.waiting.done(formatCount(progress.processed), formatCount(progress.total));
}
