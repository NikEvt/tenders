import { describe, expect, it } from "vitest";
import { deadlineTone, railGeometry } from "./geometry";

const now = new Date("2026-08-08T10:00:00");
const day = (offset: number) => new Date(now.getTime() + offset * 86_400_000);

describe("геометрия шкалы сроков", () => {
  it("ставит узлы в хронологическом порядке", () => {
    const geometry = railGeometry(
      { published: day(-8), start: day(-7), deadline: day(6) },
      { width: 120, now },
    );
    const xs = geometry.nodes.filter((n) => n.known).map((n) => n.x);
    expect(xs).toEqual([...xs].sort((a, b) => a - b));
  });

  it("не даёт узлам слипнуться, когда даты почти совпадают", () => {
    const geometry = railGeometry(
      { published: day(-8), start: day(-8), deadline: day(6) },
      { width: 120, now },
    );
    const [first, second] = geometry.nodes;
    expect(second!.x - first!.x).toBeGreaterThanOrEqual(8);
  });

  it("отметка «сейчас» лежит между первой и последней датой", () => {
    const geometry = railGeometry(
      { published: day(-8), deadline: day(6) },
      { width: 120, now },
    );
    expect(geometry.nowX).toBeGreaterThan(geometry.nodes[0]!.x);
    expect(geometry.nowX).toBeLessThan(geometry.nodes[geometry.nodes.length - 1]!.x);
  });

  it("прижимает «сейчас» к началу, если публикация ещё впереди", () => {
    const geometry = railGeometry({ published: day(3), deadline: day(10) }, { width: 120, now });
    expect(geometry.nowX).toBe(geometry.pad);
  });

  it("оставляет справа место под этапы, дат которых ЕИС не передаёт", () => {
    const geometry = railGeometry(
      { published: day(-8), start: day(-7), deadline: day(6) },
      { width: 200, now },
    );
    const unknown = geometry.nodes.filter((node) => !node.known);
    expect(unknown.map((node) => node.key)).toEqual(["commission", "summing"]);
    expect(unknown[0]!.x).toBeGreaterThan(geometry.nodes[2]!.x);
  });

  it("считает сдвиг срока в днях и помнит прежнее положение", () => {
    const geometry = railGeometry(
      { published: day(-8), deadline: day(6) },
      { width: 200, now, previousDeadline: day(1) },
    );
    expect(geometry.shiftDays).toBe(5);
    expect(geometry.ghostX).not.toBeNull();
    expect(geometry.ghostX!).toBeLessThan(geometry.nodes.find((n) => n.key === "deadline")!.x);
  });

  it("не падает, когда дат нет вовсе", () => {
    const geometry = railGeometry({}, { width: 120, now });
    expect(geometry.nowX).toBeNull();
    expect(geometry.progressX).toBe(geometry.pad);
  });

  it("держит все узлы внутри отведённой ширины", () => {
    const geometry = railGeometry(
      { published: day(-40), start: day(-39), deadline: day(1) },
      { width: 120, pad: 4, now },
    );
    for (const node of geometry.nodes) {
      expect(node.x).toBeGreaterThanOrEqual(4);
      expect(node.x).toBeLessThanOrEqual(116);
    }
  });
});

describe("цвет узла срока подачи", () => {
  it("спокойный, пока до срока больше трёх суток", () => {
    expect(deadlineTone(day(5), now)).toBe("gos");
  });

  it("тревожный за трое суток", () => {
    expect(deadlineTone(day(2), now)).toBe("oak");
  });

  it("красный, когда срок прошёл", () => {
    expect(deadlineTone(day(-1), now)).toBe("signal");
  });
});
