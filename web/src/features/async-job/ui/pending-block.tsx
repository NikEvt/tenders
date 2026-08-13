"use client";

import { Button } from "@/shared/ui/button";
import { Spinner } from "@/shared/ui/spinner";
import { ru } from "@/shared/i18n/ru";
import { cn } from "@/shared/lib/cn";
import { percent } from "@/shared/lib/format";
import type { Job } from "@/shared/api/types";
import { jobProgress } from "@/shared/api/use-job";

/**
 * Ожидание долгой операции — на месте будущего результата, а не в тосте.
 * Ошибка тоже остаётся здесь: пользователь смотрит именно сюда.
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
  const progress = jobProgress(job);
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
        "flex items-center gap-3 rounded-[10px] border border-hairline bg-surface-sunken px-4 py-3",
        className,
      )}
    >
      <Spinner className="text-gos-fg" />
      <p className="min-w-0 flex-1 text-body-sm text-text-muted">
        {title}
        {progress !== null ? ` · ${percent(progress)}` : ""}
      </p>
    </div>
  );
}
