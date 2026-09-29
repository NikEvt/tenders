"use client";

import * as React from "react";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { Loader } from "lucide-react";

import { ApiError } from "@/shared/api/client";
import { jobRegistry, useTrackedJobs, type TrackedJob } from "@/shared/api/job-registry";
import { duration } from "@/shared/api/job-progress";
import { useJob } from "@/shared/api/use-job";
import { useProgress } from "@/shared/api/use-progress";
import { ru } from "@/shared/i18n/ru";
import { formatCount } from "@/shared/lib/plural";
import { Button } from "@/shared/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/shared/ui/popover";
import { Progress } from "@/shared/ui/progress";
import { useToast } from "@/shared/ui/toast";

/**
 * Указатель идущих операций в верхней панели.
 *
 * Единственное место, где опрашиваются задания из реестра: опрос обязан быть
 * привязан к каркасу, а не к странице, — иначе он снова умрёт вместе с
 * виджетом, который операцию запустил.
 *
 * Виден, только когда что-то идёт. Пустая полоса «операций нет» была бы
 * постоянным напоминанием ни о чём.
 */
export function RunningJobs() {
  const tracked = useTrackedJobs();

  React.useEffect(() => {
    jobRegistry.hydrate();
  }, []);

  if (tracked.length === 0) return null;

  return (
    <>
      {/* Опрос живёт здесь, а не внутри поповера. Поповер Radix монтирует
          содержимое только открытым — держи опрос в нём, и закрытый указатель
          не опрашивал бы ничего: счётчик застыл бы навсегда, а задание,
          которого больше нет на сервере, не выселилось бы никогда. */}
      {tracked.map((job) => (
        <JobWatcher key={job.jobId} job={job} />
      ))}

      <Popover>
        <PopoverTrigger asChild>
          <Button variant="ghost" size="sm" aria-label={ru.waiting.runningTitle}>
            <Loader className="h-4 w-4 animate-spin" strokeWidth={1.5} aria-hidden="true" />
            <span className="tnum">{ru.waiting.runningCount(tracked.length)}</span>
          </Button>
        </PopoverTrigger>

        <PopoverContent align="end" className="w-[360px]">
          <h2 className="mb-3 text-h3">{ru.waiting.runningTitle}</h2>
          <ul className="flex flex-col gap-4">
            {tracked.map((job) => (
              <li key={job.jobId}>
                <TrackedRow job={job} />
              </li>
            ))}
          </ul>
        </PopoverContent>
      </Popover>
    </>
  );
}

/**
 * Опрос одной операции. Ничего не рисует.
 *
 * Компонент на задание, потому что `useJob` — хук: перебрать реестр циклом
 * внутри одного компонента нельзя, а общего запроса «состояние всех заданий»
 * сервер не отдаёт.
 */
function JobWatcher({ job }: { job: TrackedJob }) {
  const query = useJob(job.jobId);
  const toast = useToast();
  const client = useQueryClient();

  const status = query.data?.status;
  const missing = query.error instanceof ApiError && query.error.status === 404;

  React.useEffect(() => {
    // Задания, о котором сервер не знает, в реестре быть не должно: реестр
    // переживает пересоздание базы, и без выселения он опрашивал бы призрака
    // до конца времён.
    if (missing) {
      jobRegistry.forget(job.jobId);
      return;
    }
    if (status !== "done" && status !== "failed") return;

    // Результат в другом месте экрана или вовсе на другой странице — ровно тот
    // случай, для которого §7.5 оставляет тосты.
    toast.show({
      title: status === "done" ? ru.waiting.completed(job.title) : ru.waiting.failed(job.title),
      tone: status === "done" ? "moss" : "signal",
    });
    void client.invalidateQueries();
    jobRegistry.forget(job.jobId);
  }, [status, missing, job.jobId, job.title, toast, client]);

  return null;
}

/**
 * Строка списка. Собственного запроса не делает: `useJob` читает тот же ключ
 * кеша, который уже наполняет `JobWatcher`.
 */
function TrackedRow({ job }: { job: TrackedJob }) {
  const query = useJob(job.jobId);
  const progress = useProgress(query.data);

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <Link href={job.href} className="text-body-sm text-text hover:text-gos-fg">
          {job.title}
        </Link>
        <span className="shrink-0 text-caption tnum text-text-subtle">
          {progress ? ru.waiting.elapsed(duration(progress.elapsedMs)) : null}
        </span>
      </div>

      {progress?.phase ? <p className="text-caption text-text-muted">{progress.phase}</p> : null}

      <Progress
        value={progress?.share}
        label={
          progress && progress.total !== null
            ? ru.waiting.scale(formatCount(progress.processed), formatCount(progress.total))
            : ru.waiting.scaleUnknown
        }
      />
    </div>
  );
}
