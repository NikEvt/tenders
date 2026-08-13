"use client";

import * as React from "react";
import * as RadixToast from "@radix-ui/react-toast";
import { X } from "lucide-react";
import { cn } from "@/shared/lib/cn";
import { ru } from "@/shared/i18n/ru";

export type ToastItem = {
  id: string;
  title: string;
  body?: string;
  tone?: "neutral" | "moss" | "signal";
  /** Действие отмены выполняет обратную мутацию, а не правку кеша. */
  undo?: () => void;
};

type ToastApi = {
  show: (toast: Omit<ToastItem, "id">) => void;
};

const ToastContext = React.createContext<ToastApi | null>(null);

/** Тосты нужны только для того, чего не видно на экране (§7.5). */
export function useToast(): ToastApi {
  const api = React.useContext(ToastContext);
  if (!api) throw new Error("useToast вызван вне ToastProvider");
  return api;
}

const MAX_STACK = 3;
const DURATION_MS = 6000;

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = React.useState<ToastItem[]>([]);

  const show = React.useCallback((toast: Omit<ToastItem, "id">) => {
    setItems((prev) => [...prev, { ...toast, id: crypto.randomUUID() }].slice(-MAX_STACK));
  }, []);

  const dismiss = React.useCallback((id: string) => {
    setItems((prev) => prev.filter((item) => item.id !== id));
  }, []);

  const api = React.useMemo(() => ({ show }), [show]);

  return (
    <ToastContext.Provider value={api}>
      <RadixToast.Provider duration={DURATION_MS} swipeDirection="left">
        {children}
        {items.map((item) => (
          <RadixToast.Root
            key={item.id}
            onOpenChange={(open) => !open && dismiss(item.id)}
            className={cn(
              "flex items-start gap-3 rounded-[10px] border bg-surface px-4 py-3 shadow-(--shadow-overlay)",
              "data-[state=open]:animate-in data-[swipe=end]:animate-out",
              item.tone === "moss" && "border-moss-tint",
              item.tone === "signal" && "border-signal-tint",
              (!item.tone || item.tone === "neutral") && "border-hairline",
            )}
          >
            <div className="min-w-0 flex-1">
              <RadixToast.Title className="text-body-sm font-medium text-text">
                {item.title}
              </RadixToast.Title>
              {item.body ? (
                <RadixToast.Description className="mt-0.5 text-body-sm text-text-muted">
                  {item.body}
                </RadixToast.Description>
              ) : null}
            </div>
            {item.undo ? (
              <RadixToast.Action asChild altText={ru.common.cancel}>
                <button
                  type="button"
                  onClick={item.undo}
                  className="shrink-0 text-body-sm font-medium text-gos-fg hover:underline"
                >
                  {ru.common.cancel}
                </button>
              </RadixToast.Action>
            ) : null}
            <RadixToast.Close
              aria-label={ru.common.close}
              className="shrink-0 text-text-subtle hover:text-text"
            >
              <X className="h-4 w-4" strokeWidth={1.5} />
            </RadixToast.Close>
          </RadixToast.Root>
        ))}
        <RadixToast.Viewport className="fixed bottom-4 left-4 z-[60] flex w-90 max-w-[calc(100vw-2rem)] flex-col gap-2 outline-none" />
      </RadixToast.Provider>
    </ToastContext.Provider>
  );
}
