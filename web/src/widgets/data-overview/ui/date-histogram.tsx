"use client";

import * as React from "react";
import { ru } from "@/shared/i18n/ru";
import { cn } from "@/shared/lib/cn";
import { dateShort } from "@/shared/lib/format";
import { formatCount } from "@/shared/lib/plural";
import { useElementWidth } from "@/shared/lib/hooks";
import { layoutLabels, type LabelInput } from "@/shared/ui/chart/label-layout";
import { useMeasurer } from "@/shared/ui/chart/use-measurer";
import type { DayBucket } from "@/shared/api/types";

const HEIGHT = 120;
const AXIS = 18;
const MIN_GAP = 1;
const LABEL_FONT = "500 12px 'Golos Text', ui-sans-serif, system-ui, sans-serif";

/** Сколько подписей дат пытаемся расставить. Дальше их разводит лестница. */
const LABEL_TARGET = 6;

/**
 * Публикации по дням.
 *
 * **Главное решение здесь — про два разных нуля.** День, за который выгрузки не
 * было, и день, в который ничего не публиковали, — совершенно разные вещи:
 * первое говорит о дыре в наших данных, второе о рынке. Слить их в один пустой
 * столбец значило бы выдать наше незнание за факт. Поэтому невыгруженный день
 * рисуется штриховкой на всю высоту и подписан отдельно, а настоящий ноль —
 * пустым местом на нулевой отметке.
 *
 * Подписи оси разводит `chart/label-layout` — та же лестница отступления, что
 * у шкалы сроков: полный текст → короткий → две строки → легенда.
 */
export function DateHistogram({ days }: { days: DayBucket[] }) {
  const ref = React.useRef<HTMLDivElement>(null);
  const width = useElementWidth(ref, 720);
  const measure = useMeasurer(LABEL_FONT);

  const peak = Math.max(...days.map((day) => day.count), 1);
  const step = days.length > 0 ? width / days.length : 0;
  const barWidth = Math.max(1, step - MIN_GAP);

  const labels = React.useMemo<LabelInput[]>(() => {
    if (days.length === 0) return [];
    const every = Math.max(1, Math.round(days.length / LABEL_TARGET));
    return days
      .filter((_, index) => index % every === 0)
      .map((day, order) => ({
        id: day.day,
        x: (days.indexOf(day) + 0.5) * step,
        text: dateShort(day.day),
        priority: order,
      }));
  }, [days, step]);

  const layout = React.useMemo(
    () => layoutLabels(labels, { width, maxRows: 1, measure }),
    [labels, width, measure],
  );

  return (
    <div ref={ref} className="w-full">
      <svg
        width="100%"
        height={HEIGHT + AXIS}
        viewBox={`0 0 ${width} ${HEIGHT + AXIS}`}
        role="img"
        aria-label={ru.data.byDate}
        className="overflow-visible"
      >
        <defs>
          {/* Штриховка — не украшение: она носит смысл «данных нет», и её
              рисунок читается даже там, где цвет не различают. */}
          <pattern
            id="not-crawled"
            width="4"
            height="4"
            patternUnits="userSpaceOnUse"
            patternTransform="rotate(45)"
          >
            <line x1="0" y1="0" x2="0" y2="4" stroke="currentColor" strokeWidth="1.5" />
          </pattern>
        </defs>

        {days.map((day, index) => {
          const x = index * step;
          const height = day.crawled ? (day.count / peak) * HEIGHT : HEIGHT;

          return (
            <rect
              key={day.day}
              data-crawled={day.crawled}
              x={x}
              y={HEIGHT - height}
              width={barWidth}
              height={Math.max(height, day.crawled && day.count > 0 ? 1 : 0)}
              rx={1}
              className={cn(
                day.crawled
                  ? "fill-gos-fg"
                  : // Пропуск обязан быть отличим, но не громче данных. На
                    // корпусе, где выгружены девять дней из девяноста, сплошная
                    // штриховка в полную силу забивала собой единственный
                    // столбец с настоящими числами — то есть мешала читать
                    // ровно то, ради чего график и нужен.
                    "text-border-strong/25 [fill:url(#not-crawled)]",
              )}
            >
              <title>{dayTitle(day)}</title>
            </rect>
          );
        })}

        <line
          x1="0"
          y1={HEIGHT}
          x2={width}
          y2={HEIGHT}
          className="stroke-hairline"
          strokeWidth="1"
        />

        {layout.mode !== "legend"
          ? layout.placements.map((placement) => (
              <text
                key={placement.id}
                x={placement.x}
                y={HEIGHT + 13}
                textAnchor={placement.anchor}
                className="fill-text-subtle text-caption tnum"
              >
                {placement.text}
              </text>
            ))
          : null}
      </svg>

      <p className="mt-2 flex items-center gap-2 text-caption text-text-subtle">
        <span
          aria-hidden="true"
          className="inline-block h-3 w-3 rounded-[2px] border border-border-strong bg-[repeating-linear-gradient(45deg,transparent,transparent_1px,var(--color-border-strong)_1px,var(--color-border-strong)_2px)]"
        />
        {ru.data.notCrawledLegend}
      </p>
    </div>
  );
}

/**
 * Подпись столбца. Три разных текста, потому что за ними три разных факта:
 * публикации были, публикаций не было, данных нет.
 */
function dayTitle(day: DayBucket): string {
  const label = dateShort(day.day);
  if (!day.crawled) return ru.data.dayNotCrawled(label);
  if (day.count === 0) return ru.data.dayZero(label);
  return ru.data.dayTenders(label, formatCount(day.count));
}
