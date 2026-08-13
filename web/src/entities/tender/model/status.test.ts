import { describe, expect, it } from "vitest";
import { tenderStatus } from "./status";

/**
 * Правило должно совпадать с `Tender.status_at` из
 * services/crawler/domain/models.py. Тесты повторяют его ветки по порядку:
 * если бэкенд поменяет правило, здесь станет красно.
 */
describe("вычисление статуса закупки", () => {
  const now = new Date("2026-08-08T10:00:00");

  it("публикация в будущем — запланирована", () => {
    expect(tenderStatus({ publish_date: "2026-08-10T00:00:00" }, now).code).toBe("planned");
  });

  it("срок подачи не истёк — идёт приём заявок", () => {
    const status = tenderStatus(
      { publish_date: "2026-08-01T00:00:00", end_date: "2026-08-14T17:00:00" },
      now,
    );
    expect(status.code).toBe("collecting");
    expect(status.tone).toBe("gos");
  });

  it("срок истёк — работа комиссии", () => {
    expect(
      tenderStatus(
        { publish_date: "2026-07-01T00:00:00", end_date: "2026-08-04T17:00:00" },
        now,
      ).code,
    ).toBe("bidding");
  });

  it("итоги подведены раньше сегодняшнего дня — завершена", () => {
    expect(
      tenderStatus(
        {
          publish_date: "2026-07-01T00:00:00",
          end_date: "2026-07-20T17:00:00",
          summarizing_date: "2026-08-01T00:00:00",
        },
        now,
      ).code,
    ).toBe("finished");
  });

  it("без дат — неизвестно, и это отдельное состояние, а не «завершена»", () => {
    expect(tenderStatus({}, now).code).toBe("unknown");
  });

  it("всегда сообщает, что статус вычислен, а не получен из ЕИС", () => {
    expect(tenderStatus({ end_date: "2026-08-14T17:00:00" }, now).source).toBe("computed");
  });
});
