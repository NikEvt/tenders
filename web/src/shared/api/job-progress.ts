import { NBSP } from "@/shared/lib/format";
import type { Job } from "./types";

/**
 * Расчёт того, что показывает шкала ожидания.
 *
 * Чистые функции без DOM и без React: правила честности здесь проверяются
 * тестом, а не разглядыванием экрана. Ровно та же причина, по которой
 * раскладка подписей оси вынесена в `ui/chart/label-layout.ts`.
 *
 * Правил четыре, и все они про одно — не показывать числа, которых никто не
 * считал.
 */

/** Доля, с которой оценка остатка перестаёт быть гаданием по двум точкам. */
export const ETA_MIN_SHARE = 0.1;

/** Сколько операция должна идти, прежде чем её темп что-то значит, мс. */
export const ETA_MIN_ELAPSED_MS = 10_000;

export type Progress = {
  /** Доля выполненного в **текущей фазе**, 0…1. `null` — знаменателя нет. */
  share: number | null;
  processed: number;
  /** Объём текущей фазы. `null` — ещё не посчитан. */
  total: number | null;
  phase: string | null;
  /** Сколько идёт вся операция. Это и есть ответ на «чего я жду». */
  elapsedMs: number;
  /** Оценка остатка текущей фазы, мс. `null` — оценивать пока не по чему. */
  remainingMs: number | null;
};

export type ProgressClock = {
  now?: number;
  /**
   * Когда началась текущая фаза. По ней и только по ней считается оценка
   * остатка: `created_at` относится к заданию целиком, и на второй фазе дал бы
   * темп, смешанный с первой.
   */
  phaseStartedAt?: number;
};

/**
 * Что известно о ходе задания.
 *
 * `total = 0` и `total = null` — одно и то же состояние: «объём ещё не
 * считали». Ноль здесь никогда не означает «нисколько»: `start` вызывают до
 * того, как объём работы известен (сборка сводки узнаёт его после
 * кластеризации, обход корпуса — после подсчёта).
 */
export function readProgress(job: Job | undefined, clock: ProgressClock = {}): Progress | null {
  if (!job) return null;

  const now = clock.now ?? Date.now();
  const startedAt = Date.parse(job.created_at);
  const total = job.total && job.total > 0 ? job.total : null;
  const processed = job.processed ?? 0;
  const share = total === null ? null : Math.min(1, Math.max(0, processed / total));

  return {
    share,
    processed,
    total,
    phase: job.phase ?? null,
    elapsedMs: Math.max(0, now - startedAt),
    remainingMs: estimateRemaining(share, Math.max(0, now - (clock.phaseStartedAt ?? startedAt))),
  };
}

/**
 * Оценка остатка — или честное «не знаю».
 *
 * Три отказа, и каждый заработан:
 *
 * 1. **Нет знаменателя — нет оценки.** Никакого «примерно половина».
 * 2. **Слишком рано.** Экстраполяция по двум точкам на первых процентах даёт
 *    «осталось четыре часа», после чего вкладку закрывают.
 * 3. **Считается по текущей фазе.** Темп обхода корпуса не переносится на
 *    работу судьи: это разные операции с разной ценой единицы работы, и
 *    сквозная оценка была бы выдуманным числом. Поэтому сюда приходит время
 *    фазы, а не задания, — его отсчитывает `usePhaseClock`.
 */
export function estimateRemaining(share: number | null, elapsedMs: number): number | null {
  if (share === null || share <= 0) return null;
  if (share < ETA_MIN_SHARE) return null;
  if (elapsedMs < ETA_MIN_ELAPSED_MS) return null;
  if (share >= 1) return 0;
  return Math.round((elapsedMs / share) * (1 - share));
}

/**
 * Длительность словами: «12 с», «1 мин 20 с», «2 ч 5 мин».
 *
 * Без секунд после часа: точность, которой нет, показывать незачем.
 *
 * Число и единица склеены неразрывным пробелом — как деньги и размеры файлов
 * в `lib/format`. Подпись стоит в строке, которая переносится, и «20» на одной
 * строке с «с» на другой читается как опечатка.
 */
export function duration(ms: number): string {
  const seconds = Math.max(0, Math.round(ms / 1000));
  if (seconds < 60) return `${seconds}${NBSP}с`;

  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) {
    const rest = seconds % 60;
    return rest ? `${minutes}${NBSP}мин ${rest}${NBSP}с` : `${minutes}${NBSP}мин`;
  }

  const hours = Math.floor(minutes / 60);
  const restMinutes = minutes % 60;
  return restMinutes ? `${hours}${NBSP}ч ${restMinutes}${NBSP}мин` : `${hours}${NBSP}ч`;
}
