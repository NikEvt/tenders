import { describe, expect, it } from "vitest";
import type { Tender } from "@/shared/api/types";
import { tendersToCsv } from "./export-csv";

const tender: Tender = {
  tender_id: 1,
  reg_num: "0372200012345000123",
  name: 'Поставка "расходников"',
  description: null,
  // Decimal приходит из FastAPI строкой — фикстура повторяет это буквально.
  price: "2450000.00",
  currency: "RUB",
  customer_name: "ГБУЗ «Городская больница №4»",
  customer_inn: "7801234567",
  okpd2_code: "32.50.50",
  okpd2_name: null,
  region_code: "78",
  publish_date: "2026-08-04T00:00:00",
  start_date: null,
  end_date: "2026-08-14T17:00:00",
  prev_end_date: null,
  deadline_changed: false,
  status: null,
  documents_status: "extracted",
  document_count: 7,
};

describe("экспорт в CSV", () => {
  const csv = tendersToCsv([tender]);

  it("начинается с BOM — иначе Excel портит кириллицу", () => {
    expect(csv.startsWith("﻿")).toBe(true);
  });

  it("разделяет точкой с запятой: русская локаль Excel ждёт именно её", () => {
    expect(csv.split("\r\n")[0]).toContain('";"');
  });

  it("экранирует кавычки внутри названия", () => {
    expect(csv).toContain('"Поставка ""расходников"""');
  });

  it("кладёт цену как есть, без пробелов и знака валюты", () => {
    expect(csv).toContain('"2450000.00"');
  });
});
