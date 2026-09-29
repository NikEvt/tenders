"use client";

import * as React from "react";
import { useMutation } from "@tanstack/react-query";
import { endpoints } from "@/shared/api/endpoints";
import { jobRegistry } from "@/shared/api/job-registry";
import type { ResearchFunnel, ResearchResult } from "@/shared/api/types";
import { ru } from "@/shared/i18n/ru";
import { Button } from "@/shared/ui/button";
import { Card } from "@/shared/ui/card";
import { ErrorPanel } from "@/shared/ui/error-panel";
import { useJob } from "@/shared/api/use-job";

const TEST_DAYS = 30;

/**
 * Воронка пробного прогона.
 *
 * **Ветвление, а не каскад.** Прежняя лестница «все → после структурных →
 * после семантики → после судьи» описывала конвейер, где каждый этап был
 * подмножеством предыдущего. Теперь после находок поток разветвляется:
 * «принято правилами» не является подмножеством «отсеяно правилами», и рисовать
 * их вложенными столбцами значило бы врать о том, как работает отбор.
 *
 * Два числа обязательны и показываются даже нулями — это знаменатели.
 * «Не прочитано» не даёт принять «находок нет» за «здесь ничего нет», а
 * «не дошло» отличает остановку от потери.
 */
export function FilterFunnel({ filterId }: { filterId: number | null }) {
  const [jobId, setJobId] = React.useState<string | null>(null);
  const job = useJob(jobId);

  const start = useMutation({
    mutationFn: () => endpoints.testFilter(filterId!, TEST_DAYS),
    onSuccess: (accepted) => {
      setJobId(accepted.job_id);
      jobRegistry.track({
        jobId: accepted.job_id,
        title: ru.filters.testing,
        href: `/filters/${filterId}`,
      });
    },
  });

  const result = job.data?.result as ResearchResult | undefined;
  const funnel = result?.funnel;
  const running = start.isPending || (jobId !== null && job.data?.status !== "done");

  return (
    <Card className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-h3">{ru.filters.test}</h2>
        <Button
          variant="secondary"
          loading={running}
          // Проверять можно только сохранённый критерий: прогон идёт по filter_id.
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

      {start.error ? <ErrorPanel error={start.error} reset={() => start.reset()} /> : null}

      {job.data?.status === "failed" ? (
        <p role="alert" className="text-body-sm text-signal-fg">
          {job.data.error ?? "Проверка не удалась"}
        </p>
      ) : null}

      {funnel ? <Branches funnel={funnel} interrupted={result?.interrupted} /> : null}
    </Card>
  );
}

type Branch = {
  key: keyof ResearchFunnel;
  label: string;
  /** Подпись, объясняющая цену ветви. */
  note?: string;
  tone: "moss" | "signal" | "oak";
};

const BRANCHES: Branch[] = [
  {
    key: "confirmed_by_rules",
    label: ru.filters.funnelConfirmedByRules,
    note: ru.filters.funnelFree,
    tone: "moss",
  },
  {
    key: "rejected_by_rules",
    label: ru.filters.funnelRejectedByRules,
    note: ru.filters.funnelFree,
    tone: "signal",
  },
  { key: "disputed", label: ru.filters.funnelDisputed, tone: "oak" },
];

/** Из чего сложились «спорные»: это подытог, а не самостоятельная ветвь. */
const DISPUTED_PARTS: { key: keyof ResearchFunnel; label: string }[] = [
  { key: "from_cache", label: ru.filters.funnelFromCache },
  { key: "asked_model", label: ru.filters.funnelAskedModel },
  { key: "not_reached", label: ru.filters.funnelNotReached },
  { key: "failed", label: ru.filters.funnelFailed },
];

function Branches({
  funnel,
  interrupted,
}: {
  funnel: ResearchFunnel;
  interrupted?: boolean;
}) {
  // Ширина считается от рассмотренного, а не от максимума ветви: иначе самая
  // крупная ветвь всегда занимала бы всю строку и масштаб терялся.
  const scale = Math.max(funnel.reviewed, 1);

  return (
    <div className="flex flex-col gap-4">
      <Total funnel={funnel} />

      <ul className="flex flex-col gap-2">
        {BRANCHES.map((branch) => {
          const value = funnel[branch.key];
          return (
            <li key={String(branch.key)} className="flex items-baseline gap-3">
              <span className="w-44 shrink-0 text-body-sm text-text-muted">
                {branch.label}
              </span>
              <span className="w-16 shrink-0 text-right text-body tnum">{value}</span>
              <span
                className={`h-2 rounded-[2px] bg-${branch.tone}-fg`}
                style={{ width: `${Math.max((value / scale) * 100, value > 0 ? 1 : 0)}%` }}
                aria-hidden="true"
              />
              {branch.note ? (
                <span className="text-caption text-text-subtle">{branch.note}</span>
              ) : null}
            </li>
          );
        })}
      </ul>

      {funnel.disputed > 0 ? (
        <ul className="ml-44 flex flex-wrap gap-x-4 gap-y-1">
          {DISPUTED_PARTS.filter((part) => funnel[part.key] > 0).map((part) => (
            <li key={String(part.key)} className="text-caption text-text-subtle">
              {part.label}: <span className="tnum">{funnel[part.key]}</span>
            </li>
          ))}
        </ul>
      ) : null}

      {interrupted ? (
        <p role="alert" className="text-body-sm text-signal-fg">
          {ru.filters.funnelInterrupted}
        </p>
      ) : null}
    </div>
  );
}

/**
 * Шапка воронки: сколько рассмотрено и сколько осталось непрочитанным.
 *
 * «Не прочитано» стоит рядом с «рассмотрено» намеренно. Без него число находок
 * читается как исчерпывающее, хотя за ним может стоять непрочитанный корпус.
 */
function Total({ funnel }: { funnel: ResearchFunnel }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1">
      <span className="text-body-sm text-text-muted">
        {ru.filters.funnelReviewed}: <span className="tnum text-text">{funnel.reviewed}</span>
      </span>
      <span className="text-body-sm text-text-muted">
        {ru.filters.funnelPending}:{" "}
        <span className="tnum text-text">{funnel.documents_pending}</span>
      </span>
      <span className="text-caption text-text-subtle">{ru.filters.funnelPendingHint}</span>
    </div>
  );
}
