import { describe, expect, it } from "vitest";
import { NBSP } from "@/shared/lib/format";
import {
  ETA_MIN_ELAPSED_MS,
  ETA_MIN_SHARE,
  duration,
  estimateRemaining,
  readProgress,
} from "./job-progress";
import type { Job } from "./types";

const START = Date.parse("2026-08-15T10:00:00Z");

function job(over: Partial<Job> = {}): Job {
  return {
    job_id: "j-1",
    kind: "research",
    status: "running",
    phase: "обход корпуса",
    total: 100,
    processed: 40,
    result: null,
    error: null,
    created_at: new Date(START).toISOString(),
    updated_at: new Date(START).toISOString(),
    ...over,
  } as Job;
}

describe("знаменатель", () => {
  it("считает долю от объёма фазы", () => {
    const progress = readProgress(job({ total: 200, processed: 50 }), { now: START });
    expect(progress?.share).toBe(0.25);
  });

  it("не изобретает долю, когда объём ещё не посчитан", () => {
    // `total = 0` в базе означает «не считали»: `start` зовут до того, как
    // объём работы известен. Ноль здесь никогда не значит «нисколько».
    expect(readProgress(job({ total: 0 }), { now: START })?.share).toBeNull();
    expect(readProgress(job({ total: null }), { now: START })?.share).toBeNull();
  });

  it("не выходит за единицу, если сервер обогнал знаменатель", () => {
    const progress = readProgress(job({ total: 10, processed: 12 }), { now: START });
    expect(progress?.share).toBe(1);
  });
});

describe("оценка остатка", () => {
  it("молчит без знаменателя", () => {
    expect(estimateRemaining(null, 10 * 60_000)).toBeNull();
  });

  it("молчит на первых процентах", () => {
    // Экстраполяция по двум точкам здесь даёт «осталось четыре часа», после
    // чего вкладку закрывают.
    expect(estimateRemaining(ETA_MIN_SHARE / 2, 10 * 60_000)).toBeNull();
  });

  it("молчит первые секунды, даже когда сделано много", () => {
    expect(estimateRemaining(0.5, ETA_MIN_ELAPSED_MS - 1)).toBeNull();
  });

  it("считает по темпу, когда оба порога пройдены", () => {
    // Четверть за минуту — значит три четверти примерно за три минуты.
    expect(estimateRemaining(0.25, 60_000)).toBe(180_000);
  });

  it("на завершённой фазе остатка нет", () => {
    expect(estimateRemaining(1, 60_000)).toBe(0);
  });
});

describe("время фазы против времени задания", () => {
  it("«идёт» считается от старта задания", () => {
    const progress = readProgress(job(), { now: START + 90_000 });
    expect(progress?.elapsedMs).toBe(90_000);
  });

  it("оценка считается от начала фазы, а не задания", () => {
    // Задание идёт полчаса, но судья взялся за работу минуту назад. Перенести
    // темп обхода корпуса на судью значило бы показать выдуманное число.
    const progress = readProgress(job({ phase: "судья читает документы", processed: 25 }), {
      now: START + 30 * 60_000,
      phaseStartedAt: START + 29 * 60_000,
    });

    expect(progress?.remainingMs).toBe(180_000);
  });
});

describe("длительность словами", () => {
  it.each([
    [0, `0${NBSP}с`],
    [12_000, `12${NBSP}с`],
    [60_000, `1${NBSP}мин`],
    [80_000, `1${NBSP}мин 20${NBSP}с`],
    [3_600_000, `1${NBSP}ч`],
    [7_500_000, `2${NBSP}ч 5${NBSP}мин`],
  ])("%i мс → %s", (ms, text) => {
    expect(duration(ms)).toBe(text);
  });

  it("склеивает число с единицей неразрывным пробелом", () => {
    // Подпись стоит в строке, которая переносится: «20» и «с» на разных
    // строках читаются как опечатка.
    expect(duration(12_000)).toContain(NBSP);
  });
});
