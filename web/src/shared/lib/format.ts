import { format, formatISO, isValid, parseISO } from "date-fns";
import { ru } from "date-fns/locale";
import { plural, formatCount } from "./plural";

/** Неразрывный пробел. Между числом и единицей — всегда он. */
export const NBSP = " ";
const RUB = "₽";

const moneyFormat = new Intl.NumberFormat("ru-RU", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const roundFormat = new Intl.NumberFormat("ru-RU", {
  maximumFractionDigits: 1,
  minimumFractionDigits: 1,
});

/** 2 450 000,00 ₽ — полная форма для карточки и правой колонки. */
export function money(value: number | string | null | undefined): string {
  const n = toNumber(value);
  if (n === null) return "—";
  return `${moneyFormat.format(n)}${NBSP}${RUB}`;
}

/** Компактная форма — только для строк списка, где важна ширина колонки. */
export function compactMoney(value: number | string | null | undefined): string {
  const n = toNumber(value);
  if (n === null) return "—";
  if (Math.abs(n) >= 1e9) return `${roundFormat.format(n / 1e9)}${NBSP}млрд${NBSP}${RUB}`;
  if (Math.abs(n) >= 1e6) return `${roundFormat.format(n / 1e6)}${NBSP}млн${NBSP}${RUB}`;
  return money(n);
}

export function toNumber(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

export function toDate(value: string | Date | null | undefined): Date | null {
  if (!value) return null;
  const d = typeof value === "string" ? parseISO(value) : value;
  return isValid(d) ? d : null;
}

/** 04.08.2026 */
export function dateShort(value: string | Date | null | undefined): string {
  const d = toDate(value);
  return d ? format(d, "dd.MM.yyyy", { locale: ru }) : "—";
}

/** 4 августа 2026 */
export function dateLong(value: string | Date | null | undefined): string {
  const d = toDate(value);
  return d ? format(d, "d MMMM yyyy", { locale: ru }) : "—";
}

/** четверг, 6 августа */
export function dateWeekday(value: string | Date | null | undefined): string {
  const d = toDate(value);
  return d ? format(d, "EEEE, d MMMM", { locale: ru }) : "—";
}

/** 04.08.2026, 17:00 — время московское, подпись «мск» ставится один раз в шапке. */
export function dateTime(value: string | Date | null | undefined): string {
  const d = toDate(value);
  return d ? format(d, "dd.MM.yyyy, HH:mm", { locale: ru }) : "—";
}

export function timeOnly(value: string | Date | null | undefined): string {
  const d = toDate(value);
  return d ? format(d, "HH:mm", { locale: ru }) : "—";
}

export function isoDate(value: Date): string {
  return formatISO(value, { representation: "date" });
}

const DAY_MS = 86_400_000;

/**
 * «осталось 3 дня» / «сегодня до 17:00» / «приём завершён 4 августа».
 * Считается в днях по календарю, а не по разнице часов: аналитик мыслит датами.
 */
export function relativeDeadline(
  deadline: string | Date | null | undefined,
  now: Date = new Date(),
): string {
  const d = toDate(deadline);
  if (!d) return "срок не указан";

  const startOfDay = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((startOfDay(d) - startOfDay(now)) / DAY_MS);

  if (d.getTime() < now.getTime()) {
    return `приём завершён ${format(d, "d MMMM", { locale: ru })}`;
  }
  if (days === 0) return `сегодня до ${format(d, "HH:mm", { locale: ru })}`;
  if (days === 1) return `завтра до ${format(d, "HH:mm", { locale: ru })}`;
  return `осталось ${days} ${plural(days, ["день", "дня", "дней"])}`;
}

/** Часы до срока — по ним рельс решает, красить ли узел в oak. */
export function hoursUntil(
  deadline: string | Date | null | undefined,
  now: Date = new Date(),
): number | null {
  const d = toDate(deadline);
  if (!d) return null;
  return (d.getTime() - now.getTime()) / 3_600_000;
}

export function fileSize(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return "—";
  if (bytes < 1024) return `${bytes}${NBSP}Б`;
  if (bytes < 1024 * 1024) return `${roundFormat.format(bytes / 1024)}${NBSP}КБ`;
  return `${roundFormat.format(bytes / (1024 * 1024))}${NBSP}МБ`;
}

export function percent(value: number): string {
  return `${Math.round(value * 100)}${NBSP}%`;
}

/** Регион по коду ОКТМО/субъекта — коды приходят из ЕИС как строки. */
export function regionName(code: string | null | undefined): string {
  if (!code) return "—";
  return REGIONS[code] ?? `Регион ${code}`;
}

export { formatCount };

/** Не полный справочник: только субъекты, которые реально настраивают в EIS_REGIONS. */
export const REGIONS: Record<string, string> = {
  "77": "Москва",
  "78": "Санкт-Петербург",
  "47": "Ленинградская область",
  "50": "Московская область",
  "23": "Краснодарский край",
  "66": "Свердловская область",
  "16": "Республика Татарстан",
  "52": "Нижегородская область",
  "54": "Новосибирская область",
  "24": "Красноярский край",
  "63": "Самарская область",
  "36": "Воронежская область",
  "61": "Ростовская область",
  "02": "Республика Башкортостан",
  "74": "Челябинская область",
  "59": "Пермский край",
};
