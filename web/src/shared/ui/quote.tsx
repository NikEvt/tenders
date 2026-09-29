import * as React from "react";
import { cn } from "@/shared/lib/cn";

/**
 * Цитата с выделенным совпадением.
 *
 * Совпадение обязано остаться видимым — в этом весь смысл. При разборе прогона
 * ХПК/БПК печатались первые 155 символов цитаты, то есть один левый контекст, а
 * искомое слово оставалось за кадром; по таким превью было сделано несколько
 * неверных выводов, пока это не заметили.
 *
 * Отсюда два правила, и оба здесь, а не в вызывающем коде: подсветка и обрезка
 * **вокруг** совпадения, а не от начала строки. Вставлять `<mark>` руками в
 * каждом из трёх мест, где показываются цитаты, — заплатка вместо механизма.
 */

/** Сколько символов контекста оставлять с каждой стороны при обрезке. */
export const DEFAULT_CONTEXT = 90;

export type QuoteSpan = {
  quote: string;
  match_start: number;
  match_end: number;
};

type Trimmed = {
  before: string;
  match: string;
  after: string;
  cutStart: boolean;
  cutEnd: boolean;
};

/**
 * Режет цитату так, чтобы совпадение осталось в кадре.
 *
 * Экспортируется ради теста: правило «совпадение видно при любой длине» —
 * то, что здесь на самом деле проверяется.
 */
export function trimAroundMatch(
  { quote, match_start, match_end }: QuoteSpan,
  context: number = DEFAULT_CONTEXT,
): Trimmed {
  // Границы могли приехать битыми (старая запись, обрезанный текст) — тогда
  // показываем цитату целиком, но не роняем экран.
  const start = Math.max(0, Math.min(match_start, quote.length));
  const end = Math.max(start, Math.min(match_end, quote.length));

  const from = Math.max(0, start - context);
  const to = Math.min(quote.length, end + context);

  return {
    before: quote.slice(from, start),
    match: quote.slice(start, end),
    after: quote.slice(end, to),
    cutStart: from > 0,
    cutEnd: to < quote.length,
  };
}

export function Quote({
  span,
  context = DEFAULT_CONTEXT,
  className,
}: {
  span: QuoteSpan;
  context?: number;
  className?: string;
}) {
  const { before, match, after, cutStart, cutEnd } = trimAroundMatch(span, context);

  return (
    <q className={cn("text-body-sm text-text-muted", className)}>
      {cutStart ? <span aria-hidden="true">… </span> : null}
      {before}
      {match ? (
        <mark className="surface-oak-tint rounded-[3px] px-0.5 font-medium">{match}</mark>
      ) : null}
      {after}
      {cutEnd ? <span aria-hidden="true"> …</span> : null}
    </q>
  );
}
