import { Check, CircleHelp, X } from "lucide-react";
import { VellumNote } from "@/shared/ui/vellum-note";
import { Quote } from "@/shared/ui/quote";
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
  actions,
}: VerdictNoteProps) {
  const state =
    verdict.confidence === "confirmed"
      ? "match"
      : verdict.confidence === "rejected"
        ? "no"
        : "unknown";
  const hits = verdict.hits ?? [];

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
        {verdict.reason?.trim() || (state === "unknown" ? ru.ai.undeterminedWhy : "")}
      </p>

      {/* Чем решено: правила бесплатны, модель — нет. */}
      <p className="mt-1 text-caption text-text-subtle">
        {verdict.decided_by === "model" ? ru.ai.decidedByModel : ru.ai.decidedByRules}
      </p>

      <Citations hits={hits} />
    </VellumNote>
  );
}

/**
 * §8.5: утверждение без источника не выдаётся за проверенное.
 *
 * Цитата показывается с подсветкой совпадения и обрезается **вокруг** него.
 * Прежде обрезка шла от начала строки, и при разборе прогона это привело к
 * нескольким неверным выводам: на экране был один левый контекст, а искомое
 * слово оставалось за кадром.
 */
function Citations({ hits }: { hits: Evidence[] }) {
  if (hits.length === 0) {
    return <p className="mt-2 text-body-sm text-text-subtle">{ru.ai.noSource}</p>;
  }

  return (
    <ul className="mt-2 flex flex-col gap-1.5">
      {hits.map((hit, index) => (
        <li key={`${hit.term}-${index}`} className="measure">
          <Quote span={hit} />
          {hit.file_name ? (
            <span className="ml-2 text-caption text-text-subtle">
              {hit.file_name}
              {hit.page ? `, стр. ${hit.page}` : ""}
            </span>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
