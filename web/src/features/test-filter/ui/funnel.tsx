"use client";

import * as React from "react";
import { useMutation } from "@tanstack/react-query";
import { Button } from "@/shared/ui/button";
import { Card } from "@/shared/ui/card";
import { ErrorPanel } from "@/shared/ui/error-panel";
import { useJob } from "@/shared/api/use-job";
import { endpoints } from "@/shared/api/endpoints";
import type { FilterTestResult } from "@/shared/api/types";
import { ru } from "@/shared/i18n/ru";
import { formatCount } from "@/shared/lib/plural";

const TEST_DAYS = 30;

type Stage = { key: keyof NonNullable<FilterTestResult["funnel"]>; label: string };

const STAGES: Stage[] = [
  { key: "total", label: ru.filters.funnelAll },
  { key: "after_structural", label: ru.filters.funnelStructural },
  { key: "after_semantic", label: ru.filters.funnelSemantic },
  { key: "after_judge", label: ru.filters.funnelJudge },
];

/**
 * Воронка пробного прогона: сколько отсеял каждый этап.
 *
 * Считает сервер — этапы живут внутри llm-service, и повторить их на клиенте
 * нечем. Пока задание идёт, показывается прогресс, а не пустые столбцы.
 */
export function FilterFunnel({ filterId }: { filterId: number | null }) {
  const [jobId, setJobId] = React.useState<string | null>(null);
  const job = useJob(jobId);

  const start = useMutation({
    mutationFn: () => endpoints.testFilter(filterId!, TEST_DAYS),
    onSuccess: (accepted) => setJobId(accepted.job_id),
  });

  const result = job.data?.result as FilterTestResult | undefined;
  const funnel = result?.funnel;
  const running = start.isPending || (jobId !== null && job.data?.status !== "done");

  return (
    <Card className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-h3">{ru.filters.test}</h2>
        <Button
          variant="secondary"
          loading={running}
          // Проверять можно только сохранённый фильтр: прогон идёт по filter_id.
          disabled={filterId === null}
          onClick={() => start.mutate()}
        >
          {running ? ru.filters.testing : ru.filters.test}
        </Button>
      </div>

      {filterId === null ? (
        <p className="text-body-sm text-text-muted">
          Сохраните фильтр, чтобы проверить его на выборке за {TEST_DAYS} дней.
        </p>
      ) : null}

      {start.error ? (
        <ErrorPanel error={start.error} reset={() => start.reset()} />
      ) : null}

      {job.data?.status === "failed" ? (
        <p role="alert" className="text-body-sm text-signal-fg">
          {job.data.error ?? "Проверка не удалась"}
        </p>
      ) : null}

      {funnel ? <Bars funnel={funnel} dropped={result?.dropped} truncated={result?.dropped_truncated} /> : null}
    </Card>
  );
}

function Bars({
  funnel,
  dropped,
  truncated,
}: {
  funnel: NonNullable<FilterTestResult["funnel"]>;
  dropped: FilterTestResult["dropped"];
  truncated?: boolean;
}) {
  const peak = Math.max(funnel.total, 1);

  return (
    <div className="flex flex-col gap-3">
      <ol className="flex flex-col gap-2">
        {STAGES.map((stage, index) => {
          const value = funnel[stage.key];
          const previous = index === 0 ? value : funnel[STAGES[index - 1]!.key];
          const cut = previous - value;
          return (
            <li key={stage.key} className="flex items-center gap-3">
              <span className="tnum w-6 text-caption text-text-subtle">{index + 1}</span>
              <span className="w-44 shrink-0 text-body-sm text-text-muted">{stage.label}</span>
              <span className="h-4 flex-1 overflow-hidden rounded-[2px] bg-hairline">
                <span
                  className="block h-full bg-gos-fg/70"
                  style={{ width: `${(value / peak) * 100}%` }}
                />
              </span>
              <span className="tnum w-20 text-right text-body-sm text-text">
                {formatCount(value)}
              </span>
              <span className="tnum w-24 text-right text-body-sm text-text-subtle">
                {cut > 0 ? `−${formatCount(cut)}` : ""}
              </span>
            </li>
          );
        })}
      </ol>

      <DroppedNote dropped={dropped} truncated={truncated} />
    </div>
  );
}

/**
 * Что именно отсеялось.
 *
 * Список по векторному этапу сервер не отдаёт — отбор кандидатов ограничен
 * лимитом, и поимённо там ничего не известно. Пишем это прямо, а не показываем
 * пустой список как «ничего не отсеялось».
 */
function DroppedNote({
  dropped,
  truncated,
}: {
  dropped: FilterTestResult["dropped"];
  truncated?: boolean;
}) {
  if (!dropped) return null;

  const judge = dropped.judge?.length ?? 0;
  const structural = dropped.structural?.length ?? 0;

  return (
    <p className="text-body-sm text-text-subtle">
      Отсеяно судьёй: {formatCount(judge)}
      {structural > 0
        ? ` · структурными условиями показано ${formatCount(structural)}${truncated ? " из большего числа" : ""}`
        : ""}
      . Поимённый список по семантическому этапу не ведётся: отбор кандидатов
      ограничен лимитом.
    </p>
  );
}
