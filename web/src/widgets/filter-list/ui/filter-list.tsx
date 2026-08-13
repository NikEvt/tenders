"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, Trash2 } from "lucide-react";
import { Button } from "@/shared/ui/button";
import { Card } from "@/shared/ui/card";
import { Checkbox } from "@/shared/ui/field";
import { EmptyState } from "@/shared/ui/empty-state";
import { ErrorPanel } from "@/shared/ui/error-panel";
import { Mono } from "@/shared/ui/mono";
import { TextSkeleton } from "@/shared/ui/skeleton";
import { useToast } from "@/shared/ui/toast";
import { endpoints } from "@/shared/api/endpoints";
import { qk } from "@/shared/api/query-keys";
import type { Filter, MatchCount } from "@/shared/api/types";
import { ru } from "@/shared/i18n/ru";
import { dateShort } from "@/shared/lib/format";
import { formatCount } from "@/shared/lib/plural";

export function FilterList() {
  const client = useQueryClient();
  const toast = useToast();

  const filters = useQuery<Filter[]>({
    queryKey: qk.filters.all,
    queryFn: ({ signal }) => endpoints.listFilters(signal),
  });

  const invalidate = () => client.invalidateQueries({ queryKey: qk.filters.all });

  const toggle = useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: { in_digest?: boolean; notify?: boolean } }) =>
      endpoints.patchFilter(id, patch),
    onSuccess: invalidate,
    onError: (error: Error) => toast.show({ title: error.message, tone: "signal" }),
  });

  const duplicate = useMutation({
    mutationFn: (id: number) => endpoints.duplicateFilter(id),
    onSuccess: () => {
      void invalidate();
      toast.show({ title: "Копия создана", tone: "moss" });
    },
    onError: (error: Error) => toast.show({ title: error.message, tone: "signal" }),
  });

  const remove = useMutation({
    mutationFn: (id: number) => endpoints.deleteFilter(id),
    onSuccess: invalidate,
    onError: (error: Error) => toast.show({ title: error.message, tone: "signal" }),
  });

  if (filters.isLoading) return <TextSkeleton lines={8} />;
  if (filters.error) {
    return <ErrorPanel error={filters.error} reset={() => void filters.refetch()} />;
  }

  const items = filters.data ?? [];
  if (items.length === 0) {
    return (
      <EmptyState
        title="Фильтров пока нет"
        body="Опишите словами, что ищете, — конструктор соберёт условия и покажет, сколько отсеет каждый этап."
        action={
          <Button asChild variant="primary">
            <Link href="/filters/new">{ru.filters.newFilter}</Link>
          </Button>
        }
      />
    );
  }

  return (
    <ul className="flex flex-col gap-3">
      {items.map((filter) => (
        <li key={filter.filter_id}>
          <Card className="flex flex-col gap-3">
            <div className="flex flex-wrap items-baseline justify-between gap-3">
              <Link
                href={`/filters/${filter.filter_id}`}
                className="text-h3 font-medium text-text hover:text-gos-fg"
              >
                {filter.name}
              </Link>
              <Sparkline counts={filter.match_counts} />
            </div>

            {filter.query ? <p className="measure text-body-sm text-text-muted">{filter.query}</p> : null}

            <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-body-sm text-text-muted">
              <label className="flex cursor-pointer items-center gap-2">
                <Checkbox
                  checked={filter.in_digest}
                  onChange={(event) =>
                    toggle.mutate({
                      id: filter.filter_id,
                      patch: { in_digest: event.target.checked },
                    })
                  }
                />
                {ru.filters.inDigest}
              </label>
              <label className="flex cursor-pointer items-center gap-2">
                <Checkbox
                  checked={filter.notify}
                  onChange={(event) =>
                    toggle.mutate({ id: filter.filter_id, patch: { notify: event.target.checked } })
                  }
                />
                {ru.filters.notify}
              </label>

              <span>
                {ru.filters.lastRun}:{" "}
                {filter.last_run_at ? (
                  <Mono>{dateShort(filter.last_run_at)}</Mono>
                ) : (
                  // Прогона не было — так и пишем, а не рисуем прочерк-пустышку.
                  <span className="text-text-subtle">не запускался</span>
                )}
              </span>

              <div className="ml-auto flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Дублировать"
                  onClick={() => duplicate.mutate(filter.filter_id)}
                >
                  <Copy className="h-4 w-4" strokeWidth={1.5} />
                </Button>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Удалить"
                  onClick={() => {
                    // Вместе с фильтром уходят его вердикты — это стоит подтвердить.
                    if (window.confirm(`Удалить фильтр «${filter.name}» и его вердикты?`)) {
                      remove.mutate(filter.filter_id);
                    }
                  }}
                >
                  <Trash2 className="h-4 w-4" strokeWidth={1.5} />
                </Button>
              </div>
            </div>
          </Card>
        </li>
      ))}
    </ul>
  );
}

/**
 * Совпадения по дням за неделю.
 *
 * Дни без совпадений в ответе отсутствуют — столбца у них нет, а не нулевой:
 * рисовать нулевую засечку значило бы утверждать, что фильтр в этот день
 * отработал и ничего не нашёл, чего мы не знаем.
 */
function Sparkline({ counts }: { counts: MatchCount[] }) {
  const total = counts.reduce((sum, c) => sum + c.count, 0);
  if (total === 0) {
    return <span className="text-body-sm text-text-subtle">{ru.filters.matches7d}: 0</span>;
  }

  const peak = Math.max(...counts.map((c) => c.count));
  return (
    <span className="flex items-end gap-2">
      <span className="flex h-6 items-end gap-0.5" aria-hidden="true">
        {counts.map((c) => (
          <span
            key={c.day}
            className="w-1.5 rounded-t-[2px] bg-gos-fg/70"
            style={{ height: `${Math.max(2, (c.count / peak) * 24)}px` }}
          />
        ))}
      </span>
      <span className="tnum text-body-sm text-text-muted">
        {ru.filters.matches7d}: {formatCount(total)}
      </span>
    </span>
  );
}
