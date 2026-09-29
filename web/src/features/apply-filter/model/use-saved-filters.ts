"use client";

import { useQuery } from "@tanstack/react-query";

import { endpoints } from "@/shared/api/endpoints";
import { qk, STALE } from "@/shared/api/query-keys";
import type { Filter } from "@/shared/api/types";

/**
 * Сохранённые фильтры для меню каталога.
 *
 * Тот же ключ, что и на странице фильтров: правка имени там обновляет подпись
 * здесь без отдельной инвалидации.
 */
export function useSavedFilters({ enabled = true }: { enabled?: boolean } = {}) {
  return useQuery<Filter[]>({
    queryKey: qk.filters.all,
    staleTime: STALE.list,
    enabled,
    queryFn: ({ signal }) => endpoints.listFilters(signal),
  });
}

/** Имя фильтра по идентификатору — пока список едет, показывать нечего. */
export function filterName(filters: Filter[] | undefined, id: number | null): string | null {
  if (id === null) return null;
  return filters?.find((f) => f.filter_id === id)?.name ?? null;
}
