import { beforeEach, describe, expect, it } from "vitest";
import { jobRegistry } from "./job-registry";

const STORAGE_KEY = "zakupki:jobs";
const DAY_MS = 24 * 60 * 60 * 1000;

beforeEach(() => {
  window.localStorage.clear();
  jobRegistry.reset();
});

function track(jobId: string) {
  jobRegistry.track({ jobId, title: "Идёт прогон…", href: "/research" });
}

describe("реестр идущих операций", () => {
  it("помнит запущенное", () => {
    track("job-1");
    expect(jobRegistry.snapshot().map((j) => j.jobId)).toEqual(["job-1"]);
  });

  it("не заводит вторую запись на тот же идентификатор", () => {
    track("job-1");
    track("job-1");
    expect(jobRegistry.snapshot()).toHaveLength(1);
  });

  it("переживает перезагрузку страницы", () => {
    // Уход со страницы и полная перезагрузка — один и тот же случай: опрос
    // обязан продолжиться, а не начаться заново.
    track("job-1");
    jobRegistry.reset();
    jobRegistry.hydrate();

    expect(jobRegistry.snapshot().map((j) => j.jobId)).toEqual(["job-1"]);
  });

  it("выселяет завершённое", () => {
    track("job-1");
    jobRegistry.forget("job-1");

    expect(jobRegistry.snapshot()).toEqual([]);
    jobRegistry.reset();
    jobRegistry.hydrate();
    expect(jobRegistry.snapshot()).toEqual([]);
  });

  it("не поднимает записи старше суток", () => {
    // База пересоздана, а `localStorage` пережил. Без этого правила реестр
    // опрашивал бы несуществующее задание по разу в пять секунд вечно.
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify([
        { jobId: "древнее", title: "…", href: "/", startedAt: Date.now() - DAY_MS - 1 },
        { jobId: "свежее", title: "…", href: "/", startedAt: Date.now() },
      ]),
    );

    jobRegistry.hydrate();

    expect(jobRegistry.snapshot().map((j) => j.jobId)).toEqual(["свежее"]);
  });

  it("переживает испорченное хранилище", () => {
    window.localStorage.setItem(STORAGE_KEY, "{это не список}");
    jobRegistry.hydrate();

    expect(jobRegistry.snapshot()).toEqual([]);
  });

  it("сообщает подписчикам об изменениях", () => {
    let notified = 0;
    jobRegistry.subscribe(() => (notified += 1));

    track("job-1");
    jobRegistry.forget("job-1");

    expect(notified).toBe(2);
  });
});
