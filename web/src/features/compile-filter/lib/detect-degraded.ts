import type { FilterSpec } from "@/shared/api/types";

/**
 * Признак деградированного режима llm-service.
 *
 * Пустой `llm_criteria` сам по себе — норма: на простом запросе модель решает,
 * что структурных полей достаточно, и дорогой судья не запускается. Но пустой
 * критерий вместе с `keywords`, которые выглядят как разбитый на слова запрос, —
 * это уже фолбэк без модели. README называет ровно этот признак.
 */
export function isDegraded(query: string, spec: FilterSpec | null | undefined): boolean {
  if (!spec) return false;
  if (spec.llm_criteria?.trim()) return false;

  const tokens = query
    .toLowerCase()
    .split(/\s+/)
    .filter((token) => token.length > 2);
  const keywords = (spec.keywords ?? []).map((k) => k.toLowerCase());
  if (tokens.length < 3) return false;

  const overlap = tokens.filter((token) => keywords.includes(token)).length;
  return overlap / tokens.length > 0.8;
}
