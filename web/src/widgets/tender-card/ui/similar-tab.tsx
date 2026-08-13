"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { EmptyState } from "@/shared/ui/empty-state";
import { TextSkeleton } from "@/shared/ui/skeleton";
import { ErrorPanel } from "@/shared/ui/error-panel";
import { endpoints } from "@/shared/api/endpoints";
import { STALE } from "@/shared/api/query-keys";
import type { SimilarTenders } from "@/shared/api/types";
import { money, regionName } from "@/shared/lib/format";
import { Mono } from "@/shared/ui/mono";

const LIMIT = 6;

/**
 * Соседи по «карточному» эмбеддингу.
 *
 * Объяснение похожести приходит с сервера и собрано из совпавших полей —
 * ОКПД2, регион, заказчик, порядок цены. Это проверяемое утверждение, а не
 * пересказ модели, поэтому оно показывается как факт, а не на веллуме.
 */
export function SimilarTab({ regNum }: { regNum: string }) {
  const query = useQuery<SimilarTenders>({
    queryKey: ["tenders", regNum, "similar", LIMIT],
    staleTime: STALE.list,
    queryFn: ({ signal }) => endpoints.similarTenders(regNum, LIMIT, signal),
  });

  if (query.isLoading) return <TextSkeleton lines={6} />;
  if (query.error) return <ErrorPanel error={query.error} reset={() => void query.refetch()} />;

  const items = query.data?.items ?? [];
  if (items.length === 0) {
    return (
      <EmptyState
        title="Похожих закупок не нашлось"
        // Пустота здесь законна и объяснима, а не признак поломки.
        body="Вектор закупки считается после обработки документов. Для свежего извещения соседей ещё нет."
      />
    );
  }

  return (
    <ul className="flex flex-col divide-y divide-hairline">
      {items.map(({ tender, similarity, driver }) => (
        <li key={tender.reg_num}>
          <Link
            href={`/tenders/${tender.reg_num}`}
            className="flex flex-col gap-1 py-4 hover:bg-surface-sunken"
          >
            <div className="flex items-baseline justify-between gap-4">
              <span className="text-body font-medium text-text">
                {tender.name ?? tender.reg_num}
              </span>
              <span className="tnum shrink-0 text-body-sm text-text-muted">
                {money(tender.price)}
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-body-sm text-text-muted">
              <Mono>{tender.reg_num}</Mono>
              {tender.region_code ? <span>{regionName(tender.region_code)}</span> : null}
              <span className="tnum">{Math.round(similarity * 100)}%</span>
            </div>
            <p className="text-body-sm text-text-subtle">{driver}</p>
          </Link>
        </li>
      ))}
    </ul>
  );
}
