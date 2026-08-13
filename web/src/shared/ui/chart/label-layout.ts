/**
 * Раскладка подписей на временной оси.
 *
 * Чистая функция без DOM: измерение текста приходит снаружи (`measure`), а
 * значит алгоритм проверяется юнит-тестом без отрисовки и переиспользуется
 * любой будущей осью дат — шкалой сроков, тепловой картой выгрузок, воронкой.
 *
 * Четыре причины наложения и четыре ответа на них:
 *
 * 1. подписи ставились по `x` узла и `text-anchor: middle` без разбора
 *    столкновений — здесь их разводит развёртка минимального смещения;
 * 2. ширина угадывалась по числу символов — здесь она измеряется;
 * 3. измеряли до загрузки шрифта — за это отвечает вызывающая сторона
 *    (`measure` кешируется и сбрасывается по `document.fonts.ready`);
 * 4. не было пути отступления — здесь лестница: полный текст → короткий →
 *    две строки → легенда. Подпись не пропадает молча ни на одной ступени.
 */

export interface LabelInput {
  id: string;
  /** Желаемое положение центра, px, в системе координат дорожки. */
  x: number;
  text: string;
  /** Замена на случай тесноты: «работа комиссии» → «комиссия». */
  shortText?: string;
  /** Выше — сокращается позже. */
  priority: number;
}

export interface LabelPlacement {
  id: string;
  /** Разрешённый центр подписи. */
  x: number;
  /** Измеренная ширина выбранного текста — нужна и рисунку, и тесту. */
  width: number;
  row: 0 | 1;
  anchor: "start" | "middle" | "end";
  /** Возможно, `shortText`. */
  text: string;
  /** Рисовать ли волосяную линию от узла к подписи. */
  leader: boolean;
}

export interface LayoutOptions {
  width: number;
  padding?: number;
  /** Минимальный просвет между подписями. */
  gap?: number;
  /** meso — 1, macro — 2. */
  maxRows: 1 | 2;
  /** Сколько пикселей смещения терпим до перехода на следующую ступень. */
  maxShift?: number;
  measure: (text: string) => number;
}

export type LayoutResult =
  | { mode: "inline"; placements: LabelPlacement[] }
  | { mode: "stacked"; placements: LabelPlacement[] }
  | { mode: "legend"; placements: []; items: LabelInput[] };

/** Насколько вторая строка ниже первой. */
export const ROW_OFFSET = 16;

/** Смещение больше этого перестаёт читаться как «подпись у своего узла». */
const LEADER_THRESHOLD = 3;

const DEFAULTS = { padding: 4, gap: 8, maxShift: 20 } as const;

type Resolved = Required<Omit<LayoutOptions, "measure">> & Pick<LayoutOptions, "measure">;

type Candidate = { input: LabelInput; text: string; width: number };

type Placed = { candidate: Candidate; x: number; shift: number };

/** Сокращение: сначала явная замена, иначе `dd.MM.yyyy` → `dd.MM`. */
function shorten(input: LabelInput): string {
  if (input.shortText) return input.shortText;
  const date = /^(\d{2}\.\d{2})\.\d{4}$/.exec(input.text);
  return date ? date[1]! : input.text;
}

/** Порядок обязан быть полным: при равных `x` сравниваем id, иначе раскладка
 *  зависит от порядка входа и снимок теста «плавает». */
const byX = (a: Candidate, b: Candidate) =>
  a.input.x - b.input.x || (a.input.id < b.input.id ? -1 : a.input.id > b.input.id ? 1 : 0);

const clamp = (value: number, low: number, high: number) =>
  Math.min(Math.max(value, low), Math.max(low, high));

/**
 * Развёртка минимального смещения (классическая упаковка интервалов).
 *
 * Соседи, которые налезают друг на друга, объединяются в группу и кладутся
 * вплотную; группа целиком сдвигается так, чтобы сумма смещений её подписей
 * была наименьшей. Слияние повторяется, пока сдвинутая группа задевает
 * соседнюю слева, — отсюда `while` вместо одного прохода.
 *
 * Детерминированно, O(n log n), без ограничителя итераций: каждое слияние
 * уменьшает число групп.
 */
function sweep(candidates: Candidate[], options: Resolved): Placed[] {
  const { gap, padding, width } = options;

  /**
   * Сначала прижимаем к полям, и только потом разводим столкновения.
   *
   * Порядок важен: подпись у самого края обязана сдвинуться на половину своей
   * ширины просто чтобы не вылезти за viewBox. Считать это «смещением» нельзя —
   * оно неустранимо, ни вторая строка, ни легенда его не уберут, а лестница
   * отступления сработала бы вхолостую на каждой шкале с датой у края.
   * Поэтому смещение меряется от прижатого положения, а не от `x` узла.
   */
  const ideal = new Map<string, number>(
    candidates.map((item) => [
      item.input.id,
      clamp(item.input.x, padding + item.width / 2, width - padding - item.width / 2),
    ]),
  );
  const want = (item: Candidate) => ideal.get(item.input.id)!;

  const sorted = [...candidates].sort(
    (a, b) =>
      want(a) - want(b) || (a.input.id < b.input.id ? -1 : a.input.id > b.input.id ? 1 : 0),
  );

  type Group = { items: Candidate[]; total: number; start: number };

  const build = (items: Candidate[]): Group => {
    const total = items.reduce((sum, item) => sum + item.width, 0) + gap * (items.length - 1);

    // Точный минимум суммы квадратов смещений: start = среднее по
    // (желаемый центр − смещение внутри группы). При равных ширинах это
    // ровно «центр группы минус половина её длины».
    let offset = 0;
    let sum = 0;
    for (const item of items) {
      sum += want(item) - (offset + item.width / 2);
      offset += item.width + gap;
    }

    const start = clamp(sum / items.length, padding, width - padding - total);
    return { items, total, start };
  };

  const groups: Group[] = [];
  for (const candidate of sorted) {
    groups.push(build([candidate]));

    // Сдвиг новой группы мог загнать её в предыдущую — тогда обе становятся
    // одной и пересчитываются, и так вниз по цепочке.
    while (groups.length > 1) {
      const right = groups[groups.length - 1]!;
      const left = groups[groups.length - 2]!;
      if (left.start + left.total + gap <= right.start + 1e-9) break;
      groups.splice(groups.length - 2, 2, build([...left.items, ...right.items]));
    }
  }

  const placed: Placed[] = [];
  for (const group of groups) {
    let cursor = group.start;
    for (const item of group.items) {
      const x = cursor + item.width / 2;
      placed.push({ candidate: item, x, shift: Math.abs(x - want(item)) });
      cursor += item.width + gap;
    }
  }
  return placed;
}

/** Помещается ли ряд: никто не уехал дальше `maxShift` и никто не вылез за поля. */
function fits(placed: Placed[], options: Resolved): boolean {
  const { padding, width, maxShift } = options;
  return placed.every(
    (item) =>
      item.shift <= maxShift + 1e-9 &&
      item.x - item.candidate.width / 2 >= padding - 1e-9 &&
      item.x + item.candidate.width / 2 <= width - padding + 1e-9,
  );
}

/**
 * Крайняя подпись, прижатая к полю, якорится по краю: иначе `middle` вынес бы
 * половину её ширины за viewBox — это второй, отдельный баг наложения.
 */
function toPlacements(placed: Placed[], row: 0 | 1, options: Resolved): LabelPlacement[] {
  const { padding, width } = options;
  const ordered = [...placed].sort((a, b) => a.x - b.x);

  return ordered.map((item, index) => {
    const left = item.x - item.candidate.width / 2;
    const right = item.x + item.candidate.width / 2;

    const anchor: LabelPlacement["anchor"] =
      index === 0 && left <= padding + 0.5
        ? "start"
        : index === ordered.length - 1 && right >= width - padding - 0.5
          ? "end"
          : "middle";

    return {
      id: item.candidate.input.id,
      x: item.x,
      width: item.candidate.width,
      row,
      anchor,
      text: item.candidate.text,
      leader: item.shift > LEADER_THRESHOLD,
    };
  });
}

function singleRow(candidates: Candidate[], options: Resolved): LabelPlacement[] | null {
  const placed = sweep(candidates, options);
  return fits(placed, options) ? toPlacements(placed, 0, options) : null;
}

/** Две строки: чередование по возрастанию `x`, развёртка в каждой отдельно. */
function twoRows(candidates: Candidate[], options: Resolved): LabelPlacement[] | null {
  const sorted = [...candidates].sort(byX);
  const rows: [Candidate[], Candidate[]] = [[], []];
  sorted.forEach((candidate, index) => rows[index % 2 === 0 ? 0 : 1]!.push(candidate));

  const result: LabelPlacement[] = [];
  for (const row of [0, 1] as const) {
    if (rows[row].length === 0) continue;
    const placed = sweep(rows[row], options);
    if (!fits(placed, options)) return null;
    result.push(...toPlacements(placed, row, options));
  }
  return result;
}

function measureAll(
  inputs: readonly LabelInput[],
  shortIds: ReadonlySet<string>,
  measure: (text: string) => number,
): Candidate[] {
  return inputs.map((input) => {
    const text = shortIds.has(input.id) ? shorten(input) : input.text;
    return { input, text, width: measure(text) };
  });
}

/**
 * Лестница отступления. Останавливается на первой ступени, которая помещается.
 *
 * 1. одна строка, полный текст;
 * 2. одна строка, сокращения — по возрастанию приоритета, по одному:
 *    призрачный узел сдвинутого срока получает низкий приоритет и сокращается
 *    первым, заголовки этапов — последними;
 * 3. две строки (только при `maxRows === 2`), сперва полным текстом;
 * 4. легенда — узлы рисуются голыми, подписи уходят под шкалу списком.
 */
export function layoutLabels(inputs: readonly LabelInput[], options: LayoutOptions): LayoutResult {
  const resolved: Resolved = { ...DEFAULTS, ...options };
  if (inputs.length === 0) return { mode: "inline", placements: [] };

  const none = new Set<string>();
  const full = measureAll(inputs, none, options.measure);

  const step1 = singleRow(full, resolved);
  if (step1) return { mode: "inline", placements: step1 };

  const byPriority = [...inputs].sort(
    (a, b) => a.priority - b.priority || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0),
  );

  for (let count = 1; count <= byPriority.length; count += 1) {
    const shortIds = new Set(byPriority.slice(0, count).map((input) => input.id));
    const step2 = singleRow(measureAll(inputs, shortIds, options.measure), resolved);
    if (step2) return { mode: "inline", placements: step2 };
  }

  if (resolved.maxRows === 2) {
    const allShort = new Set(inputs.map((input) => input.id));
    const step3 =
      twoRows(full, resolved) ?? twoRows(measureAll(inputs, allShort, options.measure), resolved);
    if (step3) return { mode: "stacked", placements: step3 };
  }

  return { mode: "legend", placements: [], items: [...inputs] };
}
