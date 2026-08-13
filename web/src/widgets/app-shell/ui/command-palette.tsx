"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Command } from "cmdk";
import * as RadixDialog from "@radix-ui/react-dialog";
import { ru } from "@/shared/i18n/ru";
import { useRecentTenders } from "@/shared/lib/recent-tenders";
import { cn } from "@/shared/lib/cn";
import { NAV } from "../model/nav";

const REG_NUM = /^\d{19}$/;

/**
 * Командная строка. Реестровый номер из 19 цифр распознаётся отдельно и всегда
 * идёт первым результатом: чаще всего его вставляют из письма.
 */
export function CommandPalette({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const router = useRouter();
  const [query, setQuery] = React.useState("");
  const { recent } = useRecentTenders();

  const go = (href: string, newTab = false) => {
    onOpenChange(false);
    setQuery("");
    if (newTab) window.open(href, "_blank", "noopener");
    else router.push(href);
  };

  const looksLikeRegNum = REG_NUM.test(query.trim());

  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="fixed inset-0 z-50 bg-scrim" />
        <RadixDialog.Content
          aria-label={ru.keyboard.palette}
          className={cn(
            "fixed left-1/2 top-[12vh] z-50 w-[min(640px,calc(100vw-2rem))] -translate-x-1/2",
            "overflow-hidden rounded-[14px] border border-hairline bg-surface shadow-(--shadow-overlay)",
          )}
        >
          <RadixDialog.Title className="sr-only">{ru.keyboard.palette}</RadixDialog.Title>
          <Command
            loop
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
                event.preventDefault();
              }
            }}
          >
            <Command.Input
              value={query}
              onValueChange={setQuery}
              placeholder={ru.keyboard.palettePlaceholder}
              className="h-14 w-full border-b border-hairline bg-transparent px-4 text-body text-text outline-none placeholder:text-text-subtle"
            />
            <Command.List className="max-h-[52vh] overflow-y-auto p-2">
              <Command.Empty className="px-3 py-6 text-center text-body-sm text-text-muted">
                {ru.keyboard.paletteEmpty}
              </Command.Empty>

              {looksLikeRegNum ? (
                <Command.Group
                  heading={ru.keyboard.paletteRegNum}
                  className="[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-caption [&_[cmdk-group-heading]]:text-text-muted"
                >
                  <Item onSelect={() => go(`/tenders/${query.trim()}`)}>
                    <span className="font-mono text-mono">{query.trim()}</span>
                  </Item>
                </Command.Group>
              ) : null}

              <Command.Group
                heading={ru.keyboard.paletteRoutes}
                className="[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-caption [&_[cmdk-group-heading]]:text-text-muted"
              >
                {NAV.map((item) => (
                  <Item key={item.href} value={item.label} onSelect={() => go(item.href)}>
                    <item.icon className="h-4 w-4 text-text-muted" strokeWidth={1.5} />
                    {item.label}
                  </Item>
                ))}
              </Command.Group>

              {recent.length > 0 ? (
                <Command.Group
                  heading={ru.keyboard.paletteRecent}
                  className="[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-caption [&_[cmdk-group-heading]]:text-text-muted"
                >
                  {recent.map((item) => (
                    <Item
                      key={item.regNum}
                      value={`${item.name} ${item.regNum}`}
                      onSelect={() => go(`/tenders/${item.regNum}`)}
                    >
                      <span className="truncate">{item.name}</span>
                      <span className="ml-auto shrink-0 font-mono text-[11px] text-text-subtle">
                        {item.regNum}
                      </span>
                    </Item>
                  ))}
                </Command.Group>
              ) : null}
            </Command.List>
          </Command>
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}

function Item({
  children,
  value,
  onSelect,
}: {
  children: React.ReactNode;
  value?: string;
  onSelect: () => void;
}) {
  return (
    <Command.Item
      value={value}
      onSelect={onSelect}
      className={cn(
        "flex h-10 cursor-pointer items-center gap-2.5 rounded-[6px] px-3 text-body text-text",
        "data-[selected=true]:surface-gos-tint",
      )}
    >
      {children}
    </Command.Item>
  );
}
