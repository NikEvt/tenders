import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import type { DayBucket, Distribution } from "@/shared/api/types";
import { DateHistogram } from "../date-histogram";
import { TopList } from "../top-list";

const DAYS: DayBucket[] = [
  { day: "2026-08-13", count: 40, crawled: true },
  // Выгрузки не было: ноль здесь ничего не говорит о рынке.
  { day: "2026-08-14", count: 0, crawled: false },
  // Выгрузка была, публикаций не было: а вот это уже факт о рынке.
  { day: "2026-08-15", count: 0, crawled: true },
];

function bars(): HTMLElement[] {
  return Array.from(document.querySelectorAll("rect[data-crawled]"));
}

describe("гистограмма публикаций", () => {
  it("рисует каждый день периода, включая пустые", () => {
    render(<DateHistogram days={DAYS} />);
    expect(bars()).toHaveLength(3);
  });

  it("день без выгрузки и день без закупок подписаны по-разному", () => {
    // Главное правило этой вкладки: дыра в наших данных не имеет права
    // выглядеть как утверждение о рынке.
    render(<DateHistogram days={DAYS} />);
    const titles = bars().map((bar) => bar.querySelector("title")?.textContent);

    expect(titles[1]).toMatch(/выгрузки не было/);
    expect(titles[2]).toMatch(/ни одной публикации/);
    expect(titles[1]).not.toBe(titles[2]);
  });

  it("день без выгрузки помечен отдельно и в разметке", () => {
    render(<DateHistogram days={DAYS} />);
    const [crawled, missing] = [bars()[0], bars()[1]];

    expect(crawled).toHaveAttribute("data-crawled", "true");
    expect(missing).toHaveAttribute("data-crawled", "false");
  });

  it("настоящий ноль не занимает высоты, а пропуск занимает всю", () => {
    // Иначе пропуск читался бы как ноль: единственное место, где эта разница
    // видна глазом, — высота столбца.
    render(<DateHistogram days={DAYS} />);
    const [, missing, zero] = bars();

    expect(Number(missing?.getAttribute("height"))).toBeGreaterThan(0);
    expect(Number(zero?.getAttribute("height"))).toBe(0);
  });
});

describe("разрез", () => {
  const distribution: Distribution = {
    top: [
      { key: "77", label: "Москва", count: 18 },
      { key: "78", label: "Санкт-Петербург", count: 7 },
    ],
    others: 10,
    unknown: 5,
    total: 40,
  };

  it("сумма показанного, хвоста и «без признака» равна итогу", () => {
    // Знаменатель: без хвоста двенадцать столбиков читаются как весь корпус.
    render(<TopList distribution={distribution} />);

    expect(screen.getByText("40 из 40")).toBeInTheDocument();
  });

  it("хвост и «без признака» показаны строками, а не спрятаны", () => {
    render(<TopList distribution={distribution} />);

    expect(screen.getByText("Остальные")).toBeInTheDocument();
    expect(screen.getByText("Без кода")).toBeInTheDocument();
  });

  it("нулевой хвост не рисуется", () => {
    render(
      <TopList
        distribution={{ ...distribution, others: 0, unknown: 0, total: 25 }}
      />,
    );

    expect(screen.queryByText("Остальные")).not.toBeInTheDocument();
    expect(screen.getByText("25 из 25")).toBeInTheDocument();
  });
});
