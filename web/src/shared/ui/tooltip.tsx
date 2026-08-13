"use client";

import * as React from "react";
import * as RadixTooltip from "@radix-ui/react-tooltip";
import { cn } from "@/shared/lib/cn";

export const TooltipProvider = RadixTooltip.Provider;

export function Tooltip({
  content,
  /** Сочетание клавиш показывается прямо в подсказке (§7.1). */
  shortcut,
  side = "top",
  children,
  className,
}: {
  content: React.ReactNode;
  shortcut?: string;
  side?: "top" | "right" | "bottom" | "left";
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <RadixTooltip.Root>
      <RadixTooltip.Trigger asChild>{children}</RadixTooltip.Trigger>
      <RadixTooltip.Portal>
        <RadixTooltip.Content
          side={side}
          sideOffset={6}
          className={cn(
            "z-50 max-w-80 rounded-[6px] border border-hairline bg-surface px-2.5 py-1.5",
            "text-body-sm text-text shadow-(--shadow-overlay)",
            "data-[state=delayed-open]:animate-in",
            className,
          )}
        >
          <span className="flex items-center gap-2">
            <span>{content}</span>
            {shortcut ? <Kbd>{shortcut}</Kbd> : null}
          </span>
        </RadixTooltip.Content>
      </RadixTooltip.Portal>
    </RadixTooltip.Root>
  );
}

export function Kbd({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <kbd
      className={cn(
        "rounded-[4px] border border-hairline bg-surface-sunken px-1.5 py-0.5",
        "font-mono text-[11px] leading-4 text-text-muted",
        className,
      )}
    >
      {children}
    </kbd>
  );
}
