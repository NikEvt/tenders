import { describe, expect, it } from "vitest";
import type { GroupBucket, Tender } from "@/shared/api/types";
import { estimateSize, flattenGroups, groupValue, HEADER_HEIGHT, GROUP_ROW_HEIGHT } from "./flatten-groups";

const tender = (regNum: string, okpd: string | null, customer: string | null = null): Tender =>
  ({
    reg_num: regNum,
    okpd2_code: okpd,
    customer_name: customer,
    region_code: null,
  }) as Tender;

const bucket = (key: string, count: number, total: number | null, label = key): GroupBucket =>
  ({ key, label, count, total_price: total }) as unknown as GroupBucket;

describe("плоский список групп", () => {
  const items = [
    tender("A", "20.11"),
    tender("B", "20.11"),
    tender("C", "31.01"),
  ];
  const buckets = [bucket("20.11", 12, 500), bucket("31.01", 3, 90)];

  it("шапка встаёт на смене ключа, порядок строк не трогается", () => {
    const flat = flattenGroups(items, "okpd", buckets, new Set());

    expect(flat.map((item) => (item.kind === "header" ? `# ${item.groupKey}` : item.id))).toEqual([
      "# 20.11",
      "A",
      "B",
      "# 31.01",
      "C",
    ]);
  });

  it("счётчик и сумма берутся из оглавления, а не из загруженной страницы", () => {
    // Загружено две строки, в группе двенадцать: шапка обязана сказать 12.
    const [header] = flattenGroups(items, "okpd", buckets, new Set());
    expect(header).toMatchObject({ kind: "header", count: 12, totalPrice: 500 });
  });

  it("свёрнутая группа оставляет только шапку", () => {
    const flat = flattenGroups(items, "okpd", buckets, new Set(["okpd:20.11"]));

    expect(flat.map((item) => item.id)).toEqual(["okpd:20.11", "okpd:31.01", "C"]);
    expect(flat[0]).toMatchObject({ collapsed: true });
  });

  it("ключи строк устойчивы и не повторяются", () => {
    const flat = flattenGroups(items, "okpd", buckets, new Set());
    const ids = flat.map((item) => item.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("закупка без категории получает свою группу, а не исчезает", () => {
    const flat = flattenGroups([tender("D", null)], "okpd", [bucket("", 1, 0)], new Set());

    expect(flat).toHaveLength(2);
    expect(flat[0]).toMatchObject({ kind: "header", groupKey: "" });
    expect(flat[1]).toMatchObject({ kind: "row", id: "D" });
  });

  it("одна и та же категория, разорванная порядком, даёт две шапки", () => {
    // Так быть не должно: ключ группы идёт первым в сортировке. Но если
    // сервер вернул иначе, строки обязаны остаться на экране все.
    const broken = [tender("A", "20.11"), tender("C", "31.01"), tender("B", "20.11")];
    const flat = flattenGroups(broken, "okpd", buckets, new Set());

    expect(flat.filter((item) => item.kind === "row").map((item) => item.id)).toEqual([
      "A",
      "C",
      "B",
    ]);
  });

  it("оглавление ещё не пришло — шапка есть, числа пустые", () => {
    const [header] = flattenGroups(items, "okpd", [], new Set());
    expect(header).toMatchObject({ count: 0, totalPrice: null });
  });

  it("высота по индексу различает шапку и строку", () => {
    const flat = flattenGroups(items, "okpd", buckets, new Set());

    expect(estimateSize(flat, 0)).toBe(HEADER_HEIGHT);
    expect(estimateSize(flat, 1)).toBe(GROUP_ROW_HEIGHT);
    expect(flat.map((_, index) => estimateSize(flat, index))).toEqual([
      HEADER_HEIGHT,
      GROUP_ROW_HEIGHT,
      GROUP_ROW_HEIGHT,
      HEADER_HEIGHT,
      GROUP_ROW_HEIGHT,
    ]);
  });

  it("значение ключа берётся по полю группировки", () => {
    const row = tender("A", "20.11", "ГКУ Больница");
    expect(groupValue(row, "okpd")).toBe("20.11");
    expect(groupValue(row, "customer")).toBe("ГКУ Больница");
    expect(groupValue(row, "region")).toBe("");
  });
});
