"use client";

import * as React from "react";
import { cn } from "@/shared/lib/cn";
import { dateShort, relativeDeadline } from "@/shared/lib/format";
import { useElementWidth } from "@/shared/lib/hooks";
import { ru } from "@/shared/i18n/ru";
import {
  layoutLabels,
  ROW_OFFSET,
  type LabelInput,
  type LayoutResult,
} from "@/shared/ui/chart/label-layout";
import { useMeasurer } from "@/shared/ui/chart/use-measurer";
import { deadlineTone, railGeometry, type RailInput, type RailKey } from "./geometry";

const LABELS: Record<RailKey, string> = {
  published: ru.tender.publishedShort,
  start: ru.tender.applyStart,
  deadline: ru.tender.deadlineShort,
  commission: ru.tender.commissionShort,
  summing: ru.tender.summingShort,
};

const SHORT_LABELS: Record<RailKey, string> = {
  published: ru.tender.publishedTiny,
  start: ru.tender.applyStartTiny,
  deadline: ru.tender.deadlineTiny,
  commission: ru.tender.commissionTiny,
  summing: ru.tender.summingTiny,
};

/**
 * Что сокращать последним. Срок подачи — то, ради чего шкалу читают; этапы,
 * дат которых ЕИС не передаёт, уступают первыми. Призрачный узел прежнего
 * срока получает 0 и сокращается раньше всех.
 */
const PRIORITY: Record<RailKey, number> = {
  deadline: 4,
  published: 3,
  start: 2,
  commission: 1,
  summing: 1,
};

export type RailScale = "micro" | "meso" | "macro";

export type RailProps = RailInput & {
  scale?: RailScale;
  previousDeadline?: Date | null;
  now?: Date;
  className?: string;
};

/** Шрифт подписей — тот же, которым они рисуются. Иначе измерение врёт. */
const LABEL_FONT = "500 11px 'Golos Text', ui-sans-serif, system-ui, sans-serif";
const DATE_FONT = "400 11px 'JetBrains Mono', ui-monospace, monospace";

const MICRO_WIDTH = 120;
const FALLBACK_WIDTH = 320;

/** Отступ от узла до базовой линии подписи. */
const LABEL_GAP = 12;
const DATE_GAP = 20;
/** Место над верхней строкой подписей и под нижней. */
const EDGE_PAD = 6;

/**
 * «Шкала сроков» — подпись этого интерфейса.
 *
 * ЕИС не передаёт статус закупки: он вычисляется из дат. Вместо того чтобы
 * изображать несуществующее поле, шкала показывает сами даты — и аналитик
 * читает положение дел одним взглядом, без слов.
 *
 * Раскладкой подписей шкала не занимается: она отдаёт список и рисует ответ
 * (см. `shared/ui/chart/label-layout.ts`). Здесь нет ни одной формулы
 * расстановки — только геометрия узлов и отрисовка.
 */
export function Rail({
  scale = "micro",
  previousDeadline = null,
  now,
  className,
  ...input
}: RailProps) {
  const hostRef = React.useRef<HTMLDivElement>(null);

  return (
    <div
      ref={hostRef}
      className={cn("rail relative", scale === "micro" ? "w-[120px] shrink-0" : "w-full", className)}
    >
      {scale === "micro" ? (
        // Шестьдесят шкал в списке: ни измерения, ни раскладки, ни наблюдателя
        // за размером — микро-масштаб подписей не рисует вовсе.
        <MicroRail input={input} previousDeadline={previousDeadline} now={now} />
      ) : (
        <LabelledRail
          hostRef={hostRef}
          scale={scale}
          input={input}
          previousDeadline={previousDeadline}
          now={now}
        />
      )}
    </div>
  );
}

/* --------------------------------------------------------------- micro */

function MicroRail({
  input,
  previousDeadline,
  now,
}: {
  input: RailInput;
  previousDeadline: Date | null;
  now?: Date;
}) {
  const geometry = railGeometry(input, { width: MICRO_WIDTH, pad: 4, now, previousDeadline });
  const tone = deadlineTone(input.deadline, now);
  const trackY = 10;

  return (
    <svg
      width={MICRO_WIDTH}
      height={20}
      viewBox={`0 0 ${MICRO_WIDTH} 20`}
      role="img"
      aria-label={ariaLabel(input, previousDeadline, now)}
      className="overflow-visible"
    >
      <Track geometry={geometry} width={MICRO_WIDTH} trackY={trackY} height={20} />
      <Ghost geometry={geometry} input={input} trackY={trackY} radius={2.5} />
      {geometry.nodes.map((node) => (
        <Node key={node.key} node={node} tone={tone} trackY={trackY} radius={3} silent />
      ))}
      <NowMark geometry={geometry} trackY={trackY} height={20} />
    </svg>
  );
}

/* ------------------------------------------------------- meso и macro */

function LabelledRail({
  hostRef,
  scale,
  input,
  previousDeadline,
  now,
}: {
  hostRef: React.RefObject<HTMLDivElement | null>;
  scale: "meso" | "macro";
  input: RailInput;
  previousDeadline: Date | null;
  now?: Date;
}) {
  const width = useElementWidth(hostRef, FALLBACK_WIDTH);
  const measureLabel = useMeasurer(LABEL_FONT);
  const measureDate = useMeasurer(DATE_FONT);

  const geometry = railGeometry(input, { width, pad: 10, now, previousDeadline });
  const tone = deadlineTone(input.deadline, now);
  const maxRows = scale === "macro" ? 2 : 1;

  const stageLabels: LabelInput[] = geometry.nodes.map((node) => ({
    id: node.key,
    x: node.x,
    text: LABELS[node.key],
    shortText: SHORT_LABELS[node.key],
    priority: PRIORITY[node.key],
  }));

  const dateLabels: LabelInput[] =
    scale === "macro"
      ? [
          ...geometry.nodes.map((node) => ({
            id: node.key,
            x: node.x,
            text: node.date ? dateShort(node.date) : "—",
            priority: PRIORITY[node.key],
          })),
          // Призрачный узел участвует в раскладке наравне с прочими, но с
          // низшим приоритетом: тесно — сокращается он.
          ...(geometry.ghostX !== null && previousDeadline
            ? [
                {
                  id: "ghost",
                  x: geometry.ghostX,
                  text: dateShort(previousDeadline),
                  priority: 0,
                },
              ]
            : []),
        ]
      : [];

  const above = layoutLabels(stageLabels, {
    width,
    padding: 10,
    gap: 8,
    maxRows,
    measure: measureLabel,
  });
  const below = layoutLabels(dateLabels, {
    width,
    padding: 10,
    gap: 8,
    maxRows,
    measure: measureDate,
  });

  /**
   * Легенда — решение для шкалы целиком, а не для одной строки подписей.
   * Оставить названия этапов на месте, а даты вынести вниз (или наоборот)
   * значило бы разорвать пару «этап — дата»: именно в этой паре и есть смысл.
   */
  const degraded = above.mode === "legend" || below.mode === "legend";

  const aboveRows = degraded ? 0 : rowCount(above);
  const belowRows = degraded ? 0 : rowCount(below);
  const trackY =
    EDGE_PAD + (aboveRows > 0 ? (aboveRows - 1) * ROW_OFFSET + LABEL_GAP : LABEL_GAP);
  const height =
    trackY + (belowRows > 0 ? DATE_GAP + (belowRows - 1) * ROW_OFFSET : LABEL_GAP) + EDGE_PAD;

  return (
    <>
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={ariaLabel(input, previousDeadline, now)}
        className="overflow-visible"
      >
        <Track geometry={geometry} width={width} trackY={trackY} height={height} />
        <Ghost geometry={geometry} input={input} trackY={trackY} radius={4} />

        {geometry.nodes.map((node) => (
          <Node key={node.key} node={node} tone={tone} trackY={trackY} radius={5} />
        ))}

        <NowMark geometry={geometry} trackY={trackY} height={height} />

        {degraded ? null : (
          <>
            <Labels
              result={above}
              nodeX={(id) => geometry.nodes.find((node) => node.key === id)?.x ?? null}
              y={(row) => trackY - LABEL_GAP - row * ROW_OFFSET}
              leaderFrom={trackY - 6}
              leaderTo={(y) => y + 3}
              className="fill-(--color-text-muted) text-[11px]"
            />
            <Labels
              result={below}
              nodeX={(id) =>
                id === "ghost"
                  ? geometry.ghostX
                  : (geometry.nodes.find((node) => node.key === id)?.x ?? null)
              }
              y={(row) => trackY + DATE_GAP + row * ROW_OFFSET}
              leaderFrom={trackY + 6}
              leaderTo={(y) => y - 11}
              className="fill-(--color-text-muted) font-mono text-[11px]"
            />
          </>
        )}
      </svg>

      {/* Подписи не влезли ни в строку, ни в две — узлы остаются голыми, а
          пары «этап — дата» уходят под шкалу списком. Молча не пропадает
          ни одна: список строится по тем же узлам, что и рисунок. */}
      {degraded ? (
        <Legend
          nodes={geometry.nodes}
          previousDeadline={geometry.ghostX !== null ? previousDeadline : null}
        />
      ) : null}

      {scale === "meso" ? (
        <p className="mt-1 text-body-sm text-text-muted">{relativeDeadline(input.deadline, now)}</p>
      ) : null}

      {scale === "macro" && geometry.shiftDays !== null && geometry.shiftDays !== 0 ? (
        <p className="mt-1 text-body-sm text-oak-fg">
          {ru.tender.deadlineShifted(Math.abs(geometry.shiftDays))}
        </p>
      ) : null}
    </>
  );
}

function rowCount(result: LayoutResult): number {
  if (result.mode === "legend" || result.placements.length === 0) return 0;
  return result.placements.some((placement) => placement.row === 1) ? 2 : 1;
}

/* ---------------------------------------------------------- отрисовка */

function Labels({
  result,
  nodeX,
  y,
  leaderFrom,
  leaderTo,
  className,
}: {
  result: LayoutResult;
  nodeX: (id: string) => number | null;
  y: (row: 0 | 1) => number;
  leaderFrom: number;
  leaderTo: (y: number) => number;
  className: string;
}) {
  if (result.mode === "legend") return null;

  return (
    <>
      {result.placements.map((placement) => {
        const baseline = y(placement.row);
        const origin = nodeX(placement.id);
        const x =
          placement.anchor === "start"
            ? placement.x - placement.width / 2
            : placement.anchor === "end"
              ? placement.x + placement.width / 2
              : placement.x;

        return (
          <g key={placement.id}>
            {/* Выноска рисуется под текстом: подпись уехала от своего узла и
                обязана показать, к какому именно она относится. */}
            {placement.leader && origin !== null ? (
              <line
                x1={origin}
                y1={leaderFrom}
                x2={placement.x}
                y2={leaderTo(baseline)}
                stroke="var(--color-hairline)"
                strokeWidth={1}
              />
            ) : null}
            <text x={x} y={baseline} textAnchor={placement.anchor} className={className}>
              {placement.text}
            </text>
          </g>
        );
      })}
    </>
  );
}

/** Список «этап — дата» под голой шкалой. Порядок — тот же, что на рисунке. */
function Legend({
  nodes,
  previousDeadline,
}: {
  nodes: Geometry["nodes"];
  previousDeadline: Date | null;
}) {
  const rows: { id: string; term: string; value: string }[] = nodes.map((node) => ({
    id: node.key,
    term: LABELS[node.key],
    value: node.date ? dateShort(node.date) : "—",
  }));

  if (previousDeadline) {
    rows.push({
      id: "ghost",
      term: ru.tender.previousDeadline,
      value: dateShort(previousDeadline),
    });
  }

  return (
    <dl className="mt-1.5 grid grid-cols-[repeat(2,minmax(0,1fr))] gap-x-5 gap-y-0.5 text-[11px] text-text-muted">
      {rows.map((row) => (
        <div key={row.id} className="flex min-w-0 items-baseline justify-between gap-2">
          <dt className="truncate">{row.term}</dt>
          <dd className="shrink-0 font-mono tnum">{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}

type Geometry = ReturnType<typeof railGeometry>;

function Track({
  geometry,
  width,
  trackY,
}: {
  geometry: Geometry;
  width: number;
  trackY: number;
  height: number;
}) {
  return (
    <>
      {/* Трек: пройденное — плотной линией, будущее — светлой. */}
      <line
        x1={geometry.pad}
        y1={trackY}
        x2={width - geometry.pad}
        y2={trackY}
        stroke="var(--color-border-strong)"
        strokeWidth={2}
        strokeLinecap="round"
      />
      {geometry.nowX !== null ? (
        <line
          x1={geometry.pad}
          y1={trackY}
          x2={geometry.progressX}
          y2={trackY}
          stroke="var(--color-gos-fg)"
          strokeWidth={2}
          strokeLinecap="round"
        />
      ) : null}
    </>
  );
}

/** Прежний срок подачи: призрачный узел на пунктире. */
function Ghost({
  geometry,
  input,
  trackY,
  radius,
}: {
  geometry: Geometry;
  input: RailInput;
  trackY: number;
  radius: number;
}) {
  if (geometry.ghostX === null || !input.deadline) return null;

  return (
    <g>
      <line
        x1={geometry.ghostX}
        y1={trackY}
        x2={geometry.nodes.find((node) => node.key === "deadline")?.x ?? geometry.ghostX}
        y2={trackY}
        stroke="var(--color-oak-fg)"
        strokeWidth={1}
        strokeDasharray="2 3"
      />
      <circle
        cx={geometry.ghostX}
        cy={trackY}
        r={radius}
        fill="var(--color-surface)"
        stroke="var(--color-oak-fg)"
        strokeWidth={1}
        strokeDasharray="2 2"
      />
    </g>
  );
}

function Node({
  node,
  tone,
  trackY,
  radius,
  silent = false,
}: {
  node: Geometry["nodes"][number];
  tone: "gos" | "oak" | "signal";
  trackY: number;
  radius: number;
  silent?: boolean;
}) {
  const color = !node.known
    ? "var(--color-border-strong)"
    : node.key === "deadline"
      ? `var(--color-${tone}-fg)`
      : "var(--color-gos-fg)";

  return (
    <circle
      cx={node.x}
      cy={trackY}
      r={radius}
      fill={node.known ? color : "var(--color-surface)"}
      stroke={color}
      strokeWidth={node.known ? 0 : 1.5}
    >
      {silent ? null : (
        <title>
          {LABELS[node.key]}
          {node.date ? `: ${dateShort(node.date)}` : `: ${ru.common.notInNotice}`}
        </title>
      )}
    </circle>
  );
}

/** Отметка «сейчас» и общая для всех шкал вертикаль сегодняшнего дня. */
function NowMark({
  geometry,
  trackY,
  height,
}: {
  geometry: Geometry;
  trackY: number;
  height: number;
}) {
  if (geometry.nowX === null) return null;

  return (
    <g>
      <line
        x1={geometry.nowX}
        y1={0}
        x2={geometry.nowX}
        y2={height}
        stroke="var(--color-text-subtle)"
        strokeWidth={1}
        className="rail-nowline"
      />
      <path
        d={`M ${geometry.nowX - 3} ${trackY - 6} L ${geometry.nowX + 3} ${trackY - 6} L ${geometry.nowX} ${trackY - 2} Z`}
        fill="var(--color-text)"
      />
    </g>
  );
}

/**
 * Полная текстовая версия шкалы — то, что услышит скринридер.
 *
 * Собирается из списка дат, а не из раскладки: сокращения, вторая строка и
 * легенда — решения рисунка, и на то, что читает скринридер, они не влияют.
 */
function ariaLabel(input: RailInput, previousDeadline: Date | null, now?: Date): string {
  const parts: string[] = [];
  if (input.published) parts.push(`опубликовано ${dateShort(input.published)}`);
  if (input.deadline) {
    parts.push(`приём заявок до ${dateShort(input.deadline)}`);
    parts.push(relativeDeadline(input.deadline, now));
  }
  if (previousDeadline) parts.push(`прежний срок ${dateShort(previousDeadline)}`);
  return parts.length ? parts.join(", ") : "сроки не указаны";
}
