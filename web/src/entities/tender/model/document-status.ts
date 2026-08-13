import type { PillTone } from "@/shared/ui/pill";
import { ru } from "@/shared/i18n/ru";

/** Состояние распознавания документа — приходит из docs-worker как строка. */
export function documentStatus(raw: string | null | undefined): {
  label: string;
  tone: PillTone;
} {
  switch (raw) {
    case "extracted":
    case "done":
      return { label: ru.documents.extracted, tone: "moss" };
    case "pending":
    case "queued":
    case "in_progress":
      return { label: ru.documents.pending, tone: "gos" };
    case "failed":
    case "error":
      return { label: ru.documents.failed, tone: "signal" };
    default:
      return { label: ru.documents.notExtracted, tone: "neutral" };
  }
}
