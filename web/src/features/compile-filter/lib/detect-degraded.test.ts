import { describe, expect, it } from "vitest";
import type { FilterSpec } from "@/shared/api/types";
import { isDegraded } from "./detect-degraded";

function spec(patch: Partial<FilterSpec>): FilterSpec {
  return {
    keywords: [],
    okpd2_prefixes: [],
    price_min: null,
    price_max: null,
    regions: [],
    customer_inns: [],
    date_range: null,
    only_active: true,
    semantic_query: "",
    llm_criteria: "",
    ...patch,
  };
}

describe("определение деградированного режима", () => {
  const query = "поставка ламп с гарантией не менее трёх лет";

  it("непустой критерий судьи — модель работает", () => {
    expect(isDegraded(query, spec({ llm_criteria: "гарантия не менее 3 лет" }))).toBe(false);
  });

  it("ключевые слова, повторяющие запрос, — это фолбэк без модели", () => {
    expect(
      isDegraded(
        query,
        spec({ keywords: ["поставка", "ламп", "гарантией", "менее", "трёх", "лет"] }),
      ),
    ).toBe(true);
  });

  it("осмысленно выбранные слова — не деградация, а нормальный дешёвый путь", () => {
    expect(isDegraded(query, spec({ keywords: ["лампы", "гарантия"] }))).toBe(false);
  });

  it("короткий запрос не считается деградацией даже без критерия", () => {
    expect(isDegraded("поставка газа", spec({ keywords: ["поставка", "газа"] }))).toBe(false);
  });

  it("пустой ответ не роняет проверку", () => {
    expect(isDegraded(query, null)).toBe(false);
  });
});
