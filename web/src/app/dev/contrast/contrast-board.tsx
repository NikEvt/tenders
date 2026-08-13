"use client";

import * as React from "react";
import { Banner } from "@/shared/ui/banner";
import { Button } from "@/shared/ui/button";
import { Chip } from "@/shared/ui/chip";
import { Field, Input } from "@/shared/ui/field";
import { Bar } from "@/shared/ui/bar";
import { Pill, type PillTone } from "@/shared/ui/pill";
import { PageHeader, SectionHeading } from "@/shared/ui/section";
import { VellumNote } from "@/shared/ui/vellum-note";
import { Kbd } from "@/shared/ui/tooltip";
import { CONTRAST_PAIRS, contrastRatio, type ContrastPair } from "@/shared/lib/tokens";
import { cn } from "@/shared/lib/cn";

type Measured = ContrastPair & { ratio: number; fgValue: string; bgValue: string };

const THEMES = ["light", "dark"] as const;
type ThemeName = (typeof THEMES)[number];

/**
 * Витрина контраста.
 *
 * Считает не по файлу стилей, а по `getComputedStyle` — то есть по тому, что
 * браузер действительно нарисовал. Тест ловит ошибку в значениях токена,
 * эта страница — ошибку в каскаде: перекрытый блок, потерянный `data-theme`,
 * утилиту, которая вообще не сгенерировалась.
 */
export function ContrastBoard() {
  const refs = React.useRef<Record<ThemeName, HTMLElement | null>>({
    light: null,
    dark: null,
  });
  const [measured, setMeasured] = React.useState<Record<ThemeName, Measured[]>>({
    light: [],
    dark: [],
  });

  React.useEffect(() => {
    const read = (host: HTMLElement | null): Measured[] => {
      if (!host) return [];
      const style = getComputedStyle(host);
      return CONTRAST_PAIRS.map((pair) => {
        const fgValue = style.getPropertyValue(pair.fg).trim();
        const bgValue = style.getPropertyValue(pair.bg).trim();
        let ratio = 0;
        try {
          ratio = contrastRatio(fgValue, bgValue);
        } catch {
          // Токен не объявлен или не hex — 0 попадёт в таблицу как провал,
          // и это честнее, чем пустая ячейка.
        }
        return { ...pair, ratio, fgValue, bgValue };
      });
    };

    setMeasured({ light: read(refs.current.light), dark: read(refs.current.dark) });
  }, []);

  const failures = THEMES.flatMap((theme) =>
    measured[theme].filter((row) => row.ratio < row.min),
  ).length;

  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        title="Контраст"
        meta="Каждая пара «текст на фоне» в обеих темах, с посчитанным на месте отношением. Страница не входит в навигацию и закрыта от индексации."
      />

      {measured.light.length === 0 ? null : failures > 0 ? (
        <Banner
          tone="signal"
          title={`Провалов: ${failures}`}
          body="Ниже отмечены красным. Тест src/shared/ui/__tests__/contrast.test.ts должен падать на тех же парах."
        />
      ) : (
        <Banner
          tone="moss"
          title="Все пары проходят"
          body="Отношения посчитаны по getComputedStyle в обеих темах."
        />
      )}

      <div className="grid gap-8 lg:grid-cols-2">
        {THEMES.map((theme) => (
          <section
            key={theme}
            ref={(node) => {
              refs.current[theme] = node;
            }}
            data-theme={theme}
            className="flex flex-col gap-6 rounded-[10px] border border-hairline bg-canvas p-5 text-text"
          >
            <SectionHeading title={theme === "light" ? "Светлая тема" : "Тёмная тема"} />

            <PairTable rows={measured[theme]} />
            <Primitives />
          </section>
        ))}
      </div>
    </div>
  );
}

function PairTable({ rows }: { rows: Measured[] }) {
  if (rows.length === 0) {
    return <p className="text-body-sm text-text-muted">Считаем…</p>;
  }

  return (
    <ul className="flex flex-col gap-1">
      {rows.map((row) => {
        const passed = row.ratio >= row.min;
        return (
          <li
            key={`${row.fg}|${row.bg}`}
            className="flex items-center gap-3 rounded-[6px] border border-hairline px-2 py-1.5"
            style={{ background: `var(${row.bg})`, color: `var(${row.fg})` }}
          >
            <span className="min-w-0 flex-1 truncate text-body-sm">
              {row.fg.replace("--color-", "")} на {row.bg.replace("--color-", "")}
            </span>
            <span className="font-mono text-[11px] tnum opacity-80">
              {row.fgValue} / {row.bgValue}
            </span>
            <span
              className={cn(
                "shrink-0 rounded-[4px] px-1.5 py-0.5 font-mono text-[11px] tnum",
                passed ? "surface-moss-tint" : "surface-signal-tint",
              )}
            >
              {row.ratio.toFixed(2)}:1 ≥ {row.min}
              {row.note ? ` · ${row.note}` : ""}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

const PILLS: PillTone[] = ["gos", "oak", "moss", "signal", "neutral"];

/** Те же примитивы, что и в витрине, — но здесь важны обе темы рядом. */
function Primitives() {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="primary" size="sm">
          Главное действие
        </Button>
        <Button variant="secondary" size="sm">
          Второе
        </Button>
        <Button variant="ghost" size="sm">
          Тихое
        </Button>
        <Button variant="danger" size="sm">
          Опасное
        </Button>
        <Button variant="quiet" size="sm">
          Совсем тихое
        </Button>
      </div>

      <div className="flex flex-wrap gap-2">
        {PILLS.map((tone) => (
          <Pill key={tone} tone={tone} dot>
            {tone}
          </Pill>
        ))}
      </div>

      <div className="flex flex-wrap gap-2">
        <Chip kind="structural">регион: Москва</Chip>
        <Chip kind="semantic">«ремонт кровли»</Chip>
        <Chip kind="llm">критерий судьи</Chip>
      </div>

      <div className="rounded-[10px] border border-hairline bg-surface p-3">
        <Bar label="Прошли фильтр" value={128} max={1248} tone="gos" />
        <Bar label="Отсеяны" value={1120} max={1248} tone="neutral" />
      </div>

      <Field label="Поле ввода" hint="Подпись под полем">
        <Input placeholder="Опишите, что ищете" />
      </Field>

      <Banner tone="oak" title="Модель недоступна" body="Поиск работает по словам." />

      <VellumNote eyebrow="ИИ-вердикт" source="qwen3.6-35b">
        Закупка подходит: в ТЗ есть требование к кровельным работам.
      </VellumNote>

      <p className="text-body-sm text-text-muted">
        Второстепенная подпись · <span className="text-text-subtle">нетекстовая ступень</span> ·{" "}
        <span className="text-gos-fg">ссылка</span> · <Kbd>⌘K</Kbd>
      </p>
    </div>
  );
}
