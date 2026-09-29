import { describe, expect, it } from "vitest";

import { activeConditions } from "./active-conditions";
import type { CatalogParams } from "./use-catalog-params";

const EMPTY = {
  q: "",
  region: [],
  okpd2: "",
  customer_inn: "",
  price_min: null,
  price_max: null,
  since: "",
  until: "",
  only_active: false,
  deadline_changed: false,
  has_text: false,
  filter_id: null,
  filter_verdict: "confirmed",
  sort: "",
  group: "",
  collapsed: "",
  page: 0,
  preview: "",
} as unknown as CatalogParams;

describe("чип сохранённого фильтра", () => {
  it("показывает имя фильтра, когда оно известно", () => {
    const conditions = activeConditions(
      { ...EMPTY, filter_id: 7 },
      { filterName: "Поставка газа" },
    );

    expect(conditions.map((c) => c.label)).toContain("Фильтр: Поставка газа");
  });

  it("до приезда списка показывает номер, а не пустоту", () => {
    const conditions = activeConditions({ ...EMPTY, filter_id: 7 });

    expect(conditions.map((c) => c.label)).toContain("Фильтр: #7");
  });

  it("снимается вместе с вердиктом", () => {
    const [chip] = activeConditions({ ...EMPTY, filter_id: 7 });

    expect(chip!.clear).toMatchObject({ filter_id: null, filter_verdict: "confirmed" });
  });

  it("вердикт по умолчанию отдельным чипом не показывается", () => {
    const conditions = activeConditions({ ...EMPTY, filter_id: 7 });

    expect(conditions.map((c) => c.id)).not.toContain("filter_verdict");
  });

  it("отклонённые называются словом, а не кодом", () => {
    const conditions = activeConditions({
      ...EMPTY,
      filter_id: 7,
      filter_verdict: "rejected",
    } as unknown as CatalogParams);

    expect(conditions.map((c) => c.label)).toContain("Вердикт: отклонённые");
  });

  it("без фильтра вердикт ничего не значит и чипа не даёт", () => {
    const conditions = activeConditions({
      ...EMPTY,
      filter_verdict: "rejected",
    } as unknown as CatalogParams);

    expect(conditions).toEqual([]);
  });
});
