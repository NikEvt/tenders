import * as React from "react";
import { cn } from "@/shared/lib/cn";

export function PageHeader({
  title,
  meta,
  actions,
  display,
  className,
  children,
}: {
  title: string;
  meta?: React.ReactNode;
  actions?: React.ReactNode;
  /** Крупный кегль — только на сводке дня. */
  display?: boolean;
  className?: string;
  children?: React.ReactNode;
}) {
  return (
    <header className={cn("flex flex-col gap-2", className)}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <h1 className={display ? "text-display" : "text-h1"}>{title}</h1>
        {actions ? <div className="flex items-center gap-2 no-print">{actions}</div> : null}
      </div>
      {meta ? <div className="text-body-sm text-text-muted">{meta}</div> : null}
      {children}
    </header>
  );
}

export function SectionHeading({
  title,
  count,
  actions,
  className,
}: {
  title: string;
  count?: number;
  actions?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex items-center justify-between gap-4", className)}>
      <h2 className="flex items-center gap-2 text-h2">
        {title}
        {count !== undefined ? (
          <span className="rounded-full bg-canvas px-2 py-0.5 text-caption tnum text-text-muted">
            {count}
          </span>
        ) : null}
      </h2>
      {actions}
    </div>
  );
}
