import { cn } from "@/shared/lib/cn";

/**
 * Спиннер живёт только внутри кнопки. Загрузка экрана показывается скелетоном
 * той же геометрии, что и содержимое (§6.2), иначе макет прыгает.
 */
export function Spinner({ className }: { className?: string }) {
  return (
    <svg
      className={cn("h-3.5 w-3.5 animate-spin shrink-0", className)}
      viewBox="0 0 14 14"
      fill="none"
      aria-hidden="true"
    >
      <circle cx="7" cy="7" r="5.5" stroke="currentColor" strokeOpacity="0.25" strokeWidth="1.5" />
      <path
        d="M12.5 7a5.5 5.5 0 0 0-5.5-5.5"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}
