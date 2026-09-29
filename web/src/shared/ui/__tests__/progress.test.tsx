import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Progress } from "@/shared/ui/progress";
import { PendingBlock } from "@/shared/ui/pending-block";
import type { Job } from "@/shared/api/types";

function job(over: Partial<Job> = {}): Job {
  return {
    job_id: "j-1",
    kind: "research",
    status: "running",
    phase: "судья читает документы",
    total: 380,
    processed: 142,
    result: null,
    error: null,
    created_at: new Date(Date.now() - 80_000).toISOString(),
    updated_at: new Date().toISOString(),
    ...over,
  } as Job;
}

describe("шкала", () => {
  it("определённая объявляет долю и её текстовую версию", () => {
    render(<Progress value={0.37} label="обработано 142 из 380" />);
    const bar = screen.getByRole("progressbar");

    expect(bar).toHaveAttribute("aria-valuenow", "37");
    expect(bar).toHaveAttribute("aria-valuetext", "обработано 142 из 380");
  });

  it("неопределённая не объявляет доли вовсе", () => {
    // Знаменателя нет — значит нет и числа. «0 %» здесь было бы выдумкой.
    render(<Progress label="объём работы ещё не известен" />);
    const bar = screen.getByRole("progressbar");

    expect(bar).not.toHaveAttribute("aria-valuenow");
    expect(bar).toHaveAttribute("aria-valuetext", "объём работы ещё не известен");
  });
});

describe("блок ожидания", () => {
  it("называет фазу, а не только операцию", () => {
    render(<PendingBlock title="Идёт прогон…" job={job()} />);

    expect(screen.getByText("судья читает документы")).toBeInTheDocument();
  });

  it("показывает счётчик со знаменателем", () => {
    render(<PendingBlock title="Идёт прогон…" job={job()} />);

    expect(screen.getByText(/142 из 380/)).toBeInTheDocument();
  });

  it("без знаменателя признаётся, что объём ещё не считали", () => {
    render(<PendingBlock title="Пересобираем сводку…" job={job({ total: null })} />);

    expect(screen.getByText(/считаем объём работы/)).toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it("не оценивает остаток на первых процентах", () => {
    render(<PendingBlock title="Идёт прогон…" job={job({ processed: 4, total: 380 })} />);

    expect(screen.queryByText(/осталось/)).not.toBeInTheDocument();
  });

  it("оценивает остаток, когда оба порога пройдены", () => {
    // Идёт 80 секунд, сделано больше десятой части — темп уже что-то значит.
    render(<PendingBlock title="Идёт прогон…" job={job()} />);

    expect(screen.getByText(/осталось ≈/)).toBeInTheDocument();
  });

  it("ошибка вытесняет шкалу и зовёт повторить", () => {
    render(
      <PendingBlock
        title="Идёт прогон…"
        job={job({ status: "failed", error: "модель недоступна" })}
        onRetry={() => {}}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("модель недоступна");
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });
});
