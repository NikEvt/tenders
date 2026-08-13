"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Printer } from "lucide-react";
import { Button } from "@/shared/ui/button";
import { Card } from "@/shared/ui/card";
import { Markdown } from "@/shared/ui/markdown";
import { PageHeader, SectionHeading } from "@/shared/ui/section";
import { Skeleton, TextSkeleton } from "@/shared/ui/skeleton";
import { VellumNote } from "@/shared/ui/vellum-note";
import { Rail } from "@/shared/ui/rail/rail";
import { CopyableMono } from "@/shared/ui/mono";
import { ru } from "@/shared/i18n/ru";
import { cn } from "@/shared/lib/cn";
import { dateLong, dateShort, dateWeekday, isoDate, money, toDate } from "@/shared/lib/format";
import { formatCount, withPlural } from "@/shared/lib/plural";
import { useFirstVisitToday } from "@/shared/lib/hooks";
import { endpoints } from "@/shared/api/endpoints";
import { qk, STALE } from "@/shared/api/query-keys";
import { ApiError } from "@/shared/api/client";
import type { Digest } from "@/shared/api/types";
import { useJob } from "@/shared/api/use-job";
import { PendingBlock } from "@/features/async-job/ui/pending-block";

/**
 * Сводка дня — первое, что видит аналитик утром.
 *
 * Открывается не рядом плиток с числами, а самой сводкой, набранной как
 * документ: это самый характерный артефакт системы, и его стоит читать, а не
 * пролистывать.
 */
export function DigestReader({ date }: { date: string }) {
  const router = useRouter();
  const client = useQueryClient();
  const today = isoDate(new Date());
  const isToday = date === today;
  const firstVisit = useFirstVisitToday("zakupki:digest-seen");

  const digest = useQuery<Digest>({
    queryKey: qk.digest(date),
    queryFn: ({ signal }) => endpoints.digest(date, signal),
    staleTime: isToday ? STALE.digestToday : STALE.digestPast,
    retry: false,
  });

  const [jobId, setJobId] = React.useState<string | null>(null);
  const job = useJob(jobId);

  React.useEffect(() => {
    if (job.data?.status === "done") {
      setJobId(null);
      void client.invalidateQueries({ queryKey: qk.digest(date) });
    }
  }, [job.data?.status, client, date]);

  const build = useMutation({
    mutationFn: () => endpoints.requestDigest(date, false),
    onSuccess: (result) => setJobId(result.job_id),
  });

  const shift = (days: number) => {
    const next = new Date(`${date}T00:00:00`);
    next.setDate(next.getDate() + days);
    router.push(isoDate(next) === today ? "/" : `/digest/${isoDate(next)}`);
  };

  React.useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLElement && event.target.tagName === "INPUT") return;
      if (event.key === "ArrowLeft") shift(-1);
      if (event.key === "ArrowRight") shift(1);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  });

  // За какие дни сводки есть. Раньше это было неизвестно, и стрелки вели
  // вслепую: пользователь листал дни, не зная, есть ли там что-нибудь.
  const period = recentWindow(today);
  const available = useQuery({
    queryKey: qk.digestDates(period.from, period.to),
    staleTime: STALE.list,
    queryFn: ({ signal }) => endpoints.digestDates(period.from, period.to, signal),
  });

  const notFound = digest.error instanceof ApiError && digest.error.status === 404;
  const sections = digest.data?.sections;

  return (
    <article className={cn("flex flex-col gap-8", firstVisit && "[&>*]:rise-in")}>
      <PageHeader
        display
        title={isToday ? ru.digest.title : ru.digest.titleFor(dateLong(date))}
        meta={
          digest.data
            ? [
                withPlural(digest.data.tender_count, ["извещение", "извещения", "извещений"]),
                sections?.deadline_changes?.length
                  ? `${formatCount(sections.deadline_changes.length)} со сдвинутым сроком`
                  : null,
              ]
                .filter(Boolean)
                .join(" · ")
            : dateWeekday(date)
        }
        actions={
          <>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={ru.digest.prevDay}
              onClick={() => shift(-1)}
            >
              <ChevronLeft className="h-4 w-4" strokeWidth={1.5} />
            </Button>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={ru.digest.nextDay}
              onClick={() => shift(1)}
              disabled={isToday}
            >
              <ChevronRight className="h-4 w-4" strokeWidth={1.5} />
            </Button>
            <Button
              variant="secondary"
              size="sm"
              icon={<Printer className="h-4 w-4" strokeWidth={1.5} />}
              onClick={() => window.print()}
            >
              {ru.common.print}
            </Button>
          </>
        }
      >
        <p className="text-body-sm text-text-subtle">{dateWeekday(date)}</p>
      </PageHeader>

      <AvailableDates dates={available.data?.dates ?? []} current={date} today={today} />

      {digest.isLoading ? (
        <TextSkeleton lines={5} />
      ) : notFound ? (
        <NotReady
          isToday={isToday}
          date={date}
          job={job.data}
          pending={build.isPending || Boolean(jobId)}
          error={build.error?.message ?? null}
          onBuild={() => build.mutate()}
        />
      ) : digest.data ? (
        <>
          <VellumNote
            eyebrow={ru.digest.title.toUpperCase()}
            source={digest.data.model}
            actions={
              sections?.clusters && Object.keys(sections.clusters).length > 0 ? (
                <HowBuilt clusters={sections.clusters} />
              ) : null
            }
          >
            <Markdown source={digest.data.summary_md} />
          </VellumNote>

          {sections?.top?.length ? (
            <section className="flex flex-col gap-3">
              <SectionHeading title={ru.digest.sections.top} count={sections.top.length} />
              <ul className="flex flex-col gap-2">
                {sections.top.map((item) => (
                  <li key={item.reg_num}>
                    <Card interactive padded={false} className="p-4">
                      <Link href={`/tenders/${item.reg_num}`} className="flex items-center gap-4 no-underline">
                        <span className="min-w-0 flex-1">
                          <span className="clamp-1 block text-body text-text">
                            {item.name ?? item.reg_num}
                          </span>
                          <CopyableMono value={item.reg_num} label={ru.tender.regNum} />
                        </span>
                        <span className="shrink-0 font-mono text-body tnum text-text">
                          {money(item.price)}
                        </span>
                      </Link>
                    </Card>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {sections?.new_customers?.length ? (
            <section className="flex flex-col gap-3">
              <SectionHeading
                title={ru.digest.sections.newCustomers}
                count={sections.new_customers.length}
              />
              <ul className="flex flex-col divide-y divide-hairline rounded-[10px] border border-hairline bg-surface">
                {sections.new_customers.map((name) => (
                  <li key={name} className="px-4 py-3 text-body">
                    {name}
                  </li>
                ))}
              </ul>
              <p className="text-body-sm text-text-subtle">
                Дата первой публикации и число закупок появятся вместе с расширением
                `sections.new_customers` — см. docs/API-GAPS.md §12.
              </p>
            </section>
          ) : null}

          {sections?.deadline_changes?.length ? (
            <section className="flex flex-col gap-3">
              <SectionHeading
                title={ru.digest.sections.deadlineChanges}
                count={sections.deadline_changes.length}
              />
              <ul className="flex flex-col divide-y divide-hairline rounded-[10px] border border-hairline bg-surface">
                {sections.deadline_changes.map((regNum) => (
                  <li key={regNum} className="flex items-center gap-4 px-4 py-3">
                    <Link
                      href={`/tenders/${regNum}`}
                      className="font-mono text-mono text-gos-fg no-underline hover:underline"
                    >
                      {regNum}
                    </Link>
                    <span className="ml-auto w-40">
                      <Rail deadline={toDate(new Date())} scale="micro" />
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </>
      ) : null}
    </article>
  );
}

/** Map-шаг: резюме по категориям, из которых собрана общая сводка. */
function HowBuilt({ clusters }: { clusters: Record<string, string> }) {
  return (
    <details className="w-full">
      <summary className="cursor-pointer text-body-sm font-medium text-gos-fg">
        {ru.digest.howBuilt}
      </summary>
      <p className="mt-2 text-body-sm text-text-muted">{ru.digest.howBuiltHint}</p>
      <dl className="mt-3 flex flex-col gap-3">
        {Object.entries(clusters).map(([category, summary]) => (
          <div key={category}>
            <dt className="text-caption uppercase text-text-muted">{category}</dt>
            <dd className="mt-1 text-body-sm text-text">{summary}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

function NotReady({
  isToday,
  date,
  job,
  pending,
  error,
  onBuild,
}: {
  isToday: boolean;
  date: string;
  job: ReturnType<typeof useJob>["data"];
  pending: boolean;
  error: string | null;
  onBuild: () => void;
}) {
  if (pending || job) {
    return (
      <PendingBlock title={ru.digest.building} job={job} error={error} onRetry={onBuild} />
    );
  }

  return (
    <VellumNote eyebrow={ru.digest.title.toUpperCase()} source="—">
      <p>
        {isToday
          ? `${ru.digest.notReadyTitle} ${ru.digest.notReadyBody}`
          : `Сводка за ${dateLong(date)} не собиралась.`}
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button variant="primary" size="sm" onClick={onBuild}>
          {ru.digest.build}
        </Button>
        <Button variant="secondary" size="sm" asChild>
          <Link href="/monitoring/crawler">{ru.digest.openRuns}</Link>
        </Button>
      </div>
    </VellumNote>
  );
}

export function DigestSkeleton() {
  return (
    <div className="flex flex-col gap-8">
      <Skeleton className="h-10 w-72" />
      <Skeleton className="h-40 w-full rounded-[10px]" />
      <Skeleton className="h-6 w-56" />
      <Skeleton className="h-20 w-full rounded-[10px]" />
    </div>
  );
}


const WINDOW_DAYS = 30;

function recentWindow(today: string): { from: string; to: string } {
  const from = new Date(`${today}T00:00:00`);
  from.setDate(from.getDate() - WINDOW_DAYS);
  return { from: isoDate(from), to: today };
}

/**
 * Дни, за которые сводка уже собрана.
 *
 * Показываются только существующие даты: точка в этом ряду — обещание, что по
 * ссылке есть что читать. Дни без сводки сюда не попадают, и клиент не зовёт
 * пользователя в пустоту.
 */
function AvailableDates({
  dates,
  current,
  today,
}: {
  dates: string[];
  current: string;
  today: string;
}) {
  if (dates.length === 0) return null;

  return (
    <nav aria-label="Дни со сводками" className="no-print flex flex-wrap items-center gap-1">
      {dates.map((date) => {
        const active = date === current;
        return (
          <Link
            key={date}
            href={date === today ? "/" : `/digest/${date}`}
            aria-current={active ? "page" : undefined}
            className={cn(
              "tnum rounded-[6px] px-2 py-1 text-caption",
              active
                ? "surface-gos"
                : "text-text-muted hover:bg-surface-sunken hover:text-text",
            )}
          >
            {dateShort(date)}
          </Link>
        );
      })}
    </nav>
  );
}
