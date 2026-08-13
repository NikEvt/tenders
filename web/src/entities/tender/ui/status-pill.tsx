import { Pill } from "@/shared/ui/pill";
import { ru } from "@/shared/i18n/ru";
import { tenderStatus, type StatusDates } from "../model/status";

/**
 * Пилюля статуса всегда носит подсказку о происхождении: статус вычислен, а не
 * получен из ЕИС. Честность здесь ничего не стоит, а недоверие потом — дорого.
 */
export function StatusPill({ dates, now }: { dates: StatusDates; now?: Date }) {
  const status = tenderStatus(dates, now);
  return (
    <Pill tone={status.tone} title={ru.tender.statusComputed} dot>
      {status.label}
    </Pill>
  );
}
