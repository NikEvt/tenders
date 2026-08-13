"use client";

import * as React from "react";
import { Check, ChevronDown } from "lucide-react";
import { Button } from "@/shared/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/shared/ui/popover";
import { Tooltip } from "@/shared/ui/tooltip";
import { cn } from "@/shared/lib/cn";
import { ru } from "@/shared/i18n/ru";
import {
  GROUPABLE_FIELDS,
  SORT_FIELDS,
  SORT_GROUP_LABELS,
  SORT_GROUP_ORDER,
  defaultKey,
  describeSort,
  isAvailable,
  sortField,
  type SortContext,
  type SortDir,
  type SortKey,
} from "@/entities/tender/model/sort";

export type SortControlProps = {
  keys: SortKey[];
  group: string | null;
  context: SortContext;
  onChange: (next: { keys: SortKey[]; group: string | null }) => void;
};

/**
 * Кнопка с выпадающим списком вместо сегментированного переключателя.
 *
 * Семь вариантов и направление в сегменты не помещаются: переключатель
 * из семи кнопок занимает всю строку и всё равно не показывает, что «по
 * заказчику» бывает в две стороны.
 *
 * Ни одного перечисления сортировок здесь нет — всё читается из реестра, и
 * новое поле появляется в списке само.
 */
export function SortControl({ keys, group, context, onChange }: SortControlProps) {
  const [open, setOpen] = React.useState(false);
  const current = keys[0] ?? defaultKey("published");
  const field = sortField(current.field);
  const groupingBlocked = current.field === "relevance";

  const pick = (id: string) => {
    // Смена поля берёт его направление по умолчанию: «сначала ближайшие»
    // осмысленно для срока и бессмысленно для цены.
    const next = defaultKey(id);
    onChange({
      keys: [next],
      group: id === "relevance" ? null : group,
    });
  };

  const setDirection = (dir: SortDir) => onChange({ keys: [{ ...current, dir }], group });

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="secondary" size="sm" className="gap-1.5">
          <span className="text-text-muted">{ru.catalog.sort.label}:</span>
          <span>{describeSort(keys)}</span>
          {group ? (
            <span className="text-text-muted">
              · {ru.catalog.sort.groupedBy} {sortField(group)?.groupLabel?.toLowerCase()}
            </span>
          ) : null}
          <ChevronDown className="h-3.5 w-3.5 text-text-muted" strokeWidth={1.5} />
        </Button>
      </PopoverTrigger>

      {/* Состояние объявляется словами и вне поповера: закрыв его, человек
          должен услышать, что именно изменилось. */}
      <span aria-live="polite" className="sr-only">
        {ru.catalog.sort.announce(describeSort(keys), group ? sortField(group)?.groupLabel : null)}
      </span>

      <PopoverContent className="w-[300px] p-0" align="end">
        <div role="radiogroup" aria-label={ru.catalog.sort.label} className="max-h-[60vh] overflow-auto p-2">
          {SORT_GROUP_ORDER.map((groupName) => {
            const fields = SORT_FIELDS.filter((item) => item.group === groupName);
            if (fields.length === 0) return null;

            return (
              <div key={groupName} className="mb-1 last:mb-0">
                <p className="px-2 py-1 text-eyebrow uppercase text-text-muted">
                  {SORT_GROUP_LABELS[groupName]}
                </p>
                {fields.map((item) => {
                  const available = isAvailable(item, context);
                  const active = item.id === current.field;

                  return (
                    <button
                      key={item.id}
                      type="button"
                      role="radio"
                      aria-checked={active}
                      disabled={!available}
                      // Недоступное не прячется, а объясняется: список,
                      // который меняет длину, ощущается ненадёжным.
                      title={available ? undefined : ru.catalog.sort.needsQuery}
                      onClick={() => pick(item.id)}
                      className={cn(
                        "flex w-full items-center gap-2 rounded-[6px] px-2 py-1.5 text-left text-body-sm",
                        "hover:bg-surface-sunken",
                        active && "font-medium",
                        !available && "cursor-not-allowed opacity-50 hover:bg-transparent",
                      )}
                    >
                      <Check
                        className={cn("h-3.5 w-3.5 shrink-0", active ? "opacity-100" : "opacity-0")}
                        strokeWidth={2}
                        aria-hidden="true"
                      />
                      <span className="min-w-0 flex-1 truncate">{item.label}</span>
                      {!available ? (
                        <span className="shrink-0 text-caption text-text-muted">
                          {ru.catalog.sort.needsQueryShort}
                        </span>
                      ) : null}
                    </button>
                  );
                })}
              </div>
            );
          })}
        </div>

        <div className="flex flex-col gap-2 border-t border-hairline p-3">
          <Row label={ru.catalog.sort.direction}>
            <select
              value={current.dir}
              onChange={(event) => setDirection(event.target.value as SortDir)}
              aria-label={ru.catalog.sort.direction}
              className="min-w-0 flex-1 rounded-[6px] border border-border-strong bg-surface-sunken px-2 py-1 text-body-sm text-text"
            >
              {/* Не «↑ / ↓»: на «по заказчику» стрелка не значит ничего. */}
              <option value="asc">{field?.dirLabels.asc}</option>
              <option value="desc">{field?.dirLabels.desc}</option>
            </select>
          </Row>

          <Row label={ru.catalog.sort.groupBy}>
            <GroupSelect
              value={group}
              blocked={groupingBlocked}
              onChange={(next) => onChange({ keys, group: next })}
            />
          </Row>
        </div>
      </PopoverContent>
    </Popover>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex items-center gap-2 text-body-sm text-text-muted">
      <span className="w-32 shrink-0">{label}</span>
      {children}
    </label>
  );
}

function GroupSelect({
  value,
  blocked,
  onChange,
}: {
  value: string | null;
  blocked: boolean;
  onChange: (next: string | null) => void;
}) {
  const select = (
    <select
      value={value ?? ""}
      disabled={blocked}
      onChange={(event) => onChange(event.target.value || null)}
      aria-label={ru.catalog.sort.groupBy}
      className={cn(
        "min-w-0 flex-1 rounded-[6px] border border-border-strong bg-surface-sunken px-2 py-1 text-body-sm text-text",
        blocked && "cursor-not-allowed opacity-50",
      )}
    >
      <option value="">{ru.common.no}</option>
      {GROUPABLE_FIELDS.map((field) => (
        <option key={field.id} value={field.id}>
          {field.groupLabel}
        </option>
      ))}
    </select>
  );

  // Молча игнорировать одну из двух настроек нельзя — противоречие
  // проговаривается вслух.
  return blocked ? (
    <Tooltip content={ru.catalog.sort.groupingVsRelevance}>
      <span className="flex min-w-0 flex-1">{select}</span>
    </Tooltip>
  ) : (
    select
  );
}
