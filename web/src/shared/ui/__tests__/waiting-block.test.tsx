import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { WaitingBlock } from "@/shared/ui/waiting-block";

beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
afterEach(() => vi.useRealTimers());

describe("ожидание без задания", () => {
  it("не занимает места, пока ждать нечего", () => {
    const { container } = render(<WaitingBlock title="Ищем…" startedAt={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("шкала неопределённая: знаменателя у такой операции нет", () => {
    render(<WaitingBlock title="Ищем…" startedAt={Date.now()} />);
    const bar = screen.getByRole("progressbar");

    expect(bar).not.toHaveAttribute("aria-valuenow");
  });

  it("приписка про затянувшееся ожидание приходит по времени, а не сразу", () => {
    render(
      <WaitingBlock
        title="Ищем…"
        startedAt={Date.now()}
        hint="модель прогревается"
        hintAfterMs={5000}
      />,
    );

    expect(screen.queryByText("модель прогревается")).not.toBeInTheDocument();

    act(() => void vi.advanceTimersByTime(6000));

    expect(screen.getByText("модель прогревается")).toBeInTheDocument();
  });

  it("часы идут сами, не дожидаясь ответа сервера", () => {
    render(<WaitingBlock title="Ищем…" startedAt={Date.now()} />);

    act(() => void vi.advanceTimersByTime(12_000));

    expect(screen.getByText(/идёт 12/)).toBeInTheDocument();
  });
});
