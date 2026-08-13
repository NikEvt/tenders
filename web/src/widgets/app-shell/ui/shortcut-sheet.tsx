"use client";

import { Dialog, DialogContent } from "@/shared/ui/dialog";
import { Kbd } from "@/shared/ui/tooltip";
import { ru } from "@/shared/i18n/ru";
import { SHORTCUTS } from "../model/shortcuts";

export function ShortcutSheet({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={ru.help.shortcuts}>
        <ul className="flex flex-col gap-1">
          {SHORTCUTS.map((shortcut) => (
            <li
              key={shortcut.keys}
              className="flex items-center justify-between gap-4 border-b border-hairline py-2 last:border-0"
            >
              <span className="text-body text-text">{shortcut.action}</span>
              <Kbd className="shrink-0">{shortcut.keys}</Kbd>
            </li>
          ))}
        </ul>
      </DialogContent>
    </Dialog>
  );
}
