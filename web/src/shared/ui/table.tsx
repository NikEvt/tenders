import * as React from "react";
import { cn } from "@/shared/lib/cn";

/**
 * Таблица читается как документ: только горизонтальные линейки, без сетки и без
 * зебры — полосы спорят с линейками и обе перестают работать.
 */
export function Table({ className, ...props }: React.TableHTMLAttributes<HTMLTableElement>) {
  return (
    <div className="w-full overflow-x-auto">
      <table className={cn("w-full border-collapse text-body-sm", className)} {...props} />
    </div>
  );
}

export function THead({ className, ...props }: React.HTMLAttributes<HTMLTableSectionElement>) {
  return (
    <thead
      className={cn("sticky top-0 z-10 bg-surface [&_th]:border-b [&_th]:border-hairline", className)}
      {...props}
    />
  );
}

export function TH({
  className,
  numeric,
  ...props
}: React.ThHTMLAttributes<HTMLTableCellElement> & { numeric?: boolean }) {
  return (
    <th
      scope={props.scope ?? "col"}
      className={cn(
        "px-3 py-2 text-caption font-medium uppercase text-text-muted",
        numeric ? "text-right" : "text-left",
        className,
      )}
      {...props}
    />
  );
}

export function TBody({ className, ...props }: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody className={cn("", className)} {...props} />;
}

export function TR({ className, ...props }: React.HTMLAttributes<HTMLTableRowElement>) {
  return (
    <tr
      className={cn(
        "border-b border-hairline transition-colors duration-(--dur-state) hover:bg-surface-sunken",
        className,
      )}
      {...props}
    />
  );
}

export function TD({
  className,
  numeric,
  ...props
}: React.TdHTMLAttributes<HTMLTableCellElement> & { numeric?: boolean }) {
  return (
    <td
      className={cn(
        "h-12 px-3 align-middle",
        numeric && "text-right font-mono tnum",
        className,
      )}
      {...props}
    />
  );
}
