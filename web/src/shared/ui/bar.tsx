import { cn } from "@/shared/lib/cn";
import { formatCount } from "@/shared/lib/plural";

/**
 * Горизонтальный столбец с подписью и числом: воронка фильтра, веса профиля,
 * прогресс до обученного ранжировщика. Один компонент вместо трёх похожих —
 * и вместо графика там, где график был бы украшением.
 */
export function Bar({
  label,
  value,
  max,
  tone = "gos",
  hint,
  onClick,
  className,
}: {
  label: string;
  value: number;
  max: number;
  tone?: "gos" | "oak" | "moss" | "signal" | "neutral";
  hint?: string;
  onClick?: () => void;
  className?: string;
}) {
  const share = max > 0 ? Math.min(1, Math.max(0, value / max)) : 0;
  const fill = {
    gos: "bg-gos-fg",
    oak: "bg-oak-fg",
    moss: "bg-moss-fg",
    signal: "bg-signal-fg",
    neutral: "bg-border-strong",
  }[tone];

  const content = (
    <>
      <span className="w-44 shrink-0 truncate text-body-sm text-text-muted">{label}</span>
      <span className="w-20 shrink-0 text-right font-mono text-mono tnum text-text">
        {formatCount(value)}
      </span>
      <span className="h-2.5 min-w-0 flex-1 overflow-hidden rounded-full bg-hairline">
        <span
          className={cn("block h-full rounded-full transition-[width] duration-(--dur-move)", fill)}
          style={{ width: `${Math.max(share * 100, value > 0 ? 1.5 : 0)}%` }}
        />
      </span>
    </>
  );

  if (onClick) {
    return (
      <button
        type="button"
        onClick={onClick}
        title={hint}
        className={cn(
          "flex w-full items-center gap-3 rounded-[6px] px-1 py-1 text-left hover:bg-surface-sunken",
          className,
        )}
      >
        {content}
      </button>
    );
  }

  return (
    <div className={cn("flex w-full items-center gap-3 px-1 py-1", className)} title={hint}>
      {content}
    </div>
  );
}
