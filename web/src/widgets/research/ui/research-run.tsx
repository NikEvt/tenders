"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { Card } from "@/shared/ui/card";
import { Pill } from "@/shared/ui/pill";
import { Quote } from "@/shared/ui/quote";
import { Segmented } from "@/shared/ui/segmented";
import { TextSkeleton } from "@/shared/ui/skeleton";
import { PageHeader } from "@/shared/ui/section";
import { endpoints } from "@/shared/api/endpoints";
import type { Market, ResearchRun, ResearchTenders } from "@/shared/api/types";
import { ru } from "@/shared/i18n/ru";
import { money, regionName } from "@/shared/lib/format";
import { formatCount } from "@/shared/lib/plural";

type Tab = "tenders" | "market";

export function ResearchRunView({ runId }: { runId: number }) {
  const [tab, setTab] = React.useState<Tab>("tenders");

  const run = useQuery<ResearchRun>({
    queryKey: ["research", "run", runId],
    queryFn: ({ signal }) => endpoints.researchRun(runId, signal),
    // Идущий прогон обязан обновляться сам: теперь сюда приходят сразу после
    // запуска, и статичная страница выглядела бы зависшей.
    refetchInterval: (query) =>
      query.state.data?.status === "running" ? 5000 : false,
  });

  if (run.isLoading) return <TextSkeleton lines={8} />;
  if (!run.data) return null;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={run.data.name} meta={run.data.criteria_version} />

      <Funnel run={run.data} />

      <Segmented
        label={ru.research.title}
        value={tab}
        onChange={(value) => setTab(value as Tab)}
        options={[
          { value: "tenders", label: ru.research.tabTenders },
          { value: "market", label: ru.research.tabMarket },
        ]}
      />

      {tab === "tenders" ? <Tenders runId={runId} /> : <MarketView runId={runId} />}
    </div>
  );
}

/**
 * Воронка прогона — ветвление, а не каскад.
 *
 * «Принято правилами» не подмножество «отсеяно правилами»: после находок поток
 * расходится на три равноправные ветви. Рисовать их вложенными столбцами
 * значило бы врать о том, как работает отбор.
 */
function Funnel({ run }: { run: ResearchRun }) {
  const f = run.funnel;
  const scale = Math.max(f.tenders_candidate, 1);

  const branches = [
    { label: ru.filters.funnelConfirmedByRules, value: f.confirmed_by_rules, tone: "moss" },
    { label: ru.filters.funnelRejectedByRules, value: f.rejected_by_rules, tone: "signal" },
    { label: ru.filters.funnelDisputed, value: f.disputed, tone: "oak" },
  ];

  return (
    <Card className="flex flex-col gap-4">
      <dl className="flex flex-wrap gap-x-6 gap-y-1 text-body-sm">
        <Pair label="Извещений" value={f.tenders_total} />
        <Pair label="Кандидатов" value={f.tenders_candidate} />
        <Pair label="Документов прочитано" value={f.documents_scanned} />
        {/* Знаменатель. Ретроспектива описывает, как его отсутствие приводит к
            выводу «здесь ничего нет» на месте, где просто не искали. */}
        <Pair label={ru.filters.funnelPending} value={f.documents_pending} muted />
        <Pair label="Находок" value={f.hits_found} />
      </dl>

      <ul className="flex flex-col gap-2">
        {branches.map((branch) => (
          <li key={branch.label} className="flex items-baseline gap-3">
            <span className="w-44 shrink-0 text-body-sm text-text-muted">
              {branch.label}
            </span>
            <span className="w-16 shrink-0 text-right text-body tnum">{branch.value}</span>
            <span
              className={`h-2 rounded-[2px] bg-${branch.tone}-fg`}
              style={{
                width: `${Math.max((branch.value / scale) * 100, branch.value > 0 ? 1 : 0)}%`,
              }}
              aria-hidden="true"
            />
          </li>
        ))}
      </ul>

      {f.not_reached > 0 ? (
        <p role="alert" className="text-body-sm text-signal-fg">
          {ru.filters.funnelInterrupted} {ru.filters.funnelNotReached}: {f.not_reached}
        </p>
      ) : null}
    </Card>
  );
}

function Pair({
  label,
  value,
  muted,
}: {
  label: string;
  value: number;
  muted?: boolean;
}) {
  return (
    <div className="flex items-baseline gap-1.5">
      <dt className={muted ? "text-text-subtle" : "text-text-muted"}>{label}</dt>
      <dd className={`tnum ${muted ? "text-text-subtle" : "text-text"}`}>
        {formatCount(value)}
      </dd>
    </div>
  );
}

/**
 * Закупки прогона.
 *
 * Спорные и отклонённые показываются наравне с подтверждёнными: по ним видно,
 * что именно движок отбросил, а это и есть способ понять, не слишком ли туго
 * затянут критерий.
 */
function Tenders({ runId }: { runId: number }) {
  const [confidence, setConfidence] = React.useState<string | undefined>(undefined);

  const tenders = useQuery<ResearchTenders>({
    queryKey: ["research", "tenders", runId, confidence],
    queryFn: ({ signal }) =>
      endpoints.researchTenders(runId, { confidence, page_size: 50 }, signal),
  });

  return (
    <div className="flex flex-col gap-4">
      <Segmented
        label={ru.research.tabTenders}
        value={confidence ?? "all"}
        onChange={(value) => setConfidence(value === "all" ? undefined : value)}
        options={[
          { value: "all", label: "Все" },
          { value: "confirmed", label: ru.research.confirmed },
          { value: "disputed", label: ru.research.disputed },
          { value: "rejected", label: ru.research.rejected },
        ]}
      />

      {tenders.isLoading ? <TextSkeleton lines={6} /> : null}

      <ul className="flex flex-col gap-3">
        {tenders.data?.items.map((item) => (
          <li key={item.tender_id}>
            <Card className="flex flex-col gap-2">
              <div className="flex flex-wrap items-baseline justify-between gap-3">
                <span className="text-body font-medium">{item.name ?? item.reg_num}</span>
                <span className="tnum text-body-sm text-text-muted">
                  {item.price ? money(Number(item.price)) : ru.research.noPrice}
                </span>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <Pill
                  tone={
                    item.confidence === "confirmed"
                      ? "moss"
                      : item.confidence === "rejected"
                        ? "signal"
                        : "oak"
                  }
                >
                  {item.confidence === "confirmed"
                    ? ru.research.confirmed
                    : item.confidence === "rejected"
                      ? ru.research.rejected
                      : ru.research.disputed}
                </Pill>
                {/* Видно, во что обошлось решение: правила бесплатны, модель — нет. */}
                <span className="text-caption text-text-subtle">
                  {item.decided_by === "model"
                    ? ru.research.decidedByModel
                    : ru.research.decidedByRules}
                  {item.reason ? ` · ${item.reason}` : ""}
                </span>
              </div>

              {item.hits.length ? (
                <ul className="flex flex-col gap-1">
                  {item.hits.slice(0, 3).map((hit, index) => (
                    <li key={index} className="measure">
                      <Quote span={hit} />
                      {hit.file_name ? (
                        <span className="ml-2 text-caption text-text-subtle">
                          {hit.file_name}
                        </span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              ) : null}
            </Card>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Разрезы рынка.
 *
 * Медиана стоит рядом со средним, а не вместо: у НМЦК тяжёлый правый хвост, и
 * одно среднее описывает рынок, которого нет. «Доля трёх крупнейших» показывает
 * этот хвост числом.
 */
function MarketView({ runId }: { runId: number }) {
  const market = useQuery<Market>({
    queryKey: ["research", "market", runId],
    queryFn: ({ signal }) => endpoints.researchMarket(runId, signal),
  });

  if (market.isLoading) return <TextSkeleton lines={6} />;
  const data = market.data;
  if (!data || data.total_count === 0) {
    return <p className="text-body-sm text-text-muted">Подтверждённых закупок нет.</p>;
  }

  return (
    <div className="flex flex-col gap-4">
      <Card className="flex flex-col gap-2">
        <dl className="flex flex-wrap gap-x-6 gap-y-1 text-body-sm">
          <Pair label={ru.research.confirmed} value={data.total_count} />
          <div className="flex items-baseline gap-1.5">
            <dt className="text-text-muted">{ru.research.total}</dt>
            <dd className="tnum text-text">{money(Number(data.total_value))}</dd>
          </div>
          <div className="flex items-baseline gap-1.5">
            <dt className="text-text-muted">{ru.research.median}</dt>
            <dd className="tnum text-text">
              {data.median_price ? money(Number(data.median_price)) : "—"}
            </dd>
          </div>
          <div className="flex items-baseline gap-1.5">
            <dt className="text-text-muted">{ru.research.average}</dt>
            <dd className="tnum text-text">
              {data.average_price ? money(Number(data.average_price)) : "—"}
            </dd>
          </div>
          <div className="flex items-baseline gap-1.5">
            <dt className="text-text-muted">{ru.research.topShare}</dt>
            <dd className="tnum text-text">{Math.round(data.top_share * 100)}%</dd>
          </div>
        </dl>
        <p className="text-caption text-text-subtle">{ru.research.medianHint}</p>
      </Card>

      <Buckets title={ru.research.byRegion} buckets={data.by_region} label={regionName} />
      <Buckets
        title={ru.research.byCustomer}
        buckets={data.by_customer}
        note={ru.research.customerHint}
      />
      <Buckets title={ru.research.byOkpd2} buckets={data.by_okpd2} />
    </div>
  );
}

function Buckets({
  title,
  buckets,
  label,
  note,
}: {
  title: string;
  buckets: Market["by_region"];
  label?: (key: string) => string;
  note?: string;
}) {
  if (!buckets.length) return null;
  const peak = Math.max(...buckets.map((b) => Number(b.total)), 1);

  return (
    <Card className="flex flex-col gap-2">
      <h3 className="text-h3">{title}</h3>
      {note ? <p className="text-caption text-text-subtle">{note}</p> : null}
      <ul className="flex flex-col gap-1.5">
        {buckets.slice(0, 12).map((bucket) => (
          <li key={bucket.key} className="flex items-baseline gap-3">
            <span className="w-56 shrink-0 truncate text-body-sm text-text-muted">
              {label ? label(bucket.key) : bucket.label}
            </span>
            <span className="w-10 shrink-0 text-right text-body-sm tnum">
              {bucket.count}
            </span>
            <span className="h-2 flex-1 overflow-hidden rounded-[2px] bg-hairline">
              <span
                className="block h-full bg-gos-fg/70"
                style={{ width: `${(Number(bucket.total) / peak) * 100}%` }}
              />
            </span>
            <span className="w-32 shrink-0 text-right text-body-sm tnum text-text-muted">
              {money(Number(bucket.total))}
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}
