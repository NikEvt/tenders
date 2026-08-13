"use client";

import * as React from "react";
import { cn } from "@/shared/lib/cn";

export type SegmentedOption<T extends string> = {
  value: T;
  label: React.ReactNode;
  disabled?: boolean;
  title?: string;
  /** Нужен, когда подпись — иконка. */
  ariaLabel?: string;
};

/**
 * Сегментированный переключатель вместо select там, где вариантов немного и
 * важно видеть их все сразу — сортировка, режим поиска.
 */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  label,
  size = "md",
  className,
}: {
  options: SegmentedOption<T>[];
  value: T;
  onChange: (value: T) => void;
  label: string;
  size?: "sm" | "md";
  className?: string;
}) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={cn(
        "inline-flex items-center gap-0.5 rounded-[6px] border border-hairline bg-surface-sunken p-0.5",
        className,
      )}
    >
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            aria-label={option.ariaLabel}
            disabled={option.disabled}
            title={option.title}
            onClick={() => onChange(option.value)}
            className={cn(
              "rounded-[4px] font-medium transition-colors duration-(--dur-state)",
              size === "sm" ? "h-7 px-2.5 text-body-sm" : "h-8 px-3 text-body-sm",
              active
                ? "bg-surface text-text shadow-[0_1px_2px_rgb(18_21_26_/_0.06)]"
                : "text-text-muted hover:text-text",
              option.disabled && "cursor-not-allowed opacity-40",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
