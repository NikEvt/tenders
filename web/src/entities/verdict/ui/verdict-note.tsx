import Link from "next/link";
import { Check, CircleHelp, ExternalLink, X } from "lucide-react";
import { VellumNote } from "@/shared/ui/vellum-note";
import { ru } from "@/shared/i18n/ru";
import { percent } from "@/shared/lib/format";
import { cn } from "@/shared/lib/cn";
import type { Evidence, Verdict } from "@/shared/api/types";

export type VerdictNoteProps = {
  verdict: Verdict;
  model: string;
  /** Текст критерия, если он известен из сохранённого фильтра. */
  criterion?: string;
  reasoningEffort?: string;
  /** Куда ведёт цитата. Возвращает null, если фрагмент не адресуем. */
  citationHref?: (evidence: Evidence) => string | null;
  actions?: React.ReactNode;
};

/**
 * Вердикт судьи. Три состояния равноправны: «не удалось определить» — такой же
 * законный ответ, как и два других, и он всегда объяснён. Молчаливого
 * отсутствия вердикта не бывает.
 */
export function VerdictNote({
  verdict,
  model,
  criterion,
  reasoningEffort,
  citationHref,
  actions,
}: VerdictNoteProps) {
  const state = verdict.match === true ? "match" : verdict.match === false ? "no" : "unknown";
  const evidence = verdict.evidence ?? [];

  return (
    <VellumNote
      eyebrow={ru.ai.verdictEyebrow}
      source={model}
      extra={reasoningEffort ? `${ru.ai.reasoningEffort}: ${reasoningEffort}` : undefined}
      actions={actions}
    >
      {criterion ? (
        <p className="text-body-sm text-text-muted">
          {ru.ai.criterion}: «{criterion}»
        </p>
      ) : null}

      <p
        className={cn(
          "mt-1 flex items-center gap-1.5 font-medium",
          state === "match" && "text-moss-fg",
          state === "no" && "text-signal-fg",
          state === "unknown" && "text-text-subtle",
        )}
      >
        {state === "match" ? (
          <Check className="h-4 w-4" strokeWidth={2} aria-hidden="true" />
        ) : state === "no" ? (
          <X className="h-4 w-4" strokeWidth={2} aria-hidden="true" />
        ) : (
          <CircleHelp className="h-4 w-4" strokeWidth={1.5} aria-hidden="true" />
        )}
        {state === "match" ? ru.ai.match : state === "no" ? ru.ai.noMatch : ru.ai.undetermined}
        {verdict.score !== null && state !== "unknown" ? (
          <span className="font-normal text-text-muted">
            — {ru.ai.confidence} {percent(verdict.score)}
          </span>
        ) : null}
      </p>

      <p className="mt-1.5 measure text-body">
        {verdict.reasoning?.trim() || (state === "unknown" ? ru.ai.undeterminedWhy : "")}
      </p>

      <Citations evidence={evidence} citationHref={citationHref} />
    </VellumNote>
  );
}

/**
 * §8.5: утверждение без разрешимой ссылки не выбрасывается и не выдаётся за
 * проверенное — оно помечается «источник не указан».
 */
function Citations({
  evidence,
  citationHref,
}: {
  evidence: Evidence[];
  citationHref?: (evidence: Evidence) => string | null;
}) {
  if (evidence.length === 0) {
    return <p className="mt-2 text-body-sm text-text-subtle">{ru.ai.noSource}</p>;
  }

  return (
    <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
      {evidence.map((item, index) => {
        const href = citationHref?.(item) ?? null;
        return (
          <li key={`${item.document_id}-${item.chunk_id}-${index}`}>
            {href ? (
              <Link
                href={href}
                className="inline-flex items-center gap-1 text-body-sm font-medium text-gos-fg hover:underline"
              >
                {ru.ai.showSource}
                <ExternalLink className="h-3.5 w-3.5" strokeWidth={1.5} aria-hidden="true" />
              </Link>
            ) : (
              <span className="text-body-sm text-text-subtle">{ru.ai.noSource}</span>
            )}
          </li>
        );
      })}
    </ul>
  );
}
