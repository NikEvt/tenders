"use client";

import * as React from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Keyboard } from "lucide-react";
import { Button } from "@/shared/ui/button";
import { Tooltip } from "@/shared/ui/tooltip";
import { Banner } from "@/shared/ui/banner";
import { useHotkeys, useLocalStorage } from "@/shared/lib/hooks";
import { commandPalette, useCommandPaletteOpen } from "@/shared/lib/command-palette";
import { ru } from "@/shared/i18n/ru";
import { cn } from "@/shared/lib/cn";
import { degradedStore, useDegraded } from "@/features/compile-filter/model/degraded-store";
import { NAV } from "../model/nav";
import { BottomBar, SideRail } from "./side-rail";
import { ThemeToggle } from "./theme-toggle";

// Командная строка и лист горячих клавиш открываются по требованию — держать
// их в стартовом бандле каждой страницы незачем.
const CommandPalette = dynamic(() =>
  import("./command-palette").then((m) => m.CommandPalette),
);
const ShortcutSheet = dynamic(() =>
  import("./shortcut-sheet").then((m) => m.ShortcutSheet),
);

/**
 * Каркас: постоянная левая колонка, липкая верхняя полоса, содержимое до 1440px.
 * Панель-инспектор живёт внутри страницы каталога — она не должна размонтировать
 * список, поэтому в каркас не вынесена.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [collapsed, setCollapsed] = useLocalStorage("zakupki:rail-collapsed", false);
  const paletteOpen = useCommandPaletteOpen();
  const [shortcutsOpen, setShortcutsOpen] = React.useState(false);
  const degraded = useDegraded();

  useHotkeys([
    { combo: "ctrl+k", handler: () => commandPalette.toggle(), inInputs: true },
    { combo: "?", handler: () => setShortcutsOpen(true) },
    ...NAV.filter((item) => item.goKey).map((item) => ({
      combo: `g ${item.goKey}`,
      handler: () => router.push(item.href),
    })),
  ]);

  return (
    <div className="flex min-h-dvh">
      <a
        href="#content"
        className={cn(
          "sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50",
          "focus:rounded-[6px] focus:bg-surface focus:px-4 focus:py-2 focus:shadow-(--shadow-overlay)",
        )}
      >
        {ru.app.skipToContent}
      </a>

      <SideRail collapsed={collapsed} onToggle={() => setCollapsed(!collapsed)} />

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-hairline bg-surface/95 px-4 backdrop-blur-[2px] no-print md:px-8">
          {/* Отдельной кнопки «⌘K Быстрый переход» здесь больше нет: она была
              вторым широким входом и спорила с поиском за внимание. Подсказка
              переехала внутрь поля поиска (widgets/tender-list/ui/search-bar),
              сочетание клавиш не изменилось. */}
          <div className="ml-auto flex items-center gap-2">
            <Tooltip content={ru.keyboard.sheet} shortcut="?">
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={ru.keyboard.sheet}
                onClick={() => setShortcutsOpen(true)}
              >
                <Keyboard className="h-4 w-4" strokeWidth={1.5} />
              </Button>
            </Tooltip>
            <ThemeToggle />
          </div>
        </header>

        {degraded.degraded && !degraded.dismissed ? (
          <div className="px-4 pt-4 md:px-8 no-print">
            <Banner
              tone="oak"
              title={ru.ai.degradedTitle}
              body={ru.ai.degradedBody}
              onDismiss={() => degradedStore.dismiss()}
              actions={
                <Button asChild size="sm" variant="secondary">
                  <Link href="/settings">{ru.ai.degradedAction}</Link>
                </Button>
              }
            />
          </div>
        ) : null}

        <main id="content" className="min-w-0 flex-1 pb-16 md:pb-0">
          <div className="mx-auto w-full max-w-[1440px] px-4 py-6 md:px-8">{children}</div>
        </main>
      </div>

      <BottomBar />
      {paletteOpen ? <CommandPalette open onOpenChange={commandPalette.setOpen} /> : null}
      {shortcutsOpen ? <ShortcutSheet open onOpenChange={setShortcutsOpen} /> : null}
    </div>
  );
}
