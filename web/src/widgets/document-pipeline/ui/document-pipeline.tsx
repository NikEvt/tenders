"use client";

import { useQuery } from "@tanstack/react-query";
import { Card } from "@/shared/ui/card";
import { TextSkeleton } from "@/shared/ui/skeleton";
import { endpoints } from "@/shared/api/endpoints";
import { STALE } from "@/shared/api/query-keys";
import type { DocumentPipeline } from "@/shared/api/types";
import { formatCount } from "@/shared/lib/plural";

const LABELS: Record<string, string> = {
  downloaded: "Скачано",
  extracted: "Извлечён текст",
  ocr: "Через OCR",
  chunked: "Нарезано на фрагменты",
  embedded: "Векторизовано",
  failed: "Не удалось",
  skipped: "Пропущено",
};

/**
 * Воронка обработки документов.
 *
 * Этапы идут в порядке конвейера — порядок и есть информация: место, где
 * число резко падает, и указывает, что чинить.
 */
export function DocumentPipelineFunnel() {
  const pipeline = useQuery<DocumentPipeline>({
    queryKey: ["monitoring", "documents"],
    queryFn: ({ signal }) => endpoints.documentPipeline(signal),
    staleTime: STALE.health,
  });

  if (pipeline.isLoading) return <TextSkeleton lines={6} />;

  const funnel = pipeline.data?.funnel ?? [];
  const failures = pipeline.data?.failures ?? [];
  const peak = Math.max(...funnel.map((s) => s.count), 1);

  return (
    <div className="flex flex-col gap-6">
      <Card className="flex flex-col gap-3">
        <ol className="flex flex-col gap-2">
          {funnel.map((stage, index) => (
            <li key={stage.stage} className="flex items-center gap-3">
              <span className="tnum w-6 text-caption text-text-subtle">{index + 1}</span>
              <span className="w-52 shrink-0 text-body-sm text-text-muted">
                {LABELS[stage.stage] ?? stage.stage}
              </span>
              <span className="h-4 flex-1 overflow-hidden rounded-[2px] bg-hairline">
                <span
                  className="block h-full bg-gos-fg/70"
                  style={{ width: `${(stage.count / peak) * 100}%` }}
                />
              </span>
              <span className="tnum w-20 text-right text-body-sm text-text">
                {formatCount(stage.count)}
              </span>
            </li>
          ))}
        </ol>
      </Card>

      {failures.length ? (
        <Card className="flex flex-col gap-2">
          <h3 className="text-h3">Отказы</h3>
          {/* По этапам, а не одним числом: «не скачалось» и «не распозналось»
              чинятся по-разному. */}
          <dl className="flex flex-col gap-1 text-body-sm">
            {failures.map((failure) => (
              <div key={failure.stage} className="flex justify-between gap-3">
                <dt className="text-text-muted">{LABELS[failure.stage] ?? failure.stage}</dt>
                <dd className="tnum text-signal-fg">{formatCount(failure.count)}</dd>
              </div>
            ))}
          </dl>
        </Card>
      ) : null}
    </div>
  );
}
