"use client";

import * as React from "react";
import { Search, X } from "lucide-react";

import { ru } from "@/shared/i18n/ru";
import { cn } from "@/shared/lib/cn";
import { formatCount } from "@/shared/lib/format";
import { REGIONS } from "@/shared/lib/regions";
import { Button } from "@/shared/ui/button";
import { Checkbox, Input } from "@/shared/ui/field";

export type RegionChecklistProps = {
  value: string[];
  onChange: (regions: string[]) => void;
  /** Сколько закупок в каждом регионе. Необязательно — форма запуска их не знает. */
  counts?: Map<string, number>;
  className?: string;
};

/**
 * Выбор субъектов из справочника на 85 записей.
 *
 * Плоский список чекбоксов годился, пока справочник был на шестнадцать строк;
 * на полном найти в нём Пермский край прокруткой нельзя. Отсюда поиск и
 * выбранные наверху — иначе снять регион, уехавший вниз, стоит той же
 * прокрутки, что и найти его.
 */
export function RegionChecklist({
  value,
  onChange,
  counts,
  className,
}: RegionChecklistProps) {
  const [query, setQuery] = React.useState("");

  const codes = React.useMemo(() => {
    const needle = query.trim().toLowerCase();
    const matches = Object.keys(REGIONS).filter(
      (code) =>
        !needle ||
        code.startsWith(needle) ||
        REGIONS[code]!.toLowerCase().includes(needle),
    );
    // Выбранные наверху: снять отметку должно быть не дороже, чем поставить.
    const selected = new Set(value);
    return [
      ...matches.filter((code) => selected.has(code)),
      ...matches.filter((code) => !selected.has(code)),
    ];
  }, [query, value]);

  const toggle = (code: string, checked: boolean) =>
    onChange(checked ? [...value, code] : value.filter((r) => r !== code));

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <div className="relative">
        <Search
          aria-hidden
          className="pointer-events-none absolute top-1/2 left-2 size-4 -translate-y-1/2 text-text-subtle"
        />
        <Input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={ru.catalog.facets.regionSearch}
          aria-label={ru.catalog.facets.regionSearch}
          className="h-8 pl-8"
        />
      </div>

      {value.length > 0 ? (
        <div className="flex items-center justify-between text-caption text-text-muted">
          <span>{ru.catalog.facets.regionSelected(value.length)}</span>
          <Button
            variant="quiet"
            size="sm"
            icon={<X className="size-3" />}
            onClick={() => onChange([])}
          >
            {ru.catalog.facets.regionClear}
          </Button>
        </div>
      ) : null}

      <ul className="flex max-h-64 flex-col gap-1 overflow-y-auto">
        {codes.map((code) => {
          const checked = value.includes(code);
          return (
            <li key={code}>
              <label className="flex cursor-pointer items-center gap-2 rounded-[6px] px-1 py-1 text-body-sm hover:bg-surface-sunken">
                <Checkbox
                  checked={checked}
                  onChange={(event) => toggle(code, event.target.checked)}
                />
                <span className="flex-1">{REGIONS[code]}</span>
                {counts ? <Count value={counts.get(code)} /> : null}
              </label>
            </li>
          );
        })}
        {codes.length === 0 ? (
          <li className="px-1 py-2 text-caption text-text-subtle">
            {ru.catalog.facets.regionNotFound}
          </li>
        ) : null}
      </ul>
    </div>
  );
}

function Count({ value }: { value: number | undefined }) {
  if (value === undefined) return null;
  return <span className="tnum text-caption text-text-subtle">{formatCount(value)}</span>;
}
