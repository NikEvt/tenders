"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/shared/ui/button";
import { Banner } from "@/shared/ui/banner";
import { Card } from "@/shared/ui/card";
import { DefinitionList } from "@/shared/ui/definition-list";
import { SectionHeading } from "@/shared/ui/section";
import { TextSkeleton } from "@/shared/ui/skeleton";
import { useToast } from "@/shared/ui/toast";
import { endpoints } from "@/shared/api/endpoints";
import { LoadLevelControl } from "./load-level";
import { STALE } from "@/shared/api/query-keys";
import type { Settings } from "@/shared/api/types";
import { dateLong } from "@/shared/lib/format";

/**
 * Действующие настройки — только для чтения.
 *
 * Значения приходят из окружения и применяются при старте процесса, поэтому
 * править их отсюда нельзя: кнопка «сохранить» создавала бы впечатление, что
 * изменение вступило в силу. Единственное действие — отметить, что токен ЕИС
 * перевыпущен.
 */
export function SettingsView() {
  const client = useQueryClient();
  const toast = useToast();

  const settings = useQuery<Settings>({
    queryKey: ["settings"],
    queryFn: ({ signal }) => endpoints.settings(signal),
    staleTime: STALE.health,
  });

  const confirm = useMutation({
    mutationFn: () => endpoints.confirmTokenRotation(),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["settings"] });
      toast.show({ title: "Отмечено: токен перевыпущен", tone: "moss" });
    },
    onError: (error: Error) => toast.show({ title: error.message, tone: "signal" }),
  });

  if (settings.isLoading) return <TextSkeleton lines={12} />;
  const data = settings.data;
  if (!data) return null;

  const token = data.eis_token as { masked: string; rotated_at: string | null };
  const llm = data.llm as Record<string, string>;
  const crawler = data.crawler as { regions: string[]; document_types: string[]; interval_minutes: number };
  const embedding = data.embedding as Record<string, string | number>;

  return (
    <div className="flex flex-col gap-6">
      <LoadLevelControl />

      {data.restart_required_keys.length ? (
        <Banner
          tone="oak"
          title="Часть значений читается только при старте."
          body={`Правка ${data.restart_required_keys.join(", ")} в .env подействует после перезапуска сервиса, а не сразу.`}
        />
      ) : null}

      <section className="flex flex-col gap-3">
        <SectionHeading title="Модель" />
        <Card>
          <DefinitionList
            items={[
              { label: "Адрес", value: llm.base_url, mono: true },
              { label: "Модель", value: llm.model, mono: true },
              { label: "Авторизация", value: llm.auth_scheme },
              { label: "Рассуждения", value: llm.reasoning_effort },
              { label: "Рассуждения судьи", value: llm.judge_reasoning_effort },
            ]}
          />
        </Card>
      </section>

      <section className="flex flex-col gap-3">
        <SectionHeading title="Эмбеддинги" />
        <Card>
          <DefinitionList
            items={[
              { label: "Модель", value: String(embedding.model), mono: true },
              { label: "Размерность", value: String(embedding.dim), mono: true },
              { label: "Устройство", value: String(embedding.device) },
            ]}
          />
        </Card>
      </section>

      <section className="flex flex-col gap-3">
        <SectionHeading title="Выгрузка из ЕИС" />
        <Card className="flex flex-col gap-4">
          <DefinitionList
            items={[
              { label: "Регионы", value: crawler.regions.join(", ") || "—" },
              { label: "Типы документов", value: crawler.document_types.join(", ") || "—" },
              { label: "Интервал", value: `${crawler.interval_minutes} мин` },
              { label: "Токен", value: token.masked, mono: true },
              {
                label: "Перевыпущен",
                value: token.rotated_at ? dateLong(token.rotated_at) : "не отмечалось",
              },
            ]}
          />
          <div className="flex items-center gap-3">
            <Button variant="secondary" loading={confirm.isPending} onClick={() => confirm.mutate()}>
              Отметить, что токен перевыпущен
            </Button>
            {/* Сам токен задаётся в окружении: интерфейс его не меняет и не видит. */}
            <p className="text-body-sm text-text-subtle">
              Значение задаётся переменной EIS_TOKEN; здесь сохраняется только дата.
            </p>
          </div>
        </Card>
      </section>

      <section className="flex flex-col gap-3">
        <SectionHeading title="Сертификаты" />
        <Card>
          <DefinitionList
            items={data.certificates.map((cert) => ({
              label: cert.subject,
              value: cert.not_after ? `действует до ${cert.not_after}` : "срок неизвестен",
            }))}
          />
        </Card>
      </section>
    </div>
  );
}
