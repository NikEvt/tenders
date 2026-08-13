"use client";

import { useQuery } from "@tanstack/react-query";
import { endpoints } from "@/shared/api/endpoints";
import { qk } from "@/shared/api/query-keys";
import type { Job } from "@/shared/api/types";

const TERMINAL = new Set(["done", "failed", "cancelled"]);

/**
 * Опрос долгой задачи: 1с → 2с → 5с, дальше по 5с (§7.4).
 *
 * Задача живёт в кеше по job_id, поэтому уход со страницы и возврат
 * продолжают опрос, а не начинают его заново.
 */
export function useJob(jobId: string | null) {
  return useQuery<Job>({
    queryKey: qk.jobs(jobId ?? "none"),
    queryFn: ({ signal }) => endpoints.job(jobId!, signal),
    enabled: Boolean(jobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status && TERMINAL.has(status)) return false;
      const attempts = query.state.dataUpdateCount;
      return attempts === 0 ? 1000 : attempts === 1 ? 2000 : 5000;
    },
    staleTime: 0,
  });
}

export function isJobRunning(job: Job | undefined): boolean {
  return Boolean(job && !TERMINAL.has(job.status));
}

export function jobProgress(job: Job | undefined): number | null {
  if (!job || !job.total) return null;
  return Math.min(1, (job.processed ?? 0) / job.total);
}
