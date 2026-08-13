import * as React from "react";
import { cn } from "@/shared/lib/cn";
import { ru } from "@/shared/i18n/ru";

export type DefinitionItem = {
  label: string;
  value: React.ReactNode;
  /** Поля, которых нет в извещении, показываются прочерком с пояснением. */
  missingHint?: string;
  mono?: boolean;
};

/**
 * Карточка закупки читается как документ: подпись — значение, две колонки на
 * широком экране. Пустая строка не удаляется — отсутствие поля тоже факт.
 */
export function DefinitionList({
  items,
  columns = 2,
  className,
}: {
  items: DefinitionItem[];
  columns?: 1 | 2;
  className?: string;
}) {
  return (
    <dl
      className={cn(
        "grid gap-x-8 gap-y-4",
        columns === 2 ? "grid-cols-1 md:grid-cols-2" : "grid-cols-1",
        className,
      )}
    >
      {items.map((item) => {
        const empty = item.value === null || item.value === undefined || item.value === "";
        return (
          <div key={item.label} className="min-w-0">
            <dt className="text-caption text-text-muted">{item.label}</dt>
            <dd
              className={cn(
                "mt-1 text-body text-text",
                item.mono && "font-mono text-mono tnum",
                empty && "text-text-subtle",
              )}
              title={empty ? (item.missingHint ?? ru.common.notInNotice) : undefined}
            >
              {empty ? "—" : item.value}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}
