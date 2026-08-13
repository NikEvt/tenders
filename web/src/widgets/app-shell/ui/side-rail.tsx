"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { cn } from "@/shared/lib/cn";
import { ru } from "@/shared/i18n/ru";
import { Tooltip } from "@/shared/ui/tooltip";
import { NAV } from "../model/nav";

function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

/** Постоянная левая колонка. Свёрнутое состояние переживает перезагрузку. */
export function SideRail({
  collapsed,
  onToggle,
}: {
  collapsed: boolean;
  onToggle: () => void;
}) {
  const pathname = usePathname();

  return (
    <nav
      aria-label={ru.app.name}
      className={cn(
        "sticky top-0 hidden h-dvh shrink-0 flex-col border-r border-hairline bg-surface md:flex",
        "transition-[width] duration-(--dur-panel) ease-(--ease-enter)",
        collapsed ? "w-16" : "w-62",
      )}
    >
      <div
        className={cn(
          "flex h-14 items-center border-b border-hairline",
          collapsed ? "justify-center px-2" : "justify-between px-4",
        )}
      >
        {!collapsed ? (
          <Link href="/" className="flex items-center gap-2 no-underline">
            <Mark />
            <span className="text-body font-semibold text-text">{ru.app.name}</span>
          </Link>
        ) : (
          <Mark />
        )}
      </div>

      <ul className="flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto p-2">
        {NAV.map((item) => {
          const active = isActive(pathname, item.href);
          const link = (
            <Link
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex h-10 items-center gap-3 rounded-[6px] px-3 no-underline",
                "text-body transition-colors duration-(--dur-state)",
                active
                  ? "surface-gos-tint font-medium"
                  : "text-text-muted hover:bg-surface-sunken hover:text-text",
                collapsed && "justify-center px-0",
              )}
            >
              <item.icon className="h-5 w-5 shrink-0" strokeWidth={1.5} aria-hidden="true" />
              {!collapsed ? <span className="truncate">{item.label}</span> : null}
            </Link>
          );

          return (
            <li key={item.href}>
              {collapsed ? (
                <Tooltip
                  content={item.label}
                  side="right"
                  shortcut={item.goKey ? `g ${item.goKey}` : undefined}
                >
                  {link}
                </Tooltip>
              ) : (
                link
              )}
            </li>
          );
        })}
      </ul>

      <div className="border-t border-hairline p-2">
        <button
          type="button"
          onClick={onToggle}
          className={cn(
            "flex h-10 w-full items-center gap-3 rounded-[6px] px-3 text-body-sm text-text-muted",
            "hover:bg-surface-sunken hover:text-text",
            collapsed && "justify-center px-0",
          )}
        >
          {collapsed ? (
            <PanelLeftOpen className="h-5 w-5" strokeWidth={1.5} aria-hidden="true" />
          ) : (
            <PanelLeftClose className="h-5 w-5" strokeWidth={1.5} aria-hidden="true" />
          )}
          {!collapsed ? ru.nav.collapse : <span className="sr-only">{ru.nav.expand}</span>}
        </button>
      </div>
    </nav>
  );
}

/** Знак: две линии шкалы сроков и узел — тот же язык, что и на строках списка. */
function Mark() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" aria-hidden="true" className="shrink-0">
      <rect x="1" y="1" width="22" height="22" rx="7" fill="var(--color-gos-fg)" />
      <line
        x1="5.5"
        y1="12"
        x2="18.5"
        y2="12"
        stroke="white"
        strokeOpacity="0.45"
        strokeWidth="2"
        strokeLinecap="round"
      />
      <line
        x1="5.5"
        y1="12"
        x2="13"
        y2="12"
        stroke="white"
        strokeWidth="2"
        strokeLinecap="round"
      />
      <circle cx="13" cy="12" r="3" fill="white" />
    </svg>
  );
}

/** Нижняя панель на узких экранах: пять основных разделов. */
export function BottomBar() {
  const pathname = usePathname();
  const items = NAV.filter((item) => item.primary);

  return (
    <nav
      aria-label={ru.app.name}
      className="fixed inset-x-0 bottom-0 z-40 flex border-t border-hairline bg-surface md:hidden"
    >
      {items.map((item) => {
        const active = isActive(pathname, item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex min-h-14 flex-1 flex-col items-center justify-center gap-0.5 py-2 no-underline",
              active ? "text-gos-fg" : "text-text-muted",
            )}
          >
            <item.icon className="h-5 w-5" strokeWidth={1.5} aria-hidden="true" />
            <span className="text-[10px] leading-3">{item.label.split(" ")[0]}</span>
          </Link>
        );
      })}
    </nav>
  );
}
