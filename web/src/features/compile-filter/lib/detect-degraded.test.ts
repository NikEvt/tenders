import { describe, expect, test } from "vitest";
import type { CriteriaSpec, ResearchResult } from "@/shared/api/types";
import { isDegraded, isFallbackCriteria } from "./detect-degraded";

/**
 * Прежняя эвристика сравнивала слова запроса с `keywords` и смотрела на пустой
 * `llm_criteria`. Обоих полей больше нет, и главное — угадывать не нужно:
 * движок сообщает об отказе модели прямо.
 */
const result = (patch: Partial<ResearchResult> = {}): ResearchResult => ({
  interrupted: false,
  funnel: {
    tenders_total: 100,
    tenders_candidate: 20,
    documents_scanned: 50,
    documents_pending: 0,
    hits_found: 5,
    reviewed: 5,
    rejected_by_rules: 2,
    confirmed_by_rules: 2,
    disputed: 1,
    from_cache: 0,
    asked_model: 1,
    not_reached: 0,
    failed: 0,
    ...(patch.funnel ?? {}),
  },
  ...patch,
});

const spec = (patch: Partial<CriteriaSpec> = {}): CriteriaSpec => ({
  name: "проба",
  terms: [{ name: "ХПК", pattern: "ХПК", role: "primary" }],
  context_rules: [],
  card_pattern: null,
  okpd2_prefixes: [],
  structural: {
    regions: [],
    customer_inns: [],
    price_min: null,
    price_max: null,
    only_active: true,
  },
  version: "v1",
  ...patch,
});

describe("деградация по результату прогона", () => {
  test("обычный прогон деградацией не считается", () => {
    expect(isDegraded(result())).toBe(false);
  });

  test("оборванный прогон — деградация", () => {
    expect(isDegraded(result({ interrupted: true }))).toBe(true);
  });

  test("недошедшие закупки — тоже признак", () => {
    // Модель легла на середине: часть очереди не разобрана, и молчать об этом
    // нельзя — иначе «спорных 8, решено 5» читается как потеря.
    expect(
      isDegraded(result({ funnel: { ...result().funnel!, not_reached: 3 } })),
    ).toBe(true);
  });

  test("отсутствие результата ничего не утверждает", () => {
    expect(isDegraded(null)).toBe(false);
    expect(isDegraded(undefined)).toBe(false);
  });
});

describe("критерий, собранный без модели", () => {
  test("нет ни правил, ни предфильтра — это откат на слова запроса", () => {
    expect(isFallbackCriteria(spec())).toBe(true);
  });

  test("правила по контексту означают, что модель отвечала", () => {
    expect(
      isFallbackCriteria(
        spec({
          context_rules: [
            { name: "объект", pattern: "кровл", verdict: "rejected", window: 60 },
          ],
        }),
      ),
    ).toBe(false);
  });

  test("предфильтра достаточно, чтобы не считать критерий откатом", () => {
    expect(isFallbackCriteria(spec({ card_pattern: "вод|сточн" }))).toBe(false);
  });

  test("пустой критерий откатом не считается", () => {
    expect(isFallbackCriteria(spec({ terms: [] }))).toBe(false);
    expect(isFallbackCriteria(null)).toBe(false);
  });
});
