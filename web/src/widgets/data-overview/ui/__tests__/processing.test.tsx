import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { CorpusProcessing } from "@/shared/api/types";
import { ProcessingPanel } from "../processing";

const corpusProcessing = vi.hoisted(() => vi.fn());

vi.mock("@/shared/api/endpoints", () => ({ endpoints: { corpusProcessing } }));

function state(over: Partial<CorpusProcessing> = {}): CorpusProcessing {
  return {
    embeddings: {
      chunks_total: 2_000_000,
      chunks_embedded: 20_000,
      tenders_total: 15_000,
      tenders_embedded: 400,
      queue_depth: 12,
    },
    today: {
      day: "2026-08-15",
      runs_succeeded: 42,
      runs_failed: 1,
      runs_running: 2,
      saved: 310,
      published_today: 298,
      last_run_at: "2026-08-15T09:30:00Z",
      final: false,
    },
    documents_downloaded: 198_000,
    documents_extracted: 115_000,
    ...over,
  } as CorpusProcessing;
}

async function renderPanel(data: CorpusProcessing) {
  corpusProcessing.mockResolvedValue(data);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ProcessingPanel />
    </QueryClientProvider>,
  );
  await screen.findByText(/Обработка/);
}

beforeEach(() => corpusProcessing.mockReset());

describe("панель обработки", () => {
  it("показывает долю только со знаменателем", async () => {
    await renderPanel(state());

    expect(screen.getByText(/20 000 из 2 000 000 векторизовано/)).toBeInTheDocument();
  });

  it("на пустом корпусе не изобретает ноль процентов", async () => {
    // «0 %» здесь было бы числом, которого никто не считал: делить не на что.
    await renderPanel(
      state({
        embeddings: {
          chunks_total: 0,
          chunks_embedded: 0,
          tenders_total: 0,
          tenders_embedded: 0,
          queue_depth: 0,
        },
      } as Partial<CorpusProcessing>),
    );

    expect(screen.getAllByText(/Фрагментов пока нет/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it("молчащий брокер отличается от пустой очереди", async () => {
    await renderPanel(
      state({
        embeddings: { ...state().embeddings, queue_depth: null },
      } as Partial<CorpusProcessing>),
    );

    expect(screen.getByText(/очередь брокера недоступна/)).toBeInTheDocument();
  });

  it("никогда не называет сегодняшний день закрытым", async () => {
    // Суточный архив ЕИС дописывается до полуночи: «выгружено 42» без этой
    // оговорки читается как «за сегодня всё».
    await renderPanel(state());

    expect(screen.getByText(/День ещё дописывается/)).toBeInTheDocument();
  });

  it("день без запусков говорит об этом прямо", async () => {
    await renderPanel(
      state({
        today: { ...state().today, runs_succeeded: 0, runs_failed: 0, runs_running: 0 },
      } as Partial<CorpusProcessing>),
    );

    expect(screen.getByText(/Сегодня выгрузка ещё не запускалась/)).toBeInTheDocument();
  });
});
