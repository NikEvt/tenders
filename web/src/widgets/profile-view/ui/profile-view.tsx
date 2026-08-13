"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/shared/ui/button";
import { Mono } from "@/shared/ui/mono";
import { Card } from "@/shared/ui/card";
import { Bar } from "@/shared/ui/bar";
import { Pill } from "@/shared/ui/pill";
import { SectionHeading } from "@/shared/ui/section";
import { TextSkeleton } from "@/shared/ui/skeleton";
import { ru } from "@/shared/i18n/ru";
import { money } from "@/shared/lib/format";
import { formatCount } from "@/shared/lib/plural";
import { endpoints } from "@/shared/api/endpoints";
import { qk, SINGLE_PROFILE_ID, STALE } from "@/shared/api/query-keys";

/** Порог, за которым recsys подключает обученный ранжировщик. */
const RANKER_THRESHOLD = 500;

export function ProfileView() {
  const profile = useQuery({
    queryKey: qk.profile(SINGLE_PROFILE_ID),
    queryFn: ({ signal }) => endpoints.profile(signal),
    staleTime: STALE.profile,
  });

  if (profile.isLoading) return <TextSkeleton lines={10} />;
  if (!profile.data) return null;

  const weights = Object.entries(profile.data.okpd2_weights ?? {}).sort((a, b) => b[1] - a[1]);
  const maxWeight = weights[0]?.[1] ?? 1;
  const stats = profile.data.price_stats ?? {};

  return (
    <div className="flex flex-col gap-8">
      <div className="grid gap-4 md:grid-cols-3">
        <Card className="flex flex-col gap-1">
          <p className="text-caption uppercase text-text-muted">{ru.profile.signals}</p>
          <p className="font-mono text-h1 tnum">{formatCount(profile.data.signal_count)}</p>
        </Card>
        <Card className="flex flex-col gap-1">
          <p className="text-caption uppercase text-text-muted">{ru.profile.priceBand}</p>
          <p className="font-mono text-body tnum">
            {stats.min !== undefined ? money(stats.min) : "—"} — {stats.max !== undefined ? money(stats.max) : "—"}
          </p>
        </Card>
        <Card className="flex flex-col gap-2">
          <p className="text-caption uppercase text-text-muted">Вектор профиля</p>
          <Pill tone={profile.data.has_embedding ? "moss" : "neutral"}>
            {profile.data.has_embedding ? ru.profile.hasEmbedding : ru.profile.noEmbedding}
          </Pill>
        </Card>
      </div>

      <section className="flex flex-col gap-3">
        <SectionHeading title={`${ru.profile.weights} · ${ru.tender.okpd2}`} />
        {weights.length === 0 ? (
          <p className="text-body-sm text-text-muted">{ru.recommendations.coldStartBody}</p>
        ) : (
          <Card className="flex flex-col gap-1">
            {weights.map(([code, weight]) => (
              <Bar key={code} label={code} value={Math.round(weight * 1000) / 1000} max={maxWeight} />
            ))}
          </Card>
        )}
        <p className="text-body-sm text-text-subtle">{ru.profile.weightsHint}</p>
      </section>

      <section className="flex flex-col gap-3">
        <SectionHeading title={ru.profile.rankerStatus} />
        <Card className="flex flex-col gap-3">
          <p className="text-body text-text">
            {ru.profile.rankerLinear(profile.data.signal_count, RANKER_THRESHOLD)}
          </p>
          <span className="h-2 w-full max-w-96 overflow-hidden rounded-full bg-hairline">
            <span
              className="block h-full rounded-full bg-gos-fg"
              style={{
                width: `${Math.min(100, (profile.data.signal_count / RANKER_THRESHOLD) * 100)}%`,
              }}
            />
          </span>
        </Card>
      </section>

      <ProfileWeights />
      <ProfileHistory />
      <ProfileWins />
    </div>
  );
}


/**
 * Веса профиля.
 *
 * `source` показывает происхождение: вычисленный вес меняется сам, ручной —
 * переживает пересборку. Сброс отправляет `null`, а не ноль: ноль означал бы
 * «этот код мне не нужен», и это другое утверждение.
 */
function ProfileWeights() {
  const client = useQueryClient();
  const weights = useQuery({
    queryKey: ["profile", "weights"],
    queryFn: ({ signal }) => endpoints.profileWeights(signal),
  });

  const update = useMutation({
    mutationFn: ({ key, weight }: { key: string; weight: number | null }) =>
      endpoints.setProfileWeight(key, weight),
    onSuccess: () => client.invalidateQueries({ queryKey: ["profile", "weights"] }),
  });

  const items = (weights.data ?? []) as {
    key: string;
    label: string;
    weight: number;
    source: string;
  }[];

  return (
    <section className="flex flex-col gap-3">
      <SectionHeading title="Веса" />
      {weights.isLoading ? (
        <TextSkeleton lines={5} />
      ) : items.length === 0 ? (
        <p className="text-body-sm text-text-subtle">
          Весов пока нет: профиль строится по оценкам, а их ещё недостаточно.
        </p>
      ) : (
        <Card padded={false}>
          <ul className="divide-y divide-hairline">
            {items.map((weight) => (
              <li key={weight.key} className="flex items-center gap-3 px-4 py-3">
                <Mono className="w-32 shrink-0">{weight.key}</Mono>
                <span className="tnum w-16 text-body-sm text-text">
                  {weight.weight.toFixed(2)}
                </span>
                <span className="text-caption text-text-subtle">
                  {weight.source === "manual" ? "вручную" : "вычислен"}
                </span>
                <span className="ml-auto flex items-center gap-2">
                  <input
                    type="range"
                    min={-1}
                    max={1}
                    step={0.1}
                    defaultValue={weight.weight}
                    aria-label={`Вес ${weight.key}`}
                    onMouseUp={(event) =>
                      update.mutate({
                        key: weight.key,
                        weight: Number((event.target as HTMLInputElement).value),
                      })
                    }
                  />
                  {weight.source === "manual" ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => update.mutate({ key: weight.key, weight: null })}
                    >
                      Сбросить
                    </Button>
                  ) : null}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </section>
  );
}

function ProfileHistory() {
  const client = useQueryClient();
  const history = useQuery({
    queryKey: ["profile", "history"],
    queryFn: ({ signal }) => endpoints.profileHistory(0, signal),
  });

  const remove = useMutation({
    mutationFn: (signalId: number) => endpoints.deleteRating(signalId),
    onSuccess: () => client.invalidateQueries({ queryKey: ["profile"] }),
  });

  const items = history.data?.items ?? [];

  return (
    <section className="flex flex-col gap-3">
      <SectionHeading title={ru.profile.history} />
      {history.isLoading ? (
        <TextSkeleton lines={5} />
      ) : items.length === 0 ? (
        <p className="text-body-sm text-text-subtle">Оценок пока нет.</p>
      ) : (
        <Card padded={false}>
          <ul className="divide-y divide-hairline">
            {items.map((record) => (
              <li key={record.signal_id} className="flex items-center gap-3 px-4 py-3">
                <span className="w-20 shrink-0 text-body-sm text-text-muted">
                  {record.signal}
                </span>
                <Link
                  href={`/tenders/${record.reg_num}`}
                  className="min-w-0 flex-1 truncate text-body-sm text-text hover:text-gos-fg"
                >
                  {record.name ?? record.reg_num}
                </Link>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => remove.mutate(record.signal_id)}
                >
                  Отменить
                </Button>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </section>
  );
}

function ProfileWins() {
  const wins = useQuery({
    queryKey: ["profile", "wins"],
    queryFn: ({ signal }) => endpoints.profileWins(signal),
  });

  const items = wins.data?.items ?? [];

  return (
    <section className="flex flex-col gap-3">
      <SectionHeading title={ru.profile.wins} />
      {wins.isLoading ? (
        <TextSkeleton lines={4} />
      ) : items.length === 0 ? (
        <p className="text-body-sm text-text-subtle">Выигранных закупок пока нет.</p>
      ) : (
        <Card className="flex flex-col gap-3">
          <ul className="flex flex-col divide-y divide-hairline">
            {items.map((win) => (
              <li key={win.tender_id} className="flex items-center gap-3 py-2">
                <Link
                  href={`/tenders/${win.reg_num}`}
                  className="min-w-0 flex-1 truncate text-body-sm text-text hover:text-gos-fg"
                >
                  {win.name ?? win.reg_num}
                </Link>
                <span className="tnum text-body-sm text-text-muted">
                  {money(win.contract_price)}
                </span>
              </li>
            ))}
          </ul>
          {/* Итог по цене контракта, а не по НМЦК: последняя завышена почти всегда. */}
          <p className="text-body-sm text-text-muted">
            Итого по контрактам: <span className="tnum">{money(wins.data?.total_value)}</span>
          </p>
        </Card>
      )}
    </section>
  );
}
