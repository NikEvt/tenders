import { cn } from "@/shared/lib/cn";

/** Форма скелетона повторяет геометрию содержимого — иначе макет прыгнёт. */
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton rounded-[6px]", className)} aria-hidden="true" />;
}

/** Строка каталога: 72px, три уровня текста. */
export function RowSkeleton() {
  return (
    <div className="flex h-[72px] flex-col justify-center gap-1.5 border-b border-hairline px-4">
      <div className="flex items-center gap-3">
        <Skeleton className="h-5 w-24 rounded-full" />
        <Skeleton className="h-4 w-56" />
        <Skeleton className="ml-auto h-4 w-28" />
      </div>
      <Skeleton className="h-4 w-2/3" />
      <div className="flex items-center gap-3">
        <Skeleton className="h-3 w-72" />
        <Skeleton className="ml-auto h-3 w-[120px]" />
      </div>
    </div>
  );
}

export function ListSkeleton({ rows = 8 }: { rows?: number }) {
  return (
    <div aria-hidden="true">
      {Array.from({ length: rows }, (_, i) => (
        <RowSkeleton key={i} />
      ))}
    </div>
  );
}

export function TextSkeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div className="flex flex-col gap-2" aria-hidden="true">
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} className={cn("h-4", i === lines - 1 ? "w-2/3" : "w-full")} />
      ))}
    </div>
  );
}
