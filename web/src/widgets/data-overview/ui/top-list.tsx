"use client";

import { Bar } from "@/shared/ui/bar";
import { ru } from "@/shared/i18n/ru";
import { formatCount } from "@/shared/lib/plural";
import type { Distribution } from "@/shared/api/types";

/**
 * Разрез: верхушка плюс хвост.
 *
 * «Остальные» и «без кода» показываются **всегда**, когда они не нулевые, и это
 * не аккуратность, а знаменатель: двенадцать столбиков без хвоста читаются как
 * весь корпус. Сумма показанного, хвоста и «без признака» равна итогу — на это
 * есть сторож и на сервере, и здесь.
 */
export function TopList({
  distribution,
  mono = false,
  unknownLabel = ru.data.unknown,
}: {
  distribution: Distribution;
  /** Коды ОКПД2 — данные, а не слова: набираются моноширинным (§2.5). */
  mono?: boolean;
  unknownLabel?: string;
}) {
  const peak = Math.max(...distribution.top.map((item) => item.count), 1);

  return (
    <div className="flex flex-col gap-1">
      {distribution.top.map((item) => (
        <Bar
          key={item.key}
          label={mono ? `${item.key} · ${item.label}` : item.label}
          value={item.count}
          max={peak}
          // Названия ОКПД2 длиннее колонки и обрезаются: полный текст обязан
          // остаться доступным, иначе «Изделия м…» ничего не значит.
          hint={mono ? `${item.key} · ${item.label}` : item.label}
        />
      ))}

      {distribution.others > 0 ? (
        <Bar
          label={ru.data.others}
          value={distribution.others}
          max={peak}
          tone="neutral"
        />
      ) : null}

      {distribution.unknown > 0 ? (
        <Bar
          label={unknownLabel}
          value={distribution.unknown}
          max={peak}
          tone="neutral"
        />
      ) : null}

      <p className="mt-1 px-1 text-caption tnum text-text-subtle">
        {ru.waiting.done(
          formatCount(
            distribution.top.reduce((sum, item) => sum + item.count, 0) +
              distribution.others +
              distribution.unknown,
          ),
          formatCount(distribution.total),
        )}
      </p>
    </div>
  );
}
