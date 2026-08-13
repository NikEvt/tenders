"use client";

import * as React from "react";
import * as RadixPopover from "@radix-ui/react-popover";
import { cn } from "@/shared/lib/cn";

export const Popover = RadixPopover.Root;
export const PopoverTrigger = RadixPopover.Trigger;
export const PopoverClose = RadixPopover.Close;

export function PopoverContent({
  className,
  align = "start",
  sideOffset = 6,
  ...props
}: React.ComponentPropsWithoutRef<typeof RadixPopover.Content>) {
  return (
    <RadixPopover.Portal>
      <RadixPopover.Content
        align={align}
        sideOffset={sideOffset}
        className={cn(
          "z-50 rounded-[14px] border border-hairline bg-surface p-4 shadow-(--shadow-overlay)",
          "origin-(--radix-popover-content-transform-origin)",
          "data-[state=open]:animate-in data-[state=closed]:animate-out",
          className,
        )}
        {...props}
      />
    </RadixPopover.Portal>
  );
}
