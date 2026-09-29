import type { CriteriaSpec, ResearchResult } from "@/shared/api/types";

/**
 * Признак деградированного режима.
 *
 * Прежняя эвристика сравнивала `keywords` со словами запроса и смотрела на
 * пустой `llm_criteria`. Обоих полей больше нет, а главное — угадывать не
 * нужно: движок отбора сам сообщает, что модель перестала отвечать.
 *
 * `interrupted` ставится, когда прогон остановлен из-за отказа модели;
 * `not_reached` считает закупки, до которых из-за этого не дошли. Второе важно
 * само по себе: «спорных 8, решено 5» без него читается как потеря, хотя это
 * остановка.
 */
export function isDegraded(result: ResearchResult | null | undefined): boolean {
  if (!result) return false;
  if (result.interrupted) return true;
  return (result.funnel?.not_reached ?? 0) > 0;
}

/**
 * Компиляция без модели: критерий собран из слов запроса.
 *
 * Отличается от рабочего тем, что правил по контексту нет вовсе — а именно они
 * отсекают мусор. Такой критерий искать умеет, но всё спорное отправит судье,
 * которого нет. Сказать об этом надо до запуска, а не после.
 */
export function isFallbackCriteria(spec: CriteriaSpec | null | undefined): boolean {
  if (!spec) return false;
  return spec.terms.length > 0 && spec.context_rules.length === 0 && !spec.card_pattern;
}
