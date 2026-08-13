"use client";

import * as React from "react";
import { Check, Copy } from "lucide-react";
import { cn } from "@/shared/lib/cn";
import { ru } from "@/shared/i18n/ru";

export function Mono({ className, ...props }: React.HTMLAttributes<HTMLSpanElement>) {
  return (
    <span className={cn("font-mono text-mono tnum text-text-muted", className)} {...props} />
  );
}

/**
 * Идентификаторы — реестровый номер, ИНН, message_id — копируются кликом.
 * Группировки разрядов нет: это не числа, а коды.
 */
export function CopyableMono({
  value,
  label,
  className,
  onCopied,
}: {
  value: string;
  label?: string;
  className?: string;
  onCopied?: (value: string) => void;
}) {
  const [copied, setCopied] = React.useState(false);

  const copy = React.useCallback(
    async (event: React.MouseEvent | React.KeyboardEvent) => {
      event.stopPropagation();
      event.preventDefault();
      try {
        await navigator.clipboard.writeText(value);
        setCopied(true);
        onCopied?.(value);
        window.setTimeout(() => setCopied(false), 1600);
      } catch {
        // Буфер недоступен (нет https или прав) — молча оставляем текст выделяемым.
      }
    },
    [value, onCopied],
  );

  return (
    <button
      type="button"
      onClick={copy}
      title={label ?? value}
      aria-label={`${label ?? value}. ${ru.common.copy}`}
      className={cn(
        "group inline-flex items-center gap-1 rounded-[4px] font-mono text-mono tnum",
        "text-text-muted hover:text-text",
        className,
      )}
    >
      {value}
      {copied ? (
        <Check className="h-3 w-3 text-moss-fg" strokeWidth={1.5} aria-hidden="true" />
      ) : (
        <Copy
          className="h-3 w-3 opacity-0 transition-opacity group-hover:opacity-60 group-focus-visible:opacity-60"
          strokeWidth={1.5}
          aria-hidden="true"
        />
      )}
    </button>
  );
}
