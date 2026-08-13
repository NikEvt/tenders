import { describe, expect, it, test } from "vitest";
import { layoutLabels, type LabelInput, type LayoutOptions } from "./label-layout";
import { stubMeasurer } from "./measure";

const measure = stubMeasurer;

const options = (over: Partial<LayoutOptions> = {}): LayoutOptions => ({
  width: 640,
  padding: 10,
  gap: 8,
  maxRows: 2,
  maxShift: 20,
  measure,
  ...over,
});

const label = (id: string, x: number, text: string, over: Partial<LabelInput> = {}): LabelInput => ({
  id,
  x,
  text,
  priority: 1,
  ...over,
});

/** Подписи реальной шкалы сроков. */
const STAGES = ["публикация", "начало подачи", "окончание подачи", "работа комиссии", "итоги"];
const SHORT = ["публикация", "начало", "окончание", "комиссия", "итоги"];

const stages = (xs: number[]): LabelInput[] =>
  xs.map((x, index) =>
    label(`s${index}`, x, STAGES[index] ?? `этап ${index}`, { shortText: SHORT[index] }),
  );

/* ------------------------------------------------------------- сценарии */

const SCENARIOS: [name: string, nodes: LabelInput[], opts: LayoutOptions][] = [
  ["все четыре даты в один день", stages([300, 300, 300, 300]), options()],
  [
    "публикация и срок подачи в сутках друг от друга на 90-дневной шкале",
    stages([40, 46, 600]),
    options(),
  ],
  [
    "сдвинутый срок добавляет пятый узел",
    [...stages([40, 120, 300, 460, 600]), label("ghost", 305, "прежний срок 12.03.2026", {
      shortText: "прежний срок",
      priority: 0,
    })],
    options(),
  ],
  ["контейнер 240px", stages([20, 60, 120, 180, 220]), options({ width: 240 })],
  ["контейнер 1200px", stages([100, 300, 600, 900, 1150]), options({ width: 1200 })],
  ["одна подпись у левого поля", [label("a", 0, "публикация")], options()],
  ["одна подпись у правого поля", [label("a", 640, "итоги")], options()],
  ["пусто", [], options()],
  ["только даты", ["01.03.2026", "02.03.2026", "03.03.2026"].map((t, i) => label(`d${i}`, 100 + i * 6, t)), options()],
];

/** Коробки подписи в строке, слева направо. */
function boxes(placements: { x: number; width: number; row: number }[], row: number) {
  return placements
    .filter((p) => p.row === row)
    .map((p) => ({ l: p.x - p.width / 2, r: p.x + p.width / 2 }))
    .sort((a, b) => a.l - b.l);
}

describe("лестница отступления", () => {
  test.each(SCENARIOS)("подписи не пересекаются: %s", (_name, nodes, opts) => {
    const result = layoutLabels(nodes, opts);
    if (result.mode === "legend") return;

    for (const row of [0, 1]) {
      const row_ = boxes(result.placements, row);
      row_.forEach((box, index) => {
        if (index === 0) return;
        expect(box.l).toBeGreaterThanOrEqual(row_[index - 1]!.r + (opts.gap ?? 8) - 0.01);
      });
    }
  });

  test.each(SCENARIOS)("подписи остаются внутри полей: %s", (_name, nodes, opts) => {
    const result = layoutLabels(nodes, opts);
    if (result.mode === "legend") return;

    const padding = opts.padding ?? 4;
    for (const placement of result.placements) {
      expect(placement.x - placement.width / 2).toBeGreaterThanOrEqual(padding - 0.01);
      expect(placement.x + placement.width / 2).toBeLessThanOrEqual(opts.width - padding + 0.01);
    }
  });

  test.each(SCENARIOS)("ни одна подпись не теряется: %s", (_name, nodes, opts) => {
    const result = layoutLabels(nodes, opts);
    const seen =
      result.mode === "legend"
        ? result.items.map((item) => item.id)
        : result.placements.map((placement) => placement.id);

    expect([...seen].sort()).toEqual(nodes.map((node) => node.id).sort());
    expect(new Set(seen).size).toBe(nodes.length);
  });

  it("широкая шкала укладывается в одну строку полным текстом", () => {
    const result = layoutLabels(stages([100, 300, 600, 900, 1150]), options({ width: 1200 }));
    expect(result.mode).toBe("inline");
    if (result.mode === "legend") throw new Error("не легенда");
    expect(result.placements.map((p) => p.text)).toEqual(STAGES);
  });

  it("в тесноте сначала сокращается подпись с низшим приоритетом", () => {
    const nodes = [
      label("keep", 100, "окончание подачи", { shortText: "окончание", priority: 5 }),
      label("drop", 150, "работа комиссии", { shortText: "комиссия", priority: 0 }),
    ];
    const result = layoutLabels(nodes, options({ width: 260, maxRows: 1 }));
    if (result.mode !== "inline") throw new Error(`ожидали inline, получили ${result.mode}`);

    const text = new Map(result.placements.map((p) => [p.id, p.text]));
    expect(text.get("drop")).toBe("комиссия");
    expect(text.get("keep")).toBe("окончание подачи");
  });

  it("длинная дата сокращается до dd.MM, когда shortText не задан", () => {
    const nodes = [label("a", 60, "01.03.2026"), label("b", 74, "02.03.2026")];
    const result = layoutLabels(nodes, options({ width: 130, maxRows: 1 }));
    if (result.mode !== "inline") throw new Error(`ожидали inline, получили ${result.mode}`);
    expect(result.placements.map((p) => p.text).sort()).toEqual(["01.03", "02.03"]);
  });

  it("переходит на две строки, когда одна не вмещает даже сокращения", () => {
    // Ни у одной подписи нет `shortText` и ни одна не дата — вторая ступень
    // лестницы бессильна, и остаётся только развести подписи по строкам.
    const nodes = [100, 180, 260, 340, 420].map((x, index) =>
      label(`s${index}`, x, STAGES[index]!),
    );
    const result = layoutLabels(nodes, options({ maxShift: 4 }));
    expect(result.mode).toBe("stacked");
    if (result.mode !== "stacked") return;

    expect(new Set(result.placements.map((p) => p.row))).toEqual(new Set([0, 1]));
    // Чередование по возрастанию x: соседи по шкале никогда не в одной строке.
    const rows = [...result.placements]
      .sort((a, b) => a.x - b.x)
      .map((p) => p.row);
    expect(rows).toEqual([0, 1, 0, 1, 0]);
  });

  it("при maxRows = 1 вторая строка недоступна — сразу легенда", () => {
    const nodes = stages([120, 124, 128, 132, 136]);
    const result = layoutLabels(nodes, options({ width: 200, maxRows: 1, maxShift: 4 }));
    expect(result.mode).toBe("legend");
    if (result.mode !== "legend") return;
    expect(result.items).toHaveLength(nodes.length);
  });

  it("уводит в легенду, когда подпись шире всего контейнера", () => {
    const nodes = [label("a", 50, "окончание срока подачи заявок на участие")];
    const result = layoutLabels(nodes, options({ width: 120 }));
    expect(result.mode).toBe("legend");
  });

  it("крайние подписи якорятся по краю, а не по центру", () => {
    const nodes = stages([0, 300, 640]);
    const result = layoutLabels(nodes, options({ width: 640 }));
    if (result.mode === "legend") throw new Error("не легенда");

    const ordered = [...result.placements].sort((a, b) => a.x - b.x);
    expect(ordered[0]!.anchor).toBe("start");
    expect(ordered[ordered.length - 1]!.anchor).toBe("end");
    expect(ordered[1]!.anchor).toBe("middle");
  });

  it("сдвинутая подпись получает выноску, стоящая на месте — нет", () => {
    // 300 и 372: коробки задевают друг друга, развёртка разводит их на ~3.7px.
    const nudged = layoutLabels(stages([300, 372]), options());
    if (nudged.mode === "legend") throw new Error("не легенда");
    expect(nudged.placements.every((p) => p.leader)).toBe(true);

    // 300 и 380: просвет уже достаточный, никто не двигается.
    const calm = layoutLabels(stages([300, 380]), options());
    if (calm.mode === "legend") throw new Error("не легенда");
    expect(calm.placements.every((p) => !p.leader)).toBe(true);
  });

  it("прижатая к краю подпись не считается сдвинутой", () => {
    // Иначе лестница отступления срабатывала бы вхолостую на каждой шкале,
    // у которой дата стоит у самого края.
    const result = layoutLabels([label("a", 0, "публикация")], options());
    if (result.mode !== "inline") throw new Error(`ожидали inline, получили ${result.mode}`);
    expect(result.placements[0]!.leader).toBe(false);
    expect(result.placements[0]!.anchor).toBe("start");
  });

  it("раскладка детерминирована: тот же вход — тот же результат", () => {
    const nodes = stages([40, 46, 300, 460, 600]);
    expect(layoutLabels(nodes, options())).toEqual(layoutLabels([...nodes], options()));
  });
});

/* ---------------------------------------------------- случайные наборы */

/** mulberry32: воспроизводимый генератор — падение теста можно повторить. */
function random(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

describe("случайные наборы узлов", () => {
  it("500 наборов: без пересечений, без потерь, внутри полей", () => {
    const next = random(20260809);

    for (let run = 0; run < 500; run += 1) {
      const width = 200 + Math.floor(next() * 1000);
      const count = 1 + Math.floor(next() * 8);
      const padding = 4 + Math.floor(next() * 8);
      const gap = 4 + Math.floor(next() * 8);
      const maxRows = next() < 0.5 ? 1 : 2;

      const nodes: LabelInput[] = Array.from({ length: count }, (_, index) => {
        const stage = Math.floor(next() * STAGES.length);
        return label(`n${index}`, next() * width, STAGES[stage]!, {
          shortText: SHORT[stage],
          priority: Math.floor(next() * 3),
        });
      });

      const opts = options({ width, padding, gap, maxRows: maxRows as 1 | 2 });
      const result = layoutLabels(nodes, opts);

      const seen =
        result.mode === "legend"
          ? result.items.map((item) => item.id)
          : result.placements.map((placement) => placement.id);
      expect(new Set(seen).size, `набор ${run}: подпись потерялась или задвоилась`).toBe(count);

      if (result.mode === "legend") continue;

      for (const row of [0, 1]) {
        const row_ = boxes(result.placements, row);
        row_.forEach((box, index) => {
          if (index === 0) return;
          expect(
            box.l,
            `набор ${run}, строка ${row}: подписи наложились`,
          ).toBeGreaterThanOrEqual(row_[index - 1]!.r + gap - 0.01);
        });
      }

      for (const placement of result.placements) {
        expect(placement.x - placement.width / 2).toBeGreaterThanOrEqual(padding - 0.01);
        expect(placement.x + placement.width / 2).toBeLessThanOrEqual(width - padding + 0.01);
      }
    }
  });
});
