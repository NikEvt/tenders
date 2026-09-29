import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ApiError } from "@/shared/api/client";
import { jobRegistry } from "@/shared/api/job-registry";
import { ToastProvider } from "@/shared/ui/toast";
import { RunningJobs } from "../running-jobs";

const job = vi.hoisted(() => vi.fn());

vi.mock("@/shared/api/endpoints", () => ({ endpoints: { job } }));

function renderShell() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <RunningJobs />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
  jobRegistry.reset();
  job.mockReset();
});

afterEach(() => {
  jobRegistry.reset();
});

describe("указатель идущих операций", () => {
  it("молчит, когда ничего не идёт", () => {
    renderShell();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("показывает операцию, запущенную на другой странице", async () => {
    // Ровно тот случай, ради которого заведён реестр: запуск был в другом
    // разделе, виджет запуска давно размонтирован.
    window.localStorage.setItem(
      "zakupki:jobs",
      JSON.stringify([
        { jobId: "job-1", title: "Идёт прогон…", href: "/research", startedAt: Date.now() },
      ]),
    );
    job.mockResolvedValue({
      job_id: "job-1",
      kind: "research",
      status: "running",
      phase: "обход корпуса",
      total: 100,
      processed: 20,
      result: null,
      error: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });

    renderShell();

    expect(await screen.findByRole("button", { name: /идут операции/i })).toBeInTheDocument();
  });

  it("выселяет задание, которого нет на сервере", async () => {
    // База пересоздана, а `localStorage` пережил. Без выселения указатель
    // опрашивал бы призрака до конца времён.
    jobRegistry.track({ jobId: "job-404", title: "Идёт прогон…", href: "/research" });
    job.mockRejectedValue(new ApiError(404, "GET /jobs/job-404", "Задание не найдено"));

    renderShell();

    await waitFor(() => expect(jobRegistry.snapshot()).toEqual([]));
  });

  it("выселяет завершённое задание", async () => {
    jobRegistry.track({ jobId: "job-done", title: "Идёт прогон…", href: "/research" });
    job.mockResolvedValue({
      job_id: "job-done",
      kind: "research",
      status: "done",
      phase: null,
      total: 100,
      processed: 100,
      result: { run_id: 7 },
      error: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });

    renderShell();

    await waitFor(() => expect(jobRegistry.snapshot()).toEqual([]));
  });
});
