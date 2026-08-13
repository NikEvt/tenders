import { Skeleton, ListSkeleton } from "@/shared/ui/skeleton";

/** Скелетон повторяет геометрию каталога: строка поиска, чипы, строки по 72px. */
export default function Loading() {
  return (
    <div className="flex flex-col gap-6">
      <Skeleton className="h-8 w-56" />
      <Skeleton className="h-11 w-full" />
      <div className="flex gap-6">
        <div className="hidden w-70 flex-col gap-6 2xl:flex">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-32 w-full" />
          ))}
        </div>
        <div className="min-w-0 flex-1 overflow-hidden rounded-[10px] border border-hairline">
          <ListSkeleton rows={10} />
        </div>
      </div>
    </div>
  );
}
