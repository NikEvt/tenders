"use client";

import * as React from "react";
import Link from "next/link";
import { cn } from "@/shared/lib/cn";
import { compactMoney, regionName, toDate } from "@/shared/lib/format";
import { ru } from "@/shared/i18n/ru";
import { Rail } from "@/shared/ui/rail/rail";
import { CopyableMono } from "@/shared/ui/mono";
import type { Tender } from "@/shared/api/types";
import { StatusPill } from "./status-pill";

export const ROW_HEIGHT = 72;

export type TenderRowProps = {
  tender: Tender;
  href: string;
  /** Открытие в панели-инспекторе: обычный клик не уводит со списка. */
  onOpen?: (tender: Tender) => void;
  active?: boolean;
  focused?: boolean;
  selected?: boolean;
  onSelectedChange?: (selected: boolean) => void;
  /** Совпадение по критерию ИИ — тот же материал, что и у заметки на полях. */
  matchedByLlm?: boolean;
  verdictSnippet?: string;
  /** Кнопки строки: появляются по наведению и фокусу, композируются снаружи. */
  actions?: React.ReactNode;
  onCopyRegNum?: (value: string) => void;
};

function TenderRowImpl({
  tender,
  href,
  onOpen,
  active,
  focused,
  selected,
  onSelectedChange,
  matchedByLlm,
  verdictSnippet,
  actions,
  onCopyRegNum,
}: TenderRowProps) {
  const handleClick = (event: React.MouseEvent<HTMLAnchorElement>) => {
    // Модификаторы и средняя кнопка остаются за браузером: строка — настоящая ссылка.
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
    if (!onOpen) return;
    event.preventDefault();
    onOpen(tender);
  };

  return (
    <li
      data-row-id={tender.reg_num}
      className={cn(
        "group relative flex items-stretch border-b border-hairline bg-surface",
        "transition-[background-color,box-shadow] duration-(--dur-state)",
        "hover:z-10 hover:shadow-(--shadow-raise)",
        active && "surface-row-active",
        focused && "ring-2 ring-gos-fg ring-inset",
      )}
      style={{ height: ROW_HEIGHT }}
    >
      {matchedByLlm ? (
        <span
          className="absolute left-0 top-0 h-full w-[3px] bg-oak-fg"
          title={verdictSnippet}
          aria-hidden="true"
        />
      ) : null}

      {onSelectedChange ? (
        <span className="flex w-9 shrink-0 items-center justify-center">
          <input
            type="checkbox"
            checked={selected ?? false}
            onChange={(event) => onSelectedChange(event.target.checked)}
            aria-label={tender.name ?? tender.reg_num}
            className={cn(
              "h-4 w-4 cursor-pointer rounded-[4px] border border-border-strong accent-gos-fg",
              !selected && "opacity-0 group-hover:opacity-100 focus-visible:opacity-100",
            )}
          />
        </span>
      ) : null}

      <Link
        href={href}
        onClick={handleClick}
        className="flex min-w-0 flex-1 flex-col justify-center gap-0.5 py-2 pl-4 pr-3 no-underline"
      >
        <span className="flex min-w-0 items-center gap-2.5">
          <StatusPill dates={tender} />
          <span className="min-w-0 flex-1 truncate text-body-sm text-text-muted">
            {tender.customer_name ?? "—"}
          </span>
          <span className="shrink-0 font-mono text-body-sm tnum text-text">
            {compactMoney(tender.price)}
          </span>
        </span>

        <span className="clamp-1 text-body text-text" title={tender.name ?? undefined}>
          {tender.name ?? tender.description ?? "—"}
        </span>

        <span className="flex min-w-0 items-center gap-2 text-body-sm text-text-subtle">
          <span className="min-w-0 truncate">
            {tender.okpd2_code ? `${ru.tender.okpd2} ${tender.okpd2_code} · ` : ""}
            {regionName(tender.region_code)}
            {tender.document_count > 0
              ? ` · ${ru.tender.documentCount.toLowerCase()}: ${tender.document_count}`
              : ""}
          </span>
        </span>
      </Link>

      <span className="flex shrink-0 items-center gap-3 pr-4">
        <CopyableMono
          value={tender.reg_num}
          label={ru.tender.regNum}
          onCopied={onCopyRegNum}
          className="hidden text-[11px] lg:inline-flex"
        />
        <Rail
          published={toDate(tender.publish_date)}
          start={toDate(tender.start_date)}
          deadline={toDate(tender.end_date)}
          previousDeadline={tender.deadline_changed ? toDate(tender.prev_end_date) : null}
          scale="micro"
        />
        {actions ? (
          <span
            className={cn(
              "flex items-center gap-1",
              "opacity-0 transition-opacity duration-(--dur-state)",
              "group-hover:opacity-100 group-focus-within:opacity-100",
            )}
          >
            {actions}
          </span>
        ) : null}
      </span>
    </li>
  );
}

/**
 * Строка не должна перерисовываться, когда меняется состояние инспектора:
 * список из тысячи строк — то место, где это заметно.
 */
export const TenderRow = React.memo(TenderRowImpl);
