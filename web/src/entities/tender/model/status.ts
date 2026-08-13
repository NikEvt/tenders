import type { PillTone } from "@/shared/ui/pill";
import { ru } from "@/shared/i18n/ru";
import { toDate } from "@/shared/lib/format";

/**
 * Статус закупки вычисляется из дат — ЕИС его не передаёт.
 *
 * Правило повторяет `Tender.status_at` из services/crawler/domain/models.py
 * буква в букву. Если правило меняется на бэкенде, менять надо здесь же —
 * два разных ответа на вопрос «что сейчас с закупкой» хуже, чем один неточный.
 *
 * Возвращает `source: "computed"` осознанно: каждая пилюля носит подсказку
 * о происхождении статуса.
 */
export type StatusCode = "planned" | "collecting" | "bidding" | "finished" | "unknown";

export type TenderStatus = {
  code: StatusCode;
  label: string;
  tone: PillTone;
  source: "computed";
};

const PRESENTATION: Record<StatusCode, { label: string; tone: PillTone }> = {
  planned: { label: ru.status.published, tone: "moss" },
  collecting: { label: ru.status.accepting, tone: "gos" },
  bidding: { label: ru.status.commission, tone: "oak" },
  finished: { label: ru.status.finished, tone: "neutral" },
  unknown: { label: ru.status.unknown, tone: "neutral" },
};

export type StatusDates = {
  publish_date?: string | Date | null;
  end_date?: string | Date | null;
  /** Дата подведения итогов. В текущем каталоге наружу не выведена. */
  summarizing_date?: string | Date | null;
};

export function tenderStatus(dates: StatusDates, now: Date = new Date()): TenderStatus {
  const code = statusCode(dates, now);
  return { code, source: "computed", ...PRESENTATION[code] };
}

function statusCode(dates: StatusDates, now: Date): StatusCode {
  const publish = toDate(dates.publish_date);
  const end = toDate(dates.end_date);
  const summarizing = toDate(dates.summarizing_date);

  if (publish && publish.getTime() > now.getTime()) return "planned";
  if (end && now.getTime() < end.getTime()) return "collecting";
  if (summarizing && startOfDay(now) > startOfDay(summarizing)) return "finished";
  if (end && now.getTime() >= end.getTime()) return "bidding";
  return "unknown";
}

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}
