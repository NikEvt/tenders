"use client";

import * as React from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ChevronDown, ChevronUp, ExternalLink, ScanText } from "lucide-react";
import { Button } from "@/shared/ui/button";
import { Input } from "@/shared/ui/field";
import { Mono } from "@/shared/ui/mono";
import { Pill } from "@/shared/ui/pill";
import { Skeleton, TextSkeleton } from "@/shared/ui/skeleton";
import { Banner } from "@/shared/ui/banner";
import { ru } from "@/shared/i18n/ru";
import { cn } from "@/shared/lib/cn";
import { formatCount } from "@/shared/lib/plural";
import { useDebounced } from "@/shared/lib/hooks";
import { endpoints } from "@/shared/api/endpoints";
import { qk, STALE } from "@/shared/api/query-keys";
import type { ChunkOutline } from "@/shared/api/types";
import { findMatches, sanitizeText, segments, splitForRender } from "../lib/sanitize";

// Якоря длиннее строки не нужны: этого хватает, чтобы попасть в нужное место,
// и мало, чтобы поисковая строка стала нечитаемой.
const ANCHOR_CHARS = 80;

/**
 * Просмотрщик извлечённого текста.
 *
 * Приходить сюда принято по цитате из вердикта. Границы чанка API отдаёт
 * (`GET /documents/{id}/chunks`), поэтому нужное место находится точно: по
 * смещениям вырезается фрагмент исходного текста, и подсветка ставится по нему.
 *
 * Искать именно по тексту, а не по смещениям в отрисованном документе: перед
 * показом текст санируется и разбивается на абзацы, из-за чего абсолютные
 * позиции съезжают. Текст — устойчивый якорь, смещение — нет.
 */
export function DocumentViewer({
  regNum,
  documentId,
  chunkId,
}: {
  regNum: string;
  documentId: number;
  chunkId: number | null;
}) {
  const [needle, setNeedle] = React.useState("");
  const [current, setCurrent] = React.useState(0);
  const debounced = useDebounced(needle, 200);
  const searchRef = React.useRef<HTMLInputElement>(null);

  const text = useQuery({
    queryKey: qk.documents.text(documentId),
    queryFn: ({ signal }) => endpoints.documentText(documentId, signal),
    staleTime: STALE.documentText,
  });

  const download = useQuery({
    queryKey: qk.documents.download(documentId),
    queryFn: ({ signal }) => endpoints.documentDownload(documentId, signal),
    staleTime: 30 * 60_000,
  });

  const chunks = useQuery({
    queryKey: qk.documents.chunks(documentId),
    queryFn: ({ signal }) => endpoints.documentChunks(documentId, signal),
    staleTime: STALE.documentText,
  });

  const target = React.useMemo(
    () => chunks.data?.chunks.find((chunk) => chunk.chunk_id === chunkId) ?? null,
    [chunks.data, chunkId],
  );

  // Якорь для подсветки: начало фрагмента, вырезанное по смещениям из
  // исходного текста. Целый чанк в поисковую строку не годится — он длиной
  // в пару тысяч символов.
  const anchor = React.useMemo(() => {
    if (!target || target.char_start === null || target.char_end === null) return null;
    if (!text.data) return null;
    return text.data.content.slice(target.char_start, target.char_end).trim().slice(0, ANCHOR_CHARS);
  }, [target, text.data]);

  React.useEffect(() => {
    if (anchor) setNeedle(anchor);
  }, [anchor]);

  const clean = React.useMemo(
    () => (text.data ? sanitizeText(text.data.content) : ""),
    [text.data],
  );
  const parts = React.useMemo(() => splitForRender(clean), [clean]);
  const matchCount = React.useMemo(
    () => findMatches(clean, debounced).length,
    [clean, debounced],
  );

  // Ctrl+F перехватываем: искать нужно по тексту документа, а не по странице,
  // где видна только часть чанков.
  React.useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "f") {
        event.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  React.useEffect(() => setCurrent(0), [debounced]);

  React.useEffect(() => {
    if (!debounced || matchCount === 0) return;
    const marks = document.querySelectorAll("[data-match]");
    marks[current]?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [current, debounced, matchCount]);

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button asChild variant="quiet" size="sm">
          <Link href={`/tenders/${regNum}`}>
            <ArrowLeft className="h-4 w-4" strokeWidth={1.5} aria-hidden="true" />
            {ru.common.back}
          </Link>
        </Button>

        <div className="flex items-center gap-2">
          <div className="relative">
            <Input
              ref={searchRef}
              value={needle}
              onChange={(event) => setNeedle(event.target.value)}
              placeholder={ru.documents.searchInDocument}
              aria-label={ru.documents.searchInDocument}
              className="h-9 w-64 pr-24"
            />
            {debounced ? (
              <span className="absolute right-2 top-1/2 flex -translate-y-1/2 items-center gap-1">
                <span className="text-body-sm tnum text-text-muted">
                  {matchCount ? ru.documents.matches(current + 1, matchCount) : "0"}
                </span>
                <Button
                  size="icon-sm"
                  variant="ghost"
                  aria-label="Предыдущее совпадение"
                  disabled={matchCount === 0}
                  onClick={() => setCurrent((i) => (i - 1 + matchCount) % matchCount)}
                >
                  <ChevronUp className="h-3.5 w-3.5" strokeWidth={1.5} />
                </Button>
                <Button
                  size="icon-sm"
                  variant="ghost"
                  aria-label="Следующее совпадение"
                  disabled={matchCount === 0}
                  onClick={() => setCurrent((i) => (i + 1) % matchCount)}
                >
                  <ChevronDown className="h-3.5 w-3.5" strokeWidth={1.5} />
                </Button>
              </span>
            ) : null}
          </div>

          {/*
            Копий вложений система не хранит: она извлекает текст, а оригинал
            остаётся в ЕИС. Поэтому ссылка внешняя и бессрочная — `expires_in`
            равен нулю не потому, что истекла, а потому что сроком её жизни
            распоряжаемся не мы. Слова про «временную ссылку» здесь были бы
            неправдой, а иконка загрузки обещала бы файл с нашего сервера.
          */}
          {download.data ? (
            <Button asChild variant="secondary" size="sm">
              <a href={download.data.url} target="_blank" rel="noopener noreferrer">
                <ExternalLink className="h-4 w-4" strokeWidth={1.5} aria-hidden="true" />
                {ru.documents.openInEis}
              </a>
            </Button>
          ) : (
            <p className="text-caption text-text-subtle">{ru.documents.noOriginal}</p>
          )}
        </div>
      </div>

      <header className="flex flex-wrap items-center gap-3 border-b border-hairline pb-4">
        <h1 className="text-h2">{download.data?.file_name ?? ru.documents.title}</h1>
        {text.data ? (
          <Pill tone="neutral">
            <ScanText className="h-3 w-3" strokeWidth={1.5} aria-hidden="true" />
            {formatCount(text.data.char_count)} симв.
          </Pill>
        ) : null}
      </header>

      {chunkId !== null && anchor ? (
        <Banner
          tone="moss"
          title={`Фрагмент #${chunkId}${target?.page ? `, стр. ${target.page}` : ""} подсвечен в тексте.`}
          body="Место найдено по границам фрагмента, а не поиском наугад."
        />
      ) : chunkId !== null && chunks.data ? (
        <Banner
          tone="oak"
          title={`Переход к фрагменту #${chunkId}.`}
          // Честнее сказать, что подсветить нечем, чем подсветить не то место.
          body="Границы этого фрагмента неизвестны: он нарезан до того, как смещения начали сохраняться. Найдите нужное место поиском по документу."
        />
      ) : null}

      <div className="flex gap-8">
        <article className="min-w-0 flex-1">
          {text.isLoading ? (
            <TextSkeleton lines={20} />
          ) : text.isError ? (
            <p role="alert" className="text-body text-signal-fg">
              Текст документа не извлечён. Проверьте состояние обработки документов.
            </p>
          ) : (
            <div className="measure flex flex-col gap-4 text-body leading-[1.73]">
              {parts.map((part, index) => (
                <Part key={index} text={part} needle={debounced} />
              ))}
            </div>
          )}
        </article>

        <aside className="hidden w-56 shrink-0 lg:block">
          <p className="text-caption uppercase text-text-muted">{ru.documents.chunks}</p>
          <ChunkMap
            chunks={chunks.data?.chunks ?? []}
            activeId={chunkId}
            totalChars={text.data?.char_count ?? 0}
          />
          <Mono className="mt-4 block break-all">
            {download.data ? `document_id=${documentId}` : null}
          </Mono>
        </aside>
      </div>
    </div>
  );
}

/** Кусок текста с подсветкой. Узлы React, не HTML. */
function Part({ text, needle }: { text: string; needle: string }) {
  const pieces = React.useMemo(
    () => segments(text, findMatches(text, needle)),
    [text, needle],
  );

  return (
    <p className="whitespace-pre-wrap">
      {pieces.map((piece, index) =>
        piece.match ? (
          <mark
            key={index}
            data-match
            className={cn("rounded-[3px] surface-oak-tint px-0.5")}
          >
            {piece.text}
          </mark>
        ) : (
          <React.Fragment key={index}>{piece.text}</React.Fragment>
        ),
      )}
    </p>
  );
}

export function DocumentViewerSkeleton() {
  return (
    <div className="flex flex-col gap-5">
      <Skeleton className="h-9 w-40" />
      <Skeleton className="h-7 w-96" />
      <TextSkeleton lines={18} />
    </div>
  );
}


/**
 * Схема границ фрагментов: где каждый лежит в документе.
 *
 * Фрагменты без смещений в схему не попадают — рисовать их в произвольном
 * месте значило бы врать о структуре документа.
 */
function ChunkMap({
  chunks,
  activeId,
  totalChars,
}: {
  chunks: ChunkOutline[];
  activeId: number | null;
  totalChars: number;
}) {
  const placed = chunks.filter((c) => c.char_start !== null && c.char_end !== null);

  if (!placed.length) {
    return (
      <p className="mt-2 text-body-sm text-text-subtle">
        {chunks.length
          ? "Границы фрагментов неизвестны: документ нарезан до того, как смещения начали сохраняться."
          : "Документ ещё не нарезан на фрагменты."}
      </p>
    );
  }

  return (
    <ol className="mt-2 flex flex-col gap-1" aria-label={ru.documents.chunks}>
      {placed.map((chunk) => {
        const share = totalChars ? ((chunk.char_end! - chunk.char_start!) / totalChars) * 100 : 0;
        const active = chunk.chunk_id === activeId;
        return (
          <li key={chunk.chunk_id} className="flex items-center gap-2">
            <span className="tnum w-6 text-caption text-text-subtle">{chunk.ordinal + 1}</span>
            <span className="h-1.5 flex-1 overflow-hidden rounded-[1px] bg-hairline">
              <span
                className={cn("block h-full", active ? "bg-gos-fg" : "bg-border-strong")}
                style={{ width: `${Math.max(4, share)}%` }}
              />
            </span>
            {chunk.page ? (
              <span className="tnum w-8 text-right text-caption text-text-subtle">
                {chunk.page}
              </span>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}
