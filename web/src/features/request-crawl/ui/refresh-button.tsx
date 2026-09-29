"use client";

import * as React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";

import { endpoints } from "@/shared/api/endpoints";
import { jobRegistry } from "@/shared/api/job-registry";
import type { Job } from "@/shared/api/types";
import { useJob } from "@/shared/api/use-job";
import { ru } from "@/shared/i18n/ru";
import { Button } from "@/shared/ui/button";
import { PendingBlock } from "@/shared/ui/pending-block";

/**
 * Заказ свежей выгрузки из ЕИС.
 *
 * Механика названа в подписи, а не спрятана: ЕИС отдаёт суточные архивы, и
 * «обновить» означает перекачать последние два дня целиком. Новыми окажутся
 * лишь те извещения, которых ещё не было, — остальное отсеется дедупликацией
 * по реестровому номеру. Обещать «подтянем всё, что вышло за последний час»
 * было бы враньём: такого запроса у ЕИС нет.
 */
export function RefreshCrawlButton() {
  const client = useQueryClient();
  const [jobId, setJobId] = React.useState<string | null>(null);
  const job = useJob(jobId);

  const start = useMutation({
    // Период не задаём — сервер возьмёт вчера и сегодня.
    mutationFn: () => endpoints.requestCrawl({}),
    onSuccess: (accepted) => {
      setJobId(accepted.job_id);
      jobRegistry.track({
        jobId: accepted.job_id,
        title: ru.monitoring.refreshing,
        href: "/monitoring/crawler",
      });
    },
  });

  React.useEffect(() => {
    if (job.data?.status !== "done") return;
    setJobId(null);
    void client.invalidateQueries({ queryKey: ["monitoring"] });
    void client.invalidateQueries({ queryKey: ["tenders"] });
  }, [job.data?.status, client]);

  const running = start.isPending || (jobId !== null && job.data?.status !== "done");

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-3">
        <Button
          variant="secondary"
          size="sm"
          icon={<RefreshCw className="h-4 w-4" strokeWidth={1.5} />}
          disabled={running}
          loading={start.isPending}
          onClick={() => start.mutate()}
        >
          {ru.monitoring.refresh}
        </Button>
        <span className="text-body-sm text-text-subtle">{ru.monitoring.refreshHint}</span>
      </div>

      {running || start.error ? (
        <PendingBlock
          title={ru.monitoring.refreshing}
          job={job.data as Job | undefined}
          error={start.error?.message ?? null}
          onRetry={() => start.mutate()}
        />
      ) : null}
    </div>
  );
}
