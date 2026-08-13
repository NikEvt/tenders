import { describe, expect, it } from "vitest";
import {
  DEFAULT_SORT,
  FALLBACK_SORT,
  GROUPABLE_FIELDS,
  SORT_FIELDS,
  TIE_BREAK,
  defaultKey,
  describeSort,
  isAvailable,
  parseCollapsed,
  parseGroup,
  parseSort,
  requestSort,
  serializeCollapsed,
  serializeSort,
  sortField,
  toApiSort,
} from "./sort";

const withQuery = { q: "ремонт кровли" };
const noQuery = {};

describe("реестр", () => {
  it("описывает семь полей, у каждого — направления словами", () => {
    expect(SORT_FIELDS).toHaveLength(7);
    for (const field of SORT_FIELDS) {
      expect(field.dirLabels.asc, `${field.id}: нет подписи asc`).toBeTruthy();
      expect(field.dirLabels.desc, `${field.id}: нет подписи desc`).toBeTruthy();
      expect(field.dirLabels.asc).not.toBe(field.dirLabels.desc);
    }
  });

  it("идентификаторы уникальны", () => {
    expect(new Set(SORT_FIELDS.map((f) => f.id)).size).toBe(SORT_FIELDS.length);
  });

  it("группировать можно по трём категорийным полям", () => {
    expect(GROUPABLE_FIELDS.map((f) => f.id)).toEqual(["okpd", "customer", "region"]);
    for (const field of GROUPABLE_FIELDS) {
      expect(field.groupLabel, `${field.id}: нет подписи для шапки группы`).toBeTruthy();
    }
  });

  it("релевантность доступна только при поисковом запросе", () => {
    const relevance = sortField("relevance")!;
    expect(isAvailable(relevance, withQuery)).toBe(true);
    expect(isAvailable(relevance, noQuery)).toBe(false);
    expect(isAvailable(relevance, { q: "   " })).toBe(false);
    expect(isAvailable(sortField("deadline")!, noQuery)).toBe(true);
  });

  it("смена поля берёт его направление по умолчанию", () => {
    expect(defaultKey("deadline")).toEqual({ field: "deadline", dir: "asc" });
    expect(defaultKey("price")).toEqual({ field: "price", dir: "desc" });
    expect(defaultKey("customer")).toEqual({ field: "customer", dir: "asc" });
    expect(defaultKey("нет такого")).toEqual(DEFAULT_SORT);
  });
});

describe("разбор адреса", () => {
  it("круговой перегон одного ключа", () => {
    const keys = parseSort("deadline:asc", withQuery);
    expect(keys).toEqual([{ field: "deadline", dir: "asc" }]);
    expect(serializeSort(keys)).toBe("deadline:asc");
  });

  it("круговой перегон нескольких ключей", () => {
    const raw = "okpd:asc,price:desc";
    expect(serializeSort(parseSort(raw, withQuery))).toBe(raw);
  });

  it("пустая строка даёт сортировку по умолчанию", () => {
    expect(parseSort("", withQuery)).toEqual([DEFAULT_SORT]);
    expect(parseSort(null, withQuery)).toEqual([DEFAULT_SORT]);
    expect(parseSort(undefined, withQuery)).toEqual([DEFAULT_SORT]);
  });

  it("неизвестное поле отбрасывается, остальные остаются", () => {
    expect(parseSort("выдумка:asc,price:desc", withQuery)).toEqual([
      { field: "price", dir: "desc" },
    ]);
  });

  it("устаревшая закладка целиком из неизвестных полей не роняет экран", () => {
    expect(parseSort("выдумка:asc,ещё:desc", withQuery)).toEqual([DEFAULT_SORT]);
  });

  it("неизвестное направление заменяется умолчанием поля", () => {
    expect(parseSort("deadline:вверх", withQuery)).toEqual([{ field: "deadline", dir: "asc" }]);
    expect(parseSort("price", withQuery)).toEqual([{ field: "price", dir: "desc" }]);
  });

  it("недоступная сортировка подменяется, а не показывается ошибкой", () => {
    // Ссылку с `sort=relevance` прислали без запроса — каталог обязан открыться.
    expect(parseSort("relevance:desc", noQuery)).toEqual([FALLBACK_SORT]);
    expect(parseSort("", noQuery)).toEqual([FALLBACK_SORT]);
  });

  it("повторы одного поля схлопываются", () => {
    expect(parseSort("price:asc,price:desc", withQuery)).toEqual([{ field: "price", dir: "asc" }]);
  });

  it("доборный ключ из адреса игнорируется — его ставит только код", () => {
    expect(parseSort("id:desc,price:asc", withQuery)).toEqual([{ field: "price", dir: "asc" }]);
  });

  it("мусор вокруг разделителей не мешает", () => {
    expect(parseSort(" deadline:asc , , price:desc ", withQuery)).toEqual([
      { field: "deadline", dir: "asc" },
      { field: "price", dir: "desc" },
    ]);
  });
});

describe("группировка", () => {
  it("принимает только группируемые поля", () => {
    expect(parseGroup("customer")).toBe("customer");
    expect(parseGroup("okpd")).toBe("okpd");
    expect(parseGroup("price")).toBeNull();
    expect(parseGroup("")).toBeNull();
    expect(parseGroup("выдумка")).toBeNull();
  });

  it("ключ группы становится главным, доборный — последним", () => {
    expect(requestSort([{ field: "price", dir: "desc" }], "customer")).toEqual([
      { field: "customer", dir: "asc" },
      { field: "price", dir: "desc" },
      TIE_BREAK,
    ]);
  });

  it("без группировки порядок — выбранный ключ и добор", () => {
    expect(requestSort([{ field: "deadline", dir: "asc" }], null)).toEqual([
      { field: "deadline", dir: "asc" },
      TIE_BREAK,
    ]);
  });

  it("группировка по тому же полю, по которому сортируем, не задваивает ключ", () => {
    expect(requestSort([{ field: "customer", dir: "desc" }], "customer")).toEqual([
      { field: "customer", dir: "asc" },
      TIE_BREAK,
    ]);
  });

  it("доборный ключ есть всегда", () => {
    for (const field of SORT_FIELDS) {
      const keys = requestSort([defaultKey(field.id)], null);
      expect(keys[keys.length - 1], `${field.id}: потерян добор`).toEqual(TIE_BREAK);
    }
  });

  it("строка для API собирается из apiField", () => {
    expect(toApiSort([{ field: "price", dir: "desc" }], "okpd")).toBe(
      "okpd:asc,price:desc,id:asc",
    );
  });
});

describe("свёрнутые группы", () => {
  it("круговой перегон", () => {
    const raw = "okpd:32.50,okpd:41.20";
    expect(serializeCollapsed(parseCollapsed(raw))).toBe(raw);
  });

  it("пусто — пустое множество, а не строка из пустышки", () => {
    expect(parseCollapsed("")).toEqual(new Set());
    expect(parseCollapsed(null)).toEqual(new Set());
    expect(serializeCollapsed(new Set())).toBe("");
  });

  it("повторы схлопываются, порядок устойчив", () => {
    expect(serializeCollapsed(parseCollapsed("b,a,b"))).toBe("a,b");
  });
});

describe("состояние словами", () => {
  it("описывает поле и направление", () => {
    expect(describeSort([{ field: "deadline", dir: "asc" }])).toBe(
      "по сроку подачи · сначала ближайшие",
    );
    expect(describeSort([{ field: "customer", dir: "desc" }])).toBe("по заказчику · Я → А");
  });
});
