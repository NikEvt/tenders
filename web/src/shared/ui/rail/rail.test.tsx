import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Rail } from "./rail";
import * as measure from "@/shared/ui/chart/measure";

const now = new Date("2026-08-08T10:00:00");
const day = (offset: number) => new Date(now.getTime() + offset * 86_400_000);

describe("шкала сроков", () => {
  it("micro не рисует подписей и ничего не измеряет", () => {
    // Шестьдесят строк списка: любая работа здесь умножается на шестьдесят.
    const spy = vi.spyOn(measure, "makeMeasurer");

    const { container } = render(
      <Rail published={day(-8)} start={day(-7)} deadline={day(6)} scale="micro" now={now} />,
    );

    expect(container.querySelectorAll("text")).toHaveLength(0);
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });

  it("на широкой шкале этапы подписаны прямо на рисунке", () => {
    // ResizeObserver в jsdom нет, ширину задаёт запасное значение — поэтому
    // проверяем инвариант, а не конкретную ступень лестницы.
    const { container } = render(
      <Rail published={day(-8)} start={day(-7)} deadline={day(6)} scale="macro" now={now} />,
    );

    const inline = container.querySelectorAll("text").length > 0;
    const legend = container.querySelector("dl") !== null;
    expect(inline || legend).toBe(true);
  });

  it("ни один этап не пропадает: что не влезло на рисунок, уходит в легенду", () => {
    const { container } = render(
      <Rail published={day(-8)} start={day(-7)} deadline={day(6)} scale="macro" now={now} />,
    );

    const text = container.textContent ?? "";
    for (const stage of ["публикация", "начало", "окончание", "комиссия", "итоги"]) {
      expect(text.toLowerCase(), `этап «${stage}» потерялся`).toContain(stage);
    }
  });

  it("aria-label собирается из дат, а не из раскладки", () => {
    const { container } = render(
      <Rail
        published={day(-8)}
        deadline={day(6)}
        previousDeadline={day(1)}
        scale="macro"
        now={now}
      />,
    );

    const label = container.querySelector("svg")?.getAttribute("aria-label") ?? "";
    expect(label).toContain("опубликовано");
    expect(label).toContain("приём заявок до");
    expect(label).toContain("прежний срок");
  });

  it("шкала без дат не падает", () => {
    const { container } = render(<Rail scale="macro" now={now} />);
    expect(container.querySelector("svg")?.getAttribute("aria-label")).toBe("сроки не указаны");
  });
});
