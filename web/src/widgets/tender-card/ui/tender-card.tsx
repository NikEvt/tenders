"use client";

import * as React from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import * as Tabs from "@radix-ui/react-tabs";
import { ArrowLeft, Bookmark, ExternalLink, EyeOff, Printer } from "lucide-react";
import { Button } from "@/shared/ui/button";
import { Card } from "@/shared/ui/card";
import { DefinitionList } from "@/shared/ui/definition-list";
import { CopyableMono, Mono } from "@/shared/ui/mono";
import { Rail } from "@/shared/ui/rail/rail";
import { Skeleton, TextSkeleton } from "@/shared/ui/skeleton";
import { ru } from "@/shared/i18n/ru";
import { cn } from "@/shared/lib/cn";
import { dateShort, money, regionName, toDate } from "@/shared/lib/format";
import { useHotkeys } from "@/shared/lib/hooks";
import { endpoints } from "@/shared/api/endpoints";
import { qk, STALE } from "@/shared/api/query-keys";
import type { Evidence, TenderDetail, Verdict } from "@/shared/api/types";
import { StatusPill } from "@/entities/tender/ui/status-pill";
import { VerdictNote } from "@/entities/verdict/ui/verdict-note";
import { FeedbackStrip } from "@/features/rate-tender/ui/feedback-strip";
import { useRecordView } from "@/features/rate-tender/model/use-rate-tender";
import { useRecentTenders } from "@/shared/lib/recent-tenders";
import { DocumentsTab } from "./documents-tab";
import { EventsTab } from "./events-tab";
import { SimilarTab } from "./similar-tab";

const TABS = ["overview", "documents", "ai", "similar", "events"] as const;
type Tab = (typeof TABS)[number];

const EIS_URL = (regNum: string) =>
  `https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html?regNumber=${regNum}`;

export function TenderCard({ regNum }: { regNum: string }) {
  const [tab, setTab] = React.useState<Tab>("overview");
  const view = useRecordView();
  const { remember } = useRecentTenders();

  const detail = useQuery<TenderDetail>({
    queryKey: qk.tenders.byId(regNum),
    queryFn: ({ signal }) => endpoints.getTender(regNum, signal),
    staleTime: STALE.detail,
  });

  const tender = detail.data?.tender;

  // Просмотр — слабый сигнал для профиля, и шлётся он один раз на закупку.
  // Сторож в ref вместо урезанного списка зависимостей: так эффект остаётся
  // честным по зависимостям и не отправляет сигнал повторно на каждый ререндер.
  const recorded = React.useRef<number | null>(null);
  React.useEffect(() => {
    if (!tender || recorded.current === tender.tender_id) return;
    recorded.current = tender.tender_id;
    view.mutate({ tenderId: tender.tender_id });
    remember({ regNum: tender.reg_num, name: tender.name ?? tender.reg_num });
  }, [tender, view, remember]);

  useHotkeys(
    TABS.map((name, index) => ({
      combo: String(index + 1),
      handler: () => setTab(name),
    })),
  );

  if (detail.isLoading) return <CardSkeleton />;
  if (!tender) {
    return (
      <p role="alert" className="text-body text-signal-fg">
        {ru.errors.tenderNotFound(regNum)}
      </p>
    );
  }

  const verdicts = (detail.data?.verdicts ?? []) as Verdict[];

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3 no-print">
        <Button asChild variant="quiet" size="sm">
          <Link href="/tenders">
            <ArrowLeft className="h-4 w-4" strokeWidth={1.5} aria-hidden="true" />
            {ru.catalog.title}
          </Link>
        </Button>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" icon={<Bookmark className="h-4 w-4" strokeWidth={1.5} />}>
            {ru.tender.addToShortlist}
          </Button>
          <Button variant="ghost" size="sm" icon={<EyeOff className="h-4 w-4" strokeWidth={1.5} />}>
            {ru.tender.hide}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            icon={<Printer className="h-4 w-4" strokeWidth={1.5} />}
            onClick={() => window.print()}
          >
            {ru.common.print}
          </Button>
        </div>
      </div>

      <header className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <StatusPill dates={tender} />
          <CopyableMono value={tender.reg_num} label={ru.tender.regNum} />
          <span className="text-body-sm text-text-muted">
            {ru.tender.published.toLowerCase()} {dateShort(tender.publish_date)} · {ru.common.law}
          </span>
        </div>
        <h1 className="clamp-2 text-h1" title={tender.name ?? undefined}>
          {tender.name ?? tender.description ?? "—"}
        </h1>
      </header>

      <Card padded={false} className="px-6 pb-4 pt-6">
        <Rail
          published={toDate(tender.publish_date)}
          start={toDate(tender.start_date)}
          deadline={toDate(tender.end_date)}
          previousDeadline={tender.deadline_changed ? toDate(tender.prev_end_date) : null}
          scale="macro"
        />
      </Card>

      <div className="flex flex-col gap-6 lg:flex-row">
        <div className="flex min-w-0 flex-1 flex-col">
          <Tabs.Root value={tab} onValueChange={(value) => setTab(value as Tab)}>
            <Tabs.List className="flex gap-1 border-b border-hairline no-print">
              {TABS.map((name, index) => (
                <Tabs.Trigger
                  key={name}
                  value={name}
                  className={cn(
                    "-mb-px border-b-2 px-3 py-2 text-body transition-colors duration-(--dur-state)",
                    "border-transparent text-text-muted hover:text-text",
                    "data-[state=active]:border-gos-fg data-[state=active]:font-medium data-[state=active]:text-gos-fg",
                  )}
                  title={`${index + 1}`}
                >
                  {tabLabel(name, detail.data)}
                </Tabs.Trigger>
              ))}
            </Tabs.List>

            <Tabs.Content value="overview" className="pt-6">
              <DefinitionList
                items={[
                  { label: ru.tender.object, value: tender.description ?? tender.name },
                  { label: ru.tender.okpd2, value: okpd2(tender.okpd2_code, tender.okpd2_name), mono: true },
                  { label: ru.tender.region, value: regionName(tender.region_code) },
                  { label: ru.tender.applyStart, value: dateShort(tender.start_date) },
                  { label: ru.tender.deadline, value: dateShort(tender.end_date) },
                  { label: ru.tender.method, value: null },
                  { label: ru.tender.place, value: null },
                  { label: ru.tender.security, value: null },
                ]}
              />
            </Tabs.Content>

            <Tabs.Content value="documents" className="pt-6">
              <DocumentsTab regNum={regNum} documents={detail.data?.documents ?? []} />
            </Tabs.Content>

            <Tabs.Content value="ai" className="flex flex-col gap-4 pt-6">
              {verdicts.length === 0 ? (
                <p className="text-body text-text-muted">{ru.ai.judgeNotRun}</p>
              ) : (
                verdicts.map((verdict, index) => (
                  <VerdictNote
                    key={`${verdict.filter_id}-${index}`}
                    verdict={verdict}
                    model="qwen3.6-35b"
                    reasoningEffort="low"
                    citationHref={(evidence) => citationHref(regNum, evidence)}
                  />
                ))
              )}
            </Tabs.Content>

            <Tabs.Content value="similar" className="pt-6">
              <SimilarTab regNum={regNum} />
            </Tabs.Content>

            <Tabs.Content value="events" className="pt-6">
              <EventsTab regNum={regNum} />
            </Tabs.Content>
          </Tabs.Root>

          <FeedbackStrip
            tenderId={tender.tender_id}
            okpd2={tender.okpd2_code}
            region={regionName(tender.region_code)}
            className="mt-8 rounded-[10px] border border-hairline no-print"
          />
        </div>

        <aside className="flex w-full shrink-0 flex-col gap-5 lg:w-80">
          <Card className="flex flex-col gap-4">
            <div>
              <p className="text-caption text-text-muted">{ru.tender.price}</p>
              <p className="mt-1 font-mono text-h2 tnum text-text">{money(tender.price)}</p>
            </div>
            <DefinitionList
              columns={1}
              items={[
                { label: ru.tender.customer, value: tender.customer_name },
                { label: ru.tender.inn, value: tender.customer_inn, mono: true },
                { label: ru.tender.kpp, value: null, mono: true },
                { label: ru.tender.platform, value: null },
              ]}
            />
            <Button asChild variant="secondary" className="w-full">
              <a href={EIS_URL(tender.reg_num)} target="_blank" rel="noopener noreferrer">
                {ru.tender.openInEis}
                <ExternalLink className="h-4 w-4" strokeWidth={1.5} aria-hidden="true" />
              </a>
            </Button>
          </Card>

          <Card className="flex flex-col gap-2">
            <p className="text-caption uppercase text-text-muted">{ru.tender.documents}</p>
            <p className="text-body text-text">
              {tender.document_count} · <Mono>{tender.documents_status}</Mono>
            </p>
          </Card>
        </aside>
      </div>
    </div>
  );
}

function tabLabel(tab: Tab, detail: TenderDetail | undefined): string {
  if (tab === "documents") {
    const count = detail?.documents.length ?? 0;
    return count ? `${ru.tender.tabs.documents} ${count}` : ru.tender.tabs.documents;
  }
  return {
    overview: ru.tender.tabs.overview,
    documents: ru.tender.tabs.documents,
    ai: ru.tender.tabs.ai,
    similar: ru.tender.tabs.similar,
    events: ru.tender.tabs.events,
  }[tab];
}

/**
 * Ссылка на источник вердикта. `chunk_id` есть, а смещений чанка в тексте нет —
 * просмотрщик честно скажет об этом, вместо того чтобы подсветить наугад
 * (docs/API-GAPS.md §4).
 */
function citationHref(regNum: string, evidence: Evidence): string | null {
  if (!evidence.document_id) return null;
  const anchor = evidence.chunk_id ? `#chunk-${evidence.chunk_id}` : "";
  return `/tenders/${regNum}/documents/${evidence.document_id}${anchor}`;
}

function okpd2(code: string | null, name: string | null): string | null {
  if (!code) return null;
  return name ? `${code} — ${name}` : code;
}

function CardSkeleton() {
  return (
    <div className="flex flex-col gap-6">
      <Skeleton className="h-8 w-40" />
      <Skeleton className="h-9 w-3/4" />
      <Skeleton className="h-[88px] w-full rounded-[10px]" />
      <div className="flex gap-6">
        <div className="flex-1">
          <TextSkeleton lines={8} />
        </div>
        <Skeleton className="hidden h-64 w-80 rounded-[10px] lg:block" />
      </div>
    </div>
  );
}
