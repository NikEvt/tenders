import { cn } from "@/shared/lib/cn";

/**
 * Шкала ожидания.
 *
 * Два состояния, и различать их обязательно.
 *
 * **Определённая** — знаменатель известен, ширина заливки что-то значит.
 * **Неопределённая** — знаменатель ещё не посчитан (`value` не задан). Тогда
 * по дорожке идёт бегущая заливка, а процента нет вовсе: показать «0 %» там,
 * где считать нечего, значит выдумать число.
 *
 * `label` — не украшение, а текстовая версия шкалы (DESIGN §7: цвет и длина
 * никогда не единственные носители смысла). Она же уходит в `aria-valuetext`,
 * поэтому пишется словами — «обработано 142 из 380», а не «37 %».
 */
export function Progress({
  value,
  label,
  tone = "gos",
  className,
}: {
  /** Доля выполненного, 0…1. Не задана — шкала неопределённая. */
  value?: number | null;
  label: string;
  tone?: "gos" | "moss" | "oak";
  className?: string;
}) {
  const fill = { gos: "bg-gos-fg", moss: "bg-moss-fg", oak: "bg-oak-fg" }[tone];
  const known = value !== null && value !== undefined;
  const share = known ? Math.min(1, Math.max(0, value)) : null;

  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuetext={label}
      {...(share === null
        ? {}
        : { "aria-valuemin": 0, "aria-valuemax": 100, "aria-valuenow": Math.round(share * 100) })}
      className={cn(
        "h-1 w-full overflow-hidden rounded-full bg-hairline",
        // Неопределённая шкала обрезает бегунок по своей ширине.
        share === null && "relative",
        className,
      )}
    >
      {share === null ? (
        <span className={cn("progress-sweep block h-full w-[30%] rounded-full", fill)} />
      ) : (
        <span
          className={cn("block h-full rounded-full transition-[width] duration-(--dur-move)", fill)}
          // Нулевая доля рисуется нулевой шириной: намёк на «чуть-чуть уже
          // сделано» был бы враньём в единственном месте, где оно заметно.
          style={{ width: `${share * 100}%` }}
        />
      )}
    </div>
  );
}
