"use client";

import * as React from "react";
import { X } from "lucide-react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/shared/lib/cn";
import { ru } from "@/shared/i18n/ru";

const chip = cva(
  "inline-flex max-w-full items-center gap-1.5 rounded-[6px] border px-2 py-1 text-body-sm",
  {
    variants: {
      kind: {
        /** Структурное условие — официальный синий: это уйдёт в SQL. */
        structural: "border-gos-tint surface-gos-tint",
        /** Семантический запрос — нейтральный, в кавычках. */
        semantic: "border-hairline bg-surface-sunken text-text",
        /** Критерий для судьи — та же бумага, что и вердикт. */
        llm: "border-vellum-edge surface-vellum",
      },
    },
    defaultVariants: { kind: "structural" },
  },
);

export type ChipProps = VariantProps<typeof chip> & {
  children: React.ReactNode;
  onRemove?: () => void;
  removeLabel?: string;
  className?: string;
  title?: string;
};

/**
 * Разобранный запрос показывается чипами: интерпретация модели видна целиком
 * и снимается по частям одним кликом.
 */
export function Chip({ kind, children, onRemove, removeLabel, className, title }: ChipProps) {
  return (
    <span className={cn(chip({ kind }), className)} title={title}>
      <span className="truncate">{children}</span>
      {onRemove ? (
        <button
          type="button"
          onClick={onRemove}
          aria-label={removeLabel ?? ru.catalog.removeCondition}
          className="shrink-0 rounded-[3px] opacity-60 hover:opacity-100"
        >
          <X className="h-3.5 w-3.5" strokeWidth={1.5} />
        </button>
      ) : null}
    </span>
  );
}
