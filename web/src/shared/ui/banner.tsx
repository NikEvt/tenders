"use client";

import * as React from "react";
import { X } from "lucide-react";
import { cn } from "@/shared/lib/cn";
import { ru } from "@/shared/i18n/ru";

export type BannerTone = "gos" | "oak" | "signal" | "moss";

const TONE: Record<BannerTone, string> = {
  gos: "border-gos-fg/30 surface-gos-tint",
  oak: "border-oak-fg/30 surface-oak-tint",
  signal: "border-signal-fg/30 surface-signal-tint",
  moss: "border-moss-fg/30 surface-moss-tint",
};

/**
 * Полоса состояния над содержимым. Для того, что пользователь должен узнать
 * до того, как начнёт работать: деградация модели, упавшая выгрузка.
 */
export function Banner({
  tone = "oak",
  title,
  body,
  actions,
  onDismiss,
  className,
}: {
  tone?: BannerTone;
  title: string;
  body?: React.ReactNode;
  actions?: React.ReactNode;
  onDismiss?: () => void;
  className?: string;
}) {
  return (
    <div
      role="status"
      className={cn(
        "flex flex-wrap items-center gap-x-3 gap-y-2 rounded-[10px] border px-4 py-3",
        TONE[tone],
        className,
      )}
    >
      <p className="min-w-0 flex-1 text-body-sm text-text">
        <span className="font-medium">{title}</span>
        {body ? <span className="text-text-muted"> {body}</span> : null}
      </p>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
      {onDismiss ? (
        <button
          type="button"
          onClick={onDismiss}
          aria-label={ru.common.close}
          className="rounded-[4px] p-1 text-text-muted hover:text-text"
        >
          <X className="h-4 w-4" strokeWidth={1.5} />
        </button>
      ) : null}
    </div>
  );
}
