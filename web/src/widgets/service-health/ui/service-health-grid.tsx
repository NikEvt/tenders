"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Card } from "@/shared/ui/card";
import { Mono } from "@/shared/ui/mono";
import { Pill } from "@/shared/ui/pill";
import { SectionHeading } from "@/shared/ui/section";
import { Button } from "@/shared/ui/button";
import { Table, TBody, TD, TH, THead, TR } from "@/shared/ui/table";
import { TextSkeleton } from "@/shared/ui/skeleton";
import { useToast } from "@/shared/ui/toast";
import { ru } from "@/shared/i18n/ru";
import { endpoints } from "@/shared/api/endpoints";
import { STALE } from "@/shared/api/query-keys";
import type { Queues, ServiceHealth, ServicesHealth } from "@/shared/api/types";
import { formatCount } from "@/shared/lib/plural";

/**
 * Состояние сервисов и очередей.
 *
 * Всё собирает шлюз одним ответом: браузеру нельзя ходить на шесть портов —
 * это и CORS, и сеть, и учётные данные брокера. Сервис, который не ответил,
 * приходит со статусом `down` — это факт о нём, а не ошибка страницы.
 */
export function ServiceHealthGrid() {
  const health = useQuery<ServicesHealth>({
    queryKey: ["monitoring", "health"],
    queryFn: ({ signal }) => endpoints.servicesHealth(signal),
    staleTime: STALE.health,
    refetchInterval: STALE.health,
  });

  return (
    <div className="flex flex-col gap-6">
      <section className="flex flex-col gap-3">
        <SectionHeading title="Сервисы" />
        {health.isLoading ? (
          <TextSkeleton lines={6} />
        ) : (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {(health.data?.services ?? []).map((service) => (
              <ServiceCard key={service.name} service={service} />
            ))}
          </div>
        )}
      </section>

      <QueuesSection />
    </div>
  );
}

const TONE = { ok: "moss", degraded: "oak", down: "signal" } as const;
const LABEL = {
  ok: ru.monitoring.statusOk,
  degraded: "медленно",
  down: ru.monitoring.statusDown,
} as const;

function ServiceCard({ service }: { service: ServiceHealth }) {
  const status = (service.status as keyof typeof TONE) ?? "down";
  const facts = Object.entries(service.facts ?? {});

  return (
    <Card className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-mono text-body font-medium text-text">{service.name}</h3>
        <Pill tone={TONE[status]} dot>
          {LABEL[status]}
        </Pill>
      </div>

      <div className="flex items-center gap-3 text-body-sm text-text-muted">
        {service.port ? <Mono>:{service.port}</Mono> : null}
        {service.p95_ms !== null && service.p95_ms !== undefined ? (
          <span className="tnum">{service.p95_ms} мс</span>
        ) : null}
      </div>

      {facts.length ? (
        <dl className="flex flex-col gap-1 text-body-sm">
          {facts.map(([key, value]) => (
            <div key={key} className="flex justify-between gap-3">
              <dt className="text-text-subtle">{key}</dt>
              <dd className="truncate text-text-muted">{String(value)}</dd>
            </div>
          ))}
        </dl>
      ) : (
        // Сервис жив, но о себе ничего не рассказал — так и пишем.
        <p className="text-body-sm text-text-subtle">
          {status === "down" ? "Не отвечает" : "Подробностей не сообщает"}
        </p>
      )}
    </Card>
  );
}

function QueuesSection() {
  const client = useQueryClient();
  const toast = useToast();

  const queues = useQuery<Queues>({
    queryKey: ["monitoring", "queues"],
    queryFn: ({ signal }) => endpoints.queues(signal),
    staleTime: STALE.health,
    refetchInterval: STALE.health,
  });

  const retry = useMutation({
    mutationFn: (messageId: string) => endpoints.retryDeadLetter(messageId),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["monitoring", "queues"] });
      toast.show({ title: "Сообщение возвращено в очередь", tone: "moss" });
    },
    onError: (error: Error) => toast.show({ title: error.message, tone: "signal" }),
  });

  if (queues.isLoading) return <TextSkeleton lines={6} />;

  const data = queues.data;
  const ladder = data?.retry_ladder ?? [];
  const dead = data?.dead_letters ?? [];

  return (
    <section className="flex flex-col gap-3">
      <SectionHeading title={ru.monitoring.queues} />

      <Card padded={false}>
        <Table>
          <THead>
            <TR>
              <TH>Очередь</TH>
              <TH numeric>В работе</TH>
              <TH numeric>Потребителей</TH>
              <TH numeric>Недоставлено</TH>
            </TR>
          </THead>
          <TBody>
            {(data?.queues ?? []).map((queue) => (
              <TR key={queue.name}>
                <TD>
                  <Mono>{queue.name}</Mono>
                </TD>
                <TD numeric>
                  {formatCount(queue.depth)}
                </TD>
                <TD numeric>
                  {/* Ноль потребителей при непустой очереди — это остановка. */}
                  {queue.consumers === 0 && queue.depth > 0 ? (
                    <span className="text-signal-fg">0</span>
                  ) : (
                    queue.consumers
                  )}
                </TD>
                <TD numeric>
                  {queue.dead_letters > 0 ? (
                    <span className="text-signal-fg">{formatCount(queue.dead_letters)}</span>
                  ) : (
                    "0"
                  )}
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </Card>

      {/* Лестница повторов: 5с → 30с → 2м → 10м → 1ч. Цифры здесь —
          информация о порядке, а не украшение. */}
      <div className="flex flex-wrap items-center gap-2">
        {ladder.map((stage, index) => (
          <span key={stage.stage} className="flex items-center gap-2">
            {index > 0 ? <span className="text-text-subtle">→</span> : null}
            <span
              className={
                stage.depth > 0
                  ? "rounded-[6px] surface-oak-tint px-2 py-1 text-body-sm"
                  : "rounded-[6px] px-2 py-1 text-body-sm text-text-subtle"
              }
            >
              {stage.stage}
              {stage.depth > 0 ? ` · ${formatCount(stage.depth)}` : ""}
            </span>
          </span>
        ))}
      </div>

      {dead.length ? (
        <Card padded={false}>
          <Table>
            <THead>
              <TR>
                <TH>Сообщение</TH>
                <TH>Событие</TH>
                <TH>Ошибка</TH>
                <TH />
              </TR>
            </THead>
            <TBody>
              {dead.map((letter) => (
                <TR key={letter.message_id}>
                  <TD>
                    <Mono>{letter.message_id.slice(0, 8)}</Mono>
                  </TD>
                  <TD>
                    <Mono>{letter.event}</Mono>
                  </TD>
                  <TD className="text-body-sm text-text-muted">{letter.error ?? "—"}</TD>
                  <TD numeric>
                    <Button
                      size="sm"
                      variant="secondary"
                      loading={retry.isPending}
                      onClick={() => retry.mutate(letter.message_id)}
                    >
                      Повторить
                    </Button>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </Card>
      ) : (
        <p className="text-body-sm text-text-subtle">Недоставленных сообщений нет.</p>
      )}
    </section>
  );
}
