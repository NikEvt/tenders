import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/shared/lib/cn";

/**
 * Статусная пилюля: подложка — 8% оттенка, текст — полная насыщенность.
 * Цвет никогда не единственный носитель смысла: у каждой пилюли есть слово.
 */
const pill = cva(
  "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium uppercase tracking-[0.04em] whitespace-nowrap",
  {
    variants: {
      tone: {
        gos: "surface-gos-tint",
        oak: "surface-oak-tint",
        moss: "surface-moss-tint",
        signal: "surface-signal-tint",
        neutral: "bg-canvas text-text-muted",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export type PillTone = NonNullable<VariantProps<typeof pill>["tone"]>;

export type PillProps = React.HTMLAttributes<HTMLSpanElement> &
  VariantProps<typeof pill> & { dot?: boolean };

export function Pill({ tone, dot, className, children, ...props }: PillProps) {
  return (
    <span className={cn(pill({ tone }), className)} {...props}>
      {dot ? <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" /> : null}
      {children}
    </span>
  );
}
