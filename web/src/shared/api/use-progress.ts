"use client";

import * as React from "react";
import { useElapsed } from "@/shared/lib/hooks";
import { readProgress, type Progress } from "./job-progress";
import type { Job } from "./types";

/**
 * Ход задания, пересчитываемый по часам, а не только по ответам сервера.
 *
 * **Начало фазы отсчитывается здесь.** Сервер сообщает, какая фаза идёт, но не
 * когда она началась, а оценка остатка обязана считаться по текущей фазе:
 * темп обхода корпуса не переносится на работу судьи.
 *
 * Смену фазы мы видим и запоминаем точно. А вот при первом появлении на экране
 * не знаем ничего, кроме старта задания, — и берём его: для первой фазы это в
 * точности верно, а для второй завышает прошедшее время, то есть **завышает и
 * остаток**. Ошибаться в эту сторону не обидно; обратная ошибка — «осталось
 * полминуты» на десятиминутной работе — обидна.
 */
export function useProgress(job: Job | undefined): Progress | null {
  const phase = job?.phase ?? null;
  const phaseStartedAt = React.useRef<number | undefined>(undefined);
  const seenPhase = React.useRef<string | null>(phase);

  if (seenPhase.current !== phase) {
    seenPhase.current = phase;
    phaseStartedAt.current = Date.now();
  }

  const startedAt = job ? Date.parse(job.created_at) : null;
  const elapsed = useElapsed(startedAt, Boolean(job) && !isTerminal(job));

  return readProgress(job, {
    now: (startedAt ?? 0) + elapsed,
    phaseStartedAt: phaseStartedAt.current,
  });
}

function isTerminal(job: Job | undefined): boolean {
  return job ? ["done", "failed", "cancelled"].includes(job.status) : false;
}
