/**
 * Геометрия «шкалы сроков».
 *
 * Вынесена из компонента, потому что это единственная арифметика в интерфейсе,
 * которую стоит покрыть тестами: рельс — то, что аналитик читает взглядом, и
 * сдвинутый на пару пикселей узел врёт молча.
 */

export type RailKey = "published" | "start" | "deadline" | "commission" | "summing";

export type RailInput = {
  published?: Date | null;
  start?: Date | null;
  deadline?: Date | null;
  commission?: Date | null;
  summing?: Date | null;
};

export type RailNode = {
  key: RailKey;
  date: Date | null;
  x: number;
  /** Известные даты — залитый узел, неизвестные будущие этапы — полый. */
  known: boolean;
};

export type RailGeometry = {
  width: number;
  pad: number;
  /** x «сейчас», null — если шкала целиком в будущем или дат не хватает. */
  nowX: number | null;
  nodes: RailNode[];
  /** До какого x трек залит цветом «прошло». */
  progressX: number;
  /** x прежнего срока подачи, если крайний срок сдвигали. */
  ghostX: number | null;
  /** Насколько сдвинули, в днях. Отрицательное — срок приблизили. */
  shiftDays: number | null;
};

const MIN_GAP = 8;
const DAY_MS = 86_400_000;

/** Порядок этапов — он же порядок чтения. */
export const RAIL_ORDER: RailKey[] = ["published", "start", "deadline", "commission", "summing"];

/**
 * ЕИС не передаёт даты работы комиссии и подведения итогов. Вместо того чтобы
 * их выдумывать, шкала оставляет справа зону «дальше неизвестно» и рисует там
 * полые узлы на пунктире. Доля ширины под эту зону:
 */
const UNKNOWN_TAIL_SHARE = 0.22;

export function railGeometry(
  input: RailInput,
  options: {
    width: number;
    pad?: number;
    now?: Date;
    previousDeadline?: Date | null;
  },
): RailGeometry {
  const { width, pad = 4, now = new Date(), previousDeadline = null } = options;
  const usable = Math.max(1, width - pad * 2);

  const entries = RAIL_ORDER.map((key) => ({ key, date: input[key] ?? null }));
  const known = entries.filter((e): e is { key: RailKey; date: Date } => e.date instanceof Date);

  if (known.length === 0) {
    return {
      width,
      pad,
      nowX: null,
      nodes: entries.map((e) => ({ ...e, x: pad, known: false })),
      progressX: pad,
      ghostX: null,
      shiftDays: null,
    };
  }

  const times = known.map((e) => e.date.getTime());
  if (previousDeadline) times.push(previousDeadline.getTime());
  const t0 = Math.min(...times);
  const t1 = Math.max(...times);

  // Есть ли неизвестный «хвост» — этапы правее последней известной даты.
  const lastKnownIndex = RAIL_ORDER.indexOf(known[known.length - 1]!.key);
  const hasUnknownTail = lastKnownIndex < RAIL_ORDER.length - 1;
  const knownWidth = hasUnknownTail ? usable * (1 - UNKNOWN_TAIL_SHARE) : usable;

  const scale = (time: number): number => {
    if (t1 === t0) return pad;
    return pad + ((time - t0) / (t1 - t0)) * knownWidth;
  };

  const positions = new Map<RailKey, number>();
  let previousX = -Infinity;
  for (const entry of known) {
    const x = Math.max(scale(entry.date.getTime()), previousX + MIN_GAP);
    positions.set(entry.key, Math.min(x, pad + knownWidth));
    previousX = positions.get(entry.key)!;
  }

  // Неизвестные этапы раскладываются ровно по остатку — порядок здесь и есть
  // вся информация, точных дат у нас нет.
  const unknownKeys = RAIL_ORDER.slice(lastKnownIndex + 1);
  const tailStart = pad + knownWidth;
  const tailEnd = pad + usable;
  unknownKeys.forEach((key, index) => {
    const step = (tailEnd - tailStart) / unknownKeys.length;
    positions.set(key, tailStart + step * (index + 1));
  });

  const nodes: RailNode[] = entries
    .filter((entry) => positions.has(entry.key))
    .map((entry) => ({
      key: entry.key,
      date: entry.date,
      x: positions.get(entry.key)!,
      known: entry.date !== null,
    }));

  const nowTime = now.getTime();
  const nowX =
    nowTime <= t0 ? pad : nowTime >= t1 ? Math.min(pad + knownWidth, tailEnd) : scale(nowTime);

  const ghostX = previousDeadline ? scale(previousDeadline.getTime()) : null;
  const currentDeadline = input.deadline ?? null;
  const shiftDays =
    previousDeadline && currentDeadline
      ? Math.round((currentDeadline.getTime() - previousDeadline.getTime()) / DAY_MS)
      : null;

  return { width, pad, nowX, nodes, progressX: nowX, ghostX, shiftDays };
}

/** Цвет узла срока подачи: за трое суток он становится тревожным. */
export function deadlineTone(
  deadline: Date | null | undefined,
  now: Date = new Date(),
): "gos" | "oak" | "signal" {
  if (!deadline) return "gos";
  const hours = (deadline.getTime() - now.getTime()) / 3_600_000;
  if (hours <= 0) return "signal";
  if (hours < 72) return "oak";
  return "gos";
}
