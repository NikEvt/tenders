"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Card } from "@/shared/ui/card";
import { TextSkeleton } from "@/shared/ui/skeleton";
import { DefinitionList } from "@/shared/ui/definition-list";
import { useToast } from "@/shared/ui/toast";
import { endpoints } from "@/shared/api/endpoints";
import type { LoadLevel as LoadLevelData } from "@/shared/api/types";
import { ru } from "@/shared/i18n/ru";
import { cn } from "@/shared/lib/cn";

const LEVELS: { value: 1 | 2 | 3; label: string; note: string }[] = [
  { value: 1, label: ru.load.background, note: ru.load.backgroundNote },
  { value: 2, label: ru.load.balanced, note: ru.load.balancedNote },
  { value: 3, label: ru.load.full, note: ru.load.fullNote },
];

/**
 * Уровень нагрузки на машину.
 *
 * Единственный настоящий переключатель на экране настроек: всё остальное здесь
 * живёт в `.env` и показывается только для чтения. Поэтому он и подан иначе —
 * не строкой в таблице, а выбором из трёх состояний.
 *
 * Подписи по смыслу, а не по номеру: «фоновый» объясняет себя, «уровень 1» —
 * нет. Числа под ними — следствие выбора, и они посчитаны **для машины шлюза**:
 * у воркера с другим лимитом памяти пул может отличаться, и выдавать эти числа
 * за общие было бы неправдой.
 */
export function LoadLevelControl() {
  const client = useQueryClient();
  const toast = useToast();

  const level = useQuery<LoadLevelData>({
    queryKey: ["system", "load-level"],
    queryFn: ({ signal }) => endpoints.loadLevel(signal),
  });

  const change = useMutation({
    mutationFn: (value: 1 | 2 | 3) => endpoints.setLoadLevel(value),
    onSuccess: (result) => {
      client.setQueryData(["system", "load-level"], result);
      toast.show({ title: ru.load.changed, body: ru.load.appliesLater, tone: "moss" });
    },
  });

  if (level.isLoading) return <TextSkeleton lines={5} />;
  const current = level.data;

  return (
    <Card className="flex flex-col gap-4">
      <div>
        <h2 className="text-h3">{ru.load.title}</h2>
        <p className="mt-1 text-body-sm text-text-muted">{ru.load.hint}</p>
      </div>

      <fieldset className="flex flex-col gap-2">
        <legend className="sr-only">{ru.load.title}</legend>
        {LEVELS.map((option) => {
          const selected = current?.level === option.value;
          return (
            <label
              key={option.value}
              className={cn(
                "flex cursor-pointer items-start gap-3 rounded-[6px] border p-3",
                selected ? "border-gos-tint surface-gos-tint" : "border-hairline",
              )}
            >
              <input
                type="radio"
                name="load-level"
                className="mt-1"
                checked={selected}
                disabled={change.isPending}
                onChange={() => change.mutate(option.value)}
              />
              <span>
                <span className="block text-body font-medium">{option.label}</span>
                <span className="block text-body-sm text-text-muted">{option.note}</span>
              </span>
            </label>
          );
        })}
      </fieldset>

      {current ? (
        <>
          <DefinitionList
            items={[
              { label: ru.load.extractionWorkers, value: String(current.extraction_workers) },
              { label: ru.load.docsPrefetch, value: String(current.docs_prefetch) },
              { label: ru.load.llmConcurrency, value: String(current.llm_concurrency) },
              { label: ru.load.crawlWorkers, value: String(current.crawl_workers) },
              { label: ru.load.eisRps, value: String(current.eis_rps) },
            ]}
          />
          <p className="text-caption text-text-subtle">{ru.load.gatewayNumbers}</p>
          {/* Переключение асинхронное: воркеры сверяются с настройкой сами.
              Сказать об этом надо здесь, иначе «почему не применилось» станет
              вопросом к системе, а не ожидаемым поведением. */}
          <p className="text-caption text-text-subtle">{ru.load.appliesLater}</p>
        </>
      ) : null}
    </Card>
  );
}
