"use client";

import * as React from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink, X } from "lucide-react";
import { Button } from "@/shared/ui/button";
import { CopyableMono } from "@/shared/ui/mono";
import { DefinitionList } from "@/shared/ui/definition-list";
import { Rail } from "@/shared/ui/rail/rail";
import { Skeleton, TextSkeleton } from "@/shared/ui/skeleton";
import { ru } from "@/shared/i18n/ru";
import { cn } from "@/shared/lib/cn";
import { dateShort, money, regionName, toDate } from "@/shared/lib/format";
import { endpoints } from "@/shared/api/endpoints";
import { qk, STALE } from "@/shared/api/query-keys";
import type { Verdict } from "@/shared/api/types";
import { StatusPill } from "@/entities/tender/ui/status-pill";
import { VerdictNote } from "@/entities/verdict/ui/verdict-note";

/**
 * Панель-инспектор. Список за ней не размонтируется, не прокручивается и не
 * теряет выделение: `j`/`k` листают строки, панель обновляет содержимое —
 * так сотня извещений разбирается без единой перезагрузки страницы.
 */
export function Inspector({
  regNum,
  onClose,
  model = "qwen3.6-35b",
}: {
  regNum: string | null;
  onClose: () => void;
  model?: string;
}) {
  const open = Boolean(regNum);

  const detail = useQuery({
    queryKey: qk.tenders.byId(regNum ?? ""),
    queryFn: ({ signal }) => endpoints.getTender(regNum!, signal),
    enabled: open,
    staleTime: STALE.detail,
  });

  React.useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  const tender = detail.data?.tender;
  const verdicts = (detail.data?.verdicts ?? []) as Verdict[];
  const topVerdict = verdicts.find((v) => v.reasoning) ?? verdicts[0];

  return (
    <aside
      aria-label={ru.tender.tabs.overview}
      aria-hidden={!open}
      className={cn(
        "fixed inset-y-0 right-0 z-40 flex w-full flex-col border-l border-hairline bg-surface",
        "shadow-(--shadow-overlay) transition-transform duration-(--dur-panel) ease-(--ease-enter)",
        "xl:w-120",
        open ? "translate-x-0" : "translate-x-full",
      )}
    >
      <header className="flex items-start gap-3 border-b border-hairline p-5">
        <div className="min-w-0 flex-1">
          {tender ? (
            <>
              <div className="flex items-center gap-2">
                <StatusPill dates={tender} />
                <CopyableMono value={tender.reg_num} label={ru.tender.regNum} />
              </div>
              <h2 className="clamp-2 mt-2 text-h3" title={tender.name ?? undefined}>
                {tender.name ?? "—"}
              </h2>
              <p className="mt-1 font-mono text-body tnum text-text">{money(tender.price)}</p>
            </>
          ) : (
            <div className="flex flex-col gap-2">
              <Skeleton className="h-5 w-32 rounded-full" />
              <Skeleton className="h-5 w-full" />
              <Skeleton className="h-5 w-28" />
            </div>
          )}
        </div>
        <Button variant="ghost" size="icon-sm" aria-label={ru.common.close} onClick={onClose}>
          <X className="h-4 w-4" strokeWidth={1.5} />
        </Button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        {tender ? (
          <>
            <Rail
              published={toDate(tender.publish_date)}
              start={toDate(tender.start_date)}
              deadline={toDate(tender.end_date)}
              previousDeadline={tender.deadline_changed ? toDate(tender.prev_end_date) : null}
              scale="meso"
            />

            <DefinitionList
              columns={1}
              className="mt-6"
              items={[
                { label: ru.tender.customer, value: tender.customer_name },
                { label: ru.tender.inn, value: tender.customer_inn, mono: true },
                { label: ru.tender.okpd2, value: okpd2Label(tender.okpd2_code, tender.okpd2_name), mono: true },
                { label: ru.tender.region, value: regionName(tender.region_code) },
                { label: ru.tender.published, value: dateShort(tender.publish_date) },
                { label: ru.tender.deadline, value: dateShort(tender.end_date) },
                {
                  label: ru.tender.documents,
                  value: `${tender.document_count}`,
                },
              ]}
            />

            {topVerdict ? (
              <div className="mt-6">
                <VerdictNote verdict={topVerdict} model={model} />
              </div>
            ) : null}
          </>
        ) : detail.isError ? (
          <p role="alert" className="text-body-sm text-signal-fg">
            {ru.errors.tenderNotFound(regNum ?? "")}
          </p>
        ) : (
          <div className="flex flex-col gap-6">
            <Skeleton className="h-12 w-full" />
            <TextSkeleton lines={6} />
          </div>
        )}
      </div>

      <footer className="border-t border-hairline p-4">
        <Button asChild variant="primary" className="w-full" disabled={!tender}>
          <Link href={`/tenders/${regNum ?? ""}`}>
            {ru.common.openFull}
            <ExternalLink className="h-4 w-4" strokeWidth={1.5} aria-hidden="true" />
          </Link>
        </Button>
      </footer>
    </aside>
  );
}

function okpd2Label(code: string | null, name: string | null): string | null {
  if (!code) return null;
  return name ? `${code} — ${name}` : code;
}
