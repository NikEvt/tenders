"use client";

import * as React from "react";
import * as RadixDialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { cn } from "@/shared/lib/cn";
import { ru } from "@/shared/i18n/ru";

export const Dialog = RadixDialog.Root;
export const DialogTrigger = RadixDialog.Trigger;
export const DialogClose = RadixDialog.Close;

export function DialogContent({
  title,
  description,
  className,
  children,
  ...props
}: React.ComponentPropsWithoutRef<typeof RadixDialog.Content> & {
  title: string;
  description?: string;
}) {
  return (
    <RadixDialog.Portal>
      <RadixDialog.Overlay className="fixed inset-0 z-50 bg-scrim data-[state=open]:animate-in" />
      <RadixDialog.Content
        className={cn(
          "fixed left-1/2 top-1/2 z-50 w-[min(640px,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2",
          "max-h-[85vh] overflow-auto rounded-[14px] border border-hairline bg-surface p-6",
          "shadow-(--shadow-overlay)",
          className,
        )}
        {...props}
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <RadixDialog.Title className="text-h2">{title}</RadixDialog.Title>
            {description ? (
              <RadixDialog.Description className="mt-1 text-body-sm text-text-muted">
                {description}
              </RadixDialog.Description>
            ) : null}
          </div>
          <RadixDialog.Close
            aria-label={ru.common.close}
            className="-mr-1 -mt-1 rounded-[6px] p-1 text-text-subtle hover:bg-surface-sunken hover:text-text"
          >
            <X className="h-5 w-5" strokeWidth={1.5} />
          </RadixDialog.Close>
        </div>
        {children}
      </RadixDialog.Content>
    </RadixDialog.Portal>
  );
}
