"use client";

import * as React from "react";
import { Search, Sparkle } from "lucide-react";
import { Button } from "@/shared/ui/button";
import { Input } from "@/shared/ui/field";
import { Chip } from "@/shared/ui/chip";
import { ru } from "@/shared/i18n/ru";
import { cn } from "@/shared/lib/cn";
import { commandPalette } from "@/shared/lib/command-palette";
import type { FilterSpec } from "@/shared/api/types";
import { useCompileFilter } from "@/features/compile-filter/model/use-compile-filter";
import { compiledConditions } from "@/features/compile-filter/ui/compiled-chips";

export type SearchBarProps = {
  value: string;
  onValueChange: (value: string) => void;
  /** Простой поиск без обращения к модели: Enter при пустом разборе. */
  onSubmit: (value: string) => void;
  /** Разобранная моделью спецификация принята пользователем. */
  onApplySpec: (spec: FilterSpec) => void;
  inputRef?: React.RefObject<HTMLInputElement | null>;
};

/**
 * Одно поле, два режима, без переключателя.
 *
 * Аналитик пишет по-русски и жмёт Enter; клиент отправляет текст на разбор и
 * показывает результат чипами — интерпретация модели никогда не скрыта, и
 * каждая её часть снимается одним кликом. Это и есть ответ на вопрос «почему
 * я должен доверять ИИ-поиску».
 */
export function SearchBar({
  value,
  onValueChange,
  onSubmit,
  onApplySpec,
  inputRef,
}: SearchBarProps) {
  const compile = useCompileFilter();
  const [draft, setDraft] = React.useState<FilterSpec | null>(null);
  const [text, setText] = React.useState(value);

  React.useEffect(() => setText(value), [value]);

  const runCompile = () => {
    const query = text.trim();
    if (query.length < 3) {
      onSubmit(query);
      return;
    }
    compile.mutate(query, {
      onSuccess: (result) => setDraft(result.spec),
      // Модель недоступна — поиск всё равно должен работать по словам.
      onError: () => onSubmit(query),
    });
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-0 flex-1">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-subtle"
            strokeWidth={1.5}
            aria-hidden="true"
          />
          <Input
            ref={inputRef}
            value={text}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                runCompile();
              }
              if (event.key === "Escape") {
                setText("");
                onValueChange("");
                setDraft(null);
              }
            }}
            placeholder={ru.catalog.searchPlaceholder}
            aria-label={ru.catalog.searchPlaceholder}
            className="h-11 pl-9 pr-14"
          />
          <PaletteHint />
        </div>
        <Button variant="primary" size="lg" loading={compile.isPending} onClick={runCompile}>
          {ru.filters.compile}
        </Button>
      </div>

      {draft ? (
        <CompiledDraft
          spec={draft}
          onChange={setDraft}
          onApply={() => {
            onApplySpec(draft);
            setDraft(null);
          }}
          onDiscard={() => setDraft(null)}
        />
      ) : null}
    </div>
  );
}

/**
 * Подсказка о командной строке — внутри поля, у правого края.
 *
 * Раньше рядом с поиском стояла вторая широкая кнопка «⌘K Быстрый переход»:
 * два входа одинакового веса в одной полосе, и ни один из них не главный.
 * Подсказка внутри поля не спорит с ним за внимание, но остаётся видимой
 * всегда — не по наведению, иначе о сочетании узнают только те, кто его уже
 * знает.
 *
 * Кнопка, а не декорация: отдельного входа мышью в командную строку в
 * интерфейсе больше нет. Вариант `ghost` — цветная заливка на второстепенном
 * действии и создала перекос, который здесь исправляется.
 */
function PaletteHint() {
  return (
    <div className="absolute right-1.5 top-1/2 hidden h-9 w-9 -translate-y-1/2 items-center justify-center min-[900px]:flex">
      <Button
        variant="ghost"
        onClick={() => commandPalette.open()}
        aria-label={ru.keyboard.palette}
        title={ru.keyboard.palette}
        className="h-8 w-8 rounded-[4px] border border-hairline bg-surface p-0 font-mono text-[11px] text-text-muted"
      >
        ⌘K
      </Button>
    </div>
  );
}

function CompiledDraft({
  spec,
  onChange,
  onApply,
  onDiscard,
}: {
  spec: FilterSpec;
  onChange: (spec: FilterSpec) => void;
  onApply: () => void;
  onDiscard: () => void;
}) {
  const conditions = compiledConditions(spec);

  return (
    <div className="rounded-[10px] border border-hairline bg-surface-sunken p-3">
      <p className="mb-2 flex items-center gap-1.5 text-caption text-text-muted">
        <Sparkle className="h-3.5 w-3.5" strokeWidth={1.5} aria-hidden="true" />
        {ru.filters.changedByModel}
      </p>

      {conditions.length === 0 ? (
        <p className="text-body-sm text-text-muted">
          Модель не нашла условий: запрос уйдёт как обычный текстовый поиск.
        </p>
      ) : (
        <ul className={cn("flex flex-wrap gap-1.5")}>
          {conditions.map((condition) => (
            <li key={condition.id} className="max-w-full">
              <Chip
                kind={condition.kind}
                title={condition.kind === "llm" ? ru.filters.stepJudge : condition.label}
                onRemove={() => onChange(condition.remove(spec))}
              >
                {condition.label}
              </Chip>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-3 flex items-center gap-2">
        <Button size="sm" variant="primary" onClick={onApply}>
          {ru.common.apply}
        </Button>
        <Button size="sm" variant="ghost" onClick={onDiscard}>
          {ru.common.cancel}
        </Button>
        {spec.llm_criteria?.trim() ? (
          <p className="ml-auto text-body-sm text-text-muted">
            Критерий для судьи заработает после сохранения фильтра.
          </p>
        ) : null}
      </div>
    </div>
  );
}
