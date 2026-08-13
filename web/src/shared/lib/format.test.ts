import { describe, expect, it } from "vitest";
import { compactMoney, dateShort, fileSize, hoursUntil, money, relativeDeadline } from "./format";
import { plural, withPlural } from "./plural";

const NBSP = " ";

describe("деньги", () => {
  it("пишет полную форму с неразрывным пробелом перед ₽", () => {
    expect(money(2450000)).toBe(`2${NBSP}450${NBSP}000,00${NBSP}₽`);
  });

  it("принимает строку — Decimal приходит из API строкой", () => {
    expect(money("2450000.5")).toBe(`2${NBSP}450${NBSP}000,50${NBSP}₽`);
  });

  it("показывает прочерк вместо нуля, когда цены нет", () => {
    expect(money(null)).toBe("—");
    expect(money(undefined)).toBe("—");
  });

  it("сжимает миллионы и миллиарды для строк списка", () => {
    expect(compactMoney(2_450_000)).toBe(`2,5${NBSP}млн${NBSP}₽`);
    expect(compactMoney(1_200_000_000)).toBe(`1,2${NBSP}млрд${NBSP}₽`);
  });

  it("до миллиона не сжимает — точность там важнее ширины", () => {
    expect(compactMoney(999_999)).toBe(`999${NBSP}999,00${NBSP}₽`);
  });
});

describe("множественное число", () => {
  it("берёт правильную форму для 1, 2 и 5", () => {
    expect(plural(1, ["закупка", "закупки", "закупок"])).toBe("закупка");
    expect(plural(2, ["закупка", "закупки", "закупок"])).toBe("закупки");
    expect(plural(5, ["закупка", "закупки", "закупок"])).toBe("закупок");
  });

  it("не путается на 11 и 21 — главная ловушка русского счёта", () => {
    expect(plural(11, ["день", "дня", "дней"])).toBe("дней");
    expect(plural(21, ["день", "дня", "дней"])).toBe("день");
    expect(plural(112, ["документ", "документа", "документов"])).toBe("документов");
  });

  it("склеивает число и форму неразрывным пробелом", () => {
    expect(withPlural(1248, ["закупка", "закупки", "закупок"])).toBe(
      `1${NBSP}248${NBSP}закупок`,
    );
  });
});

describe("даты и сроки", () => {
  const now = new Date("2026-08-08T10:00:00");

  it("форматирует дату по-русски", () => {
    expect(dateShort("2026-08-04T00:00:00")).toBe("04.08.2026");
    expect(dateShort(null)).toBe("—");
  });

  it("считает остаток в календарных днях", () => {
    expect(relativeDeadline(new Date("2026-08-11T17:00:00"), now)).toBe("осталось 3 дня");
    expect(relativeDeadline(new Date("2026-08-09T17:00:00"), now)).toBe("завтра до 17:00");
    expect(relativeDeadline(new Date("2026-08-08T17:00:00"), now)).toBe("сегодня до 17:00");
  });

  it("прошедший срок называет прошедшим, а не отрицательным остатком", () => {
    expect(relativeDeadline(new Date("2026-08-04T17:00:00"), now)).toBe(
      "приём завершён 4 августа",
    );
  });

  it("считает часы до срока — по ним рельс красит узел", () => {
    expect(hoursUntil(new Date("2026-08-09T10:00:00"), now)).toBe(24);
    expect(hoursUntil(null, now)).toBeNull();
  });
});

describe("размер файла", () => {
  it("переходит на КБ и МБ", () => {
    expect(fileSize(512)).toBe(`512${NBSP}Б`);
    expect(fileSize(2048)).toBe(`2,0${NBSP}КБ`);
    expect(fileSize(5 * 1024 * 1024)).toBe(`5,0${NBSP}МБ`);
    expect(fileSize(null)).toBe("—");
  });
});
