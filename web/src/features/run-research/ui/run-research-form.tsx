"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play } from "lucide-react";

import { endpoints } from "@/shared/api/endpoints";
import { jobRegistry } from "@/shared/api/job-registry";
import { qk, STALE } from "@/shared/api/query-keys";
import type { Filter, ResearchResult } from "@/shared/api/types";
import { useJob } from "@/shared/api/use-job";
import { ru } from "@/shared/i18n/ru";
import { Button } from "@/shared/ui/button";
import { Card } from "@/shared/ui/card";
import { Field, Input, Select } from "@/shared/ui/field";
import { RegionChecklist } from "@/shared/ui/region-checklist";
import { SectionHeading } from "@/shared/ui/section";
import { PendingBlock } from "@/shared/ui/pending-block";

export type RunResearchFormProps = {
  /** Предвыбранный критерий. Задан — селектор критерия не показывается. */
  filterId?: number;
};

/**
 * Запуск исследования по выбранному охвату.
 *
 * Движок умел регионы и сроки всегда — их не доносили два HTTP-перехода, и
 * запустить прогон из интерфейса было нельзя вовсе. Отсюда же берётся охват:
 * выбранные регионы **заменяют** регионы критерия, потому что знаменатель
 * воронки обязан описывать ровно тот корпус, который просили.
 */
export function RunResearchForm({ filterId }: RunResearchFormProps) {
  const router = useRouter();
  const client = useQueryClient();

  const filters = useQuery<Filter[]>({
    queryKey: qk.filters.all,
    staleTime: STALE.list,
    queryFn: ({ signal }) => endpoints.listFilters(signal),
    enabled: filterId === undefined,
  });

  const [criteria, setCriteria] = React.useState<number | null>(filterId ?? null);
  const [regions, setRegions] = React.useState<string[]>([]);
  const [since, setSince] = React.useState("");
  const [until, setUntil] = React.useState("");

  const [jobId, setJobId] = React.useState<string | null>(null);
  const job = useJob(jobId);

  const badRange = Boolean(since && until && until < since);
  const chosen = filterId ?? criteria;
  const running = Boolean(jobId) && job.data?.status !== "done";

  const start = useMutation({
    mutationFn: () => endpoints.runFilter(chosen!, { since, until, regions }),
    onSuccess: (accepted) => {
      setJobId(accepted.job_id);
      // Прогон идёт минутами, а на полном корпусе часами. С этой минуты за ним
      // следит каркас, и уход со страницы больше не гасит опрос.
      jobRegistry.track({
        jobId: accepted.job_id,
        title: ru.research.run.running,
        href: "/research",
      });
    },
  });

  React.useEffect(() => {
    if (job.data?.status !== "done") return;
    const result = job.data.result as ResearchResult | undefined;
    setJobId(null);
    void client.invalidateQueries({ queryKey: ["research", "runs"] });
    if (result?.run_id) router.push(`/research/${result.run_id}`);
  }, [job.data, client, router]);

  return (
    <Card padded className="flex flex-col gap-5">
      <div className="flex flex-col gap-1">
        <SectionHeading title={ru.research.run.title} />
        <p className="text-body-sm text-text-subtle">{ru.research.run.hint}</p>
      </div>

      {filterId === undefined ? (
        <Field label={ru.research.criteria} htmlFor="research-criteria">
          <Select
            id="research-criteria"
            value={criteria ?? ""}
            onChange={(event) =>
              setCriteria(event.target.value ? Number(event.target.value) : null)
            }
          >
            <option value="">{ru.research.run.pickCriteria}</option>
            {filters.data?.map((item) => (
              <option key={item.filter_id} value={item.filter_id}>
                {item.name}
              </option>
            ))}
          </Select>
        </Field>
      ) : null}

      <div className="grid gap-5 md:grid-cols-2">
        <Field
          label={ru.research.regions}
          hint={
            regions.length === 0
              ? ru.research.run.allRegionsHint
              : ru.research.run.regionsOverride
          }
        >
          <RegionChecklist value={regions} onChange={setRegions} />
        </Field>

        <div className="flex flex-col gap-2">
          <Field label={ru.catalog.facets.from} htmlFor="research-since">
            <Input
              id="research-since"
              type="date"
              value={since}
              onChange={(event) => setSince(event.target.value)}
            />
          </Field>
          <Field
            label={ru.catalog.facets.to}
            htmlFor="research-until"
            hint={ru.research.run.periodHint}
            error={badRange ? ru.research.run.badRange : undefined}
          >
            <Input
              id="research-until"
              type="date"
              value={until}
              onChange={(event) => setUntil(event.target.value)}
            />
          </Field>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <Button
          variant="primary"
          icon={<Play className="h-4 w-4" strokeWidth={1.5} />}
          disabled={chosen === null || badRange || running}
          loading={start.isPending}
          onClick={() => start.mutate()}
        >
          {ru.research.run.submit}
        </Button>
        {chosen === null ? (
          <span className="text-body-sm text-text-subtle">
            {ru.research.run.needsCriteria}
          </span>
        ) : null}
      </div>

      {running || start.error ? (
        <PendingBlock
          title={ru.research.run.running}
          job={job.data}
          error={start.error?.message ?? null}
          onRetry={() => start.mutate()}
        />
      ) : null}
    </Card>
  );
}
