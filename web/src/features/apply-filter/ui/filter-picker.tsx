"use client";

import * as React from "react";
import { Check, ChevronDown } from "lucide-react";

import { ru } from "@/shared/i18n/ru";
import { cn } from "@/shared/lib/cn";
import { Button } from "@/shared/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/shared/ui/popover";
import { Segmented, type SegmentedOption } from "@/shared/ui/segmented";
import { useSavedFilters } from "../model/use-saved-filters";

export type FilterVerdict = "confirmed" | "rejected" | "disputed";

export type FilterPickerProps = {
  filterId: number | null;
  verdict: FilterVerdict;
  onChange: (patch: { filterId: number | null; verdict: FilterVerdict }) => void;
};

const VERDICTS: SegmentedOption<FilterVerdict>[] = [
  { value: "confirmed", label: ru.catalog.filter.verdictConfirmed },
  { value: "rejected", label: ru.catalog.filter.verdictRejected },
  { value: "disputed", label: ru.catalog.filter.verdictDisputed },
];

/**
 * Выбор сохранённого фильтра для каталога.
 *
 * Отбор считает сервер по вердиктам исследования — то есть с учётом
 * контекстных правил и LLM-судьи. Разложить критерий по фасетам было бы
 * нагляднее, но это второе воплощение правила отбора, а оно в проекте живёт
 * ровно в одном месте.
 */
export function FilterPicker({ filterId, verdict, onChange }: FilterPickerProps) {
  const filters = useSavedFilters();
  const active = filters.data?.find((f) => f.filter_id === filterId);
  const label = filterId === null
    ? ru.catalog.filter.none
    : (active?.name ?? `#${filterId}`);

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          size="sm"
          variant={filterId === null ? "secondary" : "primary"}
          icon={<ChevronDown className="h-4 w-4" strokeWidth={1.5} />}
        >
          {`${ru.catalog.filter.label}: ${label}`}
        </Button>
      </PopoverTrigger>

      <span aria-live="polite" className="sr-only">
        {ru.catalog.filter.announce(label)}
      </span>

      <PopoverContent className="w-[320px] p-0" align="start">
        <div
          role="radiogroup"
          aria-label={ru.catalog.filter.pick}
          className="max-h-[50vh] overflow-auto p-2"
        >
          <Row
            active={filterId === null}
            label={ru.catalog.filter.none}
            onSelect={() => onChange({ filterId: null, verdict })}
          />
          {filters.data?.map((item) => (
            <Row
              key={item.filter_id}
              active={item.filter_id === filterId}
              label={item.name}
              // Фильтр без прогона даёт пустую выдачу. Сказать об этом до
              // клика честнее, чем показать пустой экран после.
              hint={item.last_run_at === null ? ru.catalog.filter.notRun : undefined}
              onSelect={() => onChange({ filterId: item.filter_id, verdict })}
            />
          ))}
          {filters.data?.length === 0 ? (
            <p className="px-2 py-2 text-caption text-text-subtle">
              {ru.catalog.filter.empty}
            </p>
          ) : null}
        </div>

        {filterId !== null ? (
          <div className="flex flex-col gap-2 border-t border-hairline p-3">
            <Segmented
              label={ru.catalog.filter.verdict}
              options={VERDICTS}
              value={verdict}
              onChange={(next) => onChange({ filterId, verdict: next })}
              size="sm"
            />
          </div>
        ) : null}
      </PopoverContent>
    </Popover>
  );
}

function Row({
  active,
  label,
  hint,
  onSelect,
}: {
  active: boolean;
  label: string;
  hint?: string;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={active}
      onClick={onSelect}
      className={cn(
        "flex w-full items-center gap-2 rounded-[6px] px-2 py-1.5 text-left text-body-sm",
        "hover:bg-surface-sunken",
        active && "font-medium",
      )}
    >
      <Check
        className={cn("h-3.5 w-3.5 shrink-0", active ? "opacity-100" : "opacity-0")}
        strokeWidth={2}
        aria-hidden="true"
      />
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {hint ? (
        <span className="shrink-0 text-caption text-text-muted">{hint}</span>
      ) : null}
    </button>
  );
}
