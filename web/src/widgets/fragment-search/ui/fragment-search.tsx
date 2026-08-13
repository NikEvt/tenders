"use client";

import * as React from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { parseAsString, parseAsStringLiteral, useQueryStates } from "nuqs";
import { FileSearch, Search } from "lucide-react";
import { Button } from "@/shared/ui/button";
import { Card } from "@/shared/ui/card";
import { EmptyState } from "@/shared/ui/empty-state";
import { Input } from "@/shared/ui/field";
import { Segmented } from "@/shared/ui/segmented";
import { ListSkeleton } from "@/shared/ui/skeleton";
import { CopyableMono } from "@/shared/ui/mono";
import { ru } from "@/shared/i18n/ru";
import { compactMoney } from "@/shared/lib/format";
import { formatCount } from "@/shared/lib/plural";
import { useDebounced } from "@/shared/lib/hooks";
import { endpoints } from "@/shared/api/endpoints";
import { STALE } from "@/shared/api/query-keys";
import type { Fragment, FragmentPage } from "@/shared/api/types";

const MODES = ["lexical", "semantic", "rrf"] as const;
const PAGE_SIZE = 20;

/**
 * Поиск по документам (§5.5 брифа).
 *
 * Единица результата — фрагмент, а не закупка: человек ищет формулировку
 * («гарантия не менее трёх лет») и должен увидеть саму фразу в её окружении,
 * а не карточку, внутри которой она где-то есть.
 */
export function FragmentSearch() {
  const [params, setParams] = useQueryStates(
    {
      q: parseAsString.withDefault(""),
      mode: parseAsStringLiteral(MODES).withDefault("rrf"),
    },
    { history: "push", clearOnDefault: true },
  );

  const debounced = useDebounced(params.q, 400);
  const ready = debounced.trim().length >= 2;

  const results = useQuery<FragmentPage>({
    queryKey: ["fragments", debounced, params.mode],
    queryFn: ({ signal }) =>
      endpoints.searchFragments(
        { q: debounced, mode: params.mode, page: 0, page_size: PAGE_SIZE },
        signal,
      ),
    enabled: ready,
    staleTime: STALE.list,
  });

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-0 flex-1">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-subtle"
            strokeWidth={1.5}
            aria-hidden="true"
          />
          <Input
            value={params.q}
            onChange={(event) => setParams({ q: event.target.value })}
            placeholder={ru.search.placeholder}
            aria-label={ru.search.placeholder}
            className="h-11 pl-9"
          />
        </div>
        <Segmented
          label="Режим поиска"
          value={params.mode}
          onChange={(mode) => setParams({ mode })}
          options={[
            { value: "lexical", label: ru.search.modeLexical },
            { value: "semantic", label: ru.search.modeSemantic },
            { value: "rrf", label: ru.search.modeHybrid },
          ]}
        />
      </div>

      {!ready ? (
        <EmptyState
          icon={<FileSearch strokeWidth={1.5} />}
          title={ru.search.title}
          body="Ищет по тексту приложенной документации: часть требований звучит только в ТЗ и в наименование извещения не попадает."
        />
      ) : results.isLoading ? (
        <ListSkeleton rows={6} />
      ) : (results.data?.items.length ?? 0) === 0 ? (
        <EmptyState
          icon={<FileSearch strokeWidth={1.5} />}
          title={ru.search.emptyTitle}
          body={
            params.mode === "semantic"
              ? "Векторный режим ищет по смыслу и требует посчитанных эмбеддингов. Попробуйте лексический или гибридный."
              : ru.search.emptyBody
          }
        />
      ) : (
        <>
          <p className="text-body-sm text-text-muted" aria-live="polite">
            {ru.catalog.found(0).replace("0", formatCount(results.data?.total ?? 0))}
          </p>
          <ul className="flex flex-col gap-3">
            {results.data?.items.map((fragment) => (
              <li key={fragment.chunk_id}>
                <FragmentCard fragment={fragment} />
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function FragmentCard({ fragment }: { fragment: Fragment }) {
  return (
    <Card className="flex flex-col gap-3 p-4">
      <div className="flex items-start gap-4">
        <div className="min-w-0 flex-1">
          <Link
            href={`/tenders/${fragment.reg_num}`}
            className="clamp-2 text-body font-medium text-text no-underline hover:text-gos-fg"
          >
            {fragment.tender_name ?? fragment.reg_num}
          </Link>
          <p className="mt-1 text-body-sm text-text-muted">
            {fragment.document_name ?? "документ без имени"}
          </p>
        </div>
        <span className="shrink-0 font-mono text-body tnum">
          {compactMoney(fragment.tender_price)}
        </span>
      </div>

      <p className="measure text-body-sm text-text">
        <Highlighted text={fragment.text} spans={fragment.highlights} />
      </p>

      <div className="flex flex-wrap items-center gap-3">
        <CopyableMono value={fragment.reg_num} label={ru.tender.regNum} />
        <Scores scores={fragment.scores} />
        <span className="ml-auto flex gap-2">
          <Button asChild size="sm" variant="ghost">
            <Link
              href={
                fragment.char_start !== null
                  ? `/tenders/${fragment.reg_num}/documents/${fragment.document_id}?from=${fragment.char_start}&to=${fragment.char_end}`
                  : `/tenders/${fragment.reg_num}/documents/${fragment.document_id}`
              }
            >
              Открыть в документе
            </Link>
          </Button>
          <Button asChild size="sm" variant="ghost">
            <Link href={`/tenders/${fragment.reg_num}`}>{ru.search.openTender}</Link>
          </Button>
        </span>
      </div>
    </Card>
  );
}

/**
 * Разложение оценки.
 *
 * `null` у источника означает «этот поиск фрагмент не выдал», а не «оценка
 * ноль» — по этому и видно, чем именно он найден.
 */
function Scores({ scores }: { scores: Fragment["scores"] }) {
  const parts = [
    scores.lexical !== null ? `лексика ${scores.lexical.toFixed(3)}` : null,
    scores.vector !== null ? `вектор ${scores.vector.toFixed(3)}` : null,
  ].filter(Boolean);

  return (
    <span className="font-mono text-[11px] tnum text-text-subtle">
      {parts.length ? `${parts.join(" · ")} · ` : ""}
      итог {scores.rrf.toFixed(4)}
    </span>
  );
}

/** Подсветка совпадений по смещениям, посчитанным сервером. */
function Highlighted({ text, spans }: { text: string; spans: [number, number][] }) {
  if (!spans.length) return <>{text}</>;

  const pieces: React.ReactNode[] = [];
  let cursor = 0;
  spans.forEach(([start, end], index) => {
    if (start < cursor) return;
    if (start > cursor) pieces.push(text.slice(cursor, start));
    pieces.push(
      <mark key={index} className="rounded-[2px] surface-oak-tint px-0.5">
        {text.slice(start, end)}
      </mark>,
    );
    cursor = end;
  });
  if (cursor < text.length) pieces.push(text.slice(cursor));

  return <>{pieces}</>;
}
