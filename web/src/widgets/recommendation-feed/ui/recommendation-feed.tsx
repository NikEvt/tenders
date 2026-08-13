"use client";

import * as React from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Sparkle, ThumbsDown, ThumbsUp } from "lucide-react";
import { Button } from "@/shared/ui/button";
import { Card } from "@/shared/ui/card";
import { EmptyState } from "@/shared/ui/empty-state";
import { ListSkeleton } from "@/shared/ui/skeleton";
import { Popover, PopoverContent, PopoverTrigger } from "@/shared/ui/popover";
import { useToast } from "@/shared/ui/toast";
import { Rail } from "@/shared/ui/rail/rail";
import { CopyableMono } from "@/shared/ui/mono";
import { ru } from "@/shared/i18n/ru";
import { cn } from "@/shared/lib/cn";
import { compactMoney, toDate } from "@/shared/lib/format";
import { endpoints } from "@/shared/api/endpoints";
import { qk, SINGLE_PROFILE_ID, STALE } from "@/shared/api/query-keys";
import type { Recommendation } from "@/shared/api/types";
import { useRateTender } from "@/features/rate-tender/model/use-rate-tender";

const LIMIT = 30;
const COLD_START_RATINGS = 20;

/** Человеческие названия факторов ранжирования из recsys-service. */
const FACTOR_LABELS: Record<string, string> = {
  similarity: "похоже на интересовавшие",
  okpd2_match: "совпадает ОКПД2",
  price_fit: "бюджет в вашем диапазоне",
  known_customer: "знакомый заказчик",
  freshness: "свежая публикация",
};

export function RecommendationFeed() {
  const profile = useQuery({
    queryKey: qk.profile(SINGLE_PROFILE_ID),
    queryFn: ({ signal }) => endpoints.profile(signal),
    staleTime: STALE.profile,
  });

  const feed = useQuery({
    queryKey: qk.recs(SINGLE_PROFILE_ID, LIMIT),
    queryFn: ({ signal }) => endpoints.recommendations(LIMIT, signal),
    staleTime: STALE.profile,
  });

  if (feed.isLoading || profile.isLoading) return <ListSkeleton rows={6} />;

  const signals = profile.data?.signal_count ?? 0;
  if (signals < COLD_START_RATINGS) {
    return <ColdStart current={signals} target={COLD_START_RATINGS} />;
  }

  if (!feed.data?.length) {
    return (
      <EmptyState
        icon={<Sparkle strokeWidth={1.5} />}
        title={ru.recommendations.emptyTitle}
        body={ru.recommendations.emptyBody}
        action={
          <Button asChild variant="primary">
            <Link href="/tenders">{ru.catalog.title}</Link>
          </Button>
        }
      />
    );
  }

  return (
    <div className="flex gap-8">
      <ul className="flex min-w-0 flex-1 flex-col gap-3">
        {feed.data.map((item) => (
          <li key={item.tender_id}>
            <RecommendationCard item={item} />
          </li>
        ))}
      </ul>

      <aside className="hidden w-64 shrink-0 lg:block">
        <p className="rounded-[10px] border border-hairline bg-surface p-4 text-body-sm text-text-muted">
          {ru.recommendations.explorationNote}
        </p>
      </aside>
    </div>
  );
}

function RecommendationCard({ item }: { item: Recommendation }) {
  const rate = useRateTender();
  const toast = useToast();
  const exploration = item.explanation?.exploration ?? false;
  const factors = Object.entries(item.explanation?.factors ?? {})
    .map(([factor, contribution]) => ({
      factor,
      label: FACTOR_LABELS[factor] ?? factor,
      contribution,
    }))
    .filter((f) => f.contribution > 0)
    .sort((a, b) => b.contribution - a.contribution);

  const max = factors[0]?.contribution ?? 1;

  return (
    <Card
      padded={false}
      className={cn(
        "flex flex-col gap-3 p-4",
        exploration && "border-t-2 border-t-transparent [border-top-style:dotted] border-t-oak-fg",
      )}
    >
      {exploration ? (
        <p className="text-caption uppercase text-oak-fg">{ru.recommendations.exploration}</p>
      ) : null}

      <div className="flex items-start gap-4">
        <div className="min-w-0 flex-1">
          <Link
            href={`/tenders/${item.reg_num}`}
            className="clamp-2 text-body font-medium text-text no-underline hover:text-gos-fg"
          >
            {item.name ?? item.reg_num}
          </Link>
          <p className="mt-1 text-body-sm text-text-muted">{item.customer_name}</p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <span className="font-mono text-body tnum">{compactMoney(item.price)}</span>
          <Rail deadline={toDate(item.end_date)} scale="micro" />
        </div>
      </div>

      {/* Объяснение есть всегда: рекомендация без причины — это гадание. */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <span className="text-caption text-text-muted">{ru.recommendations.why}:</span>
        {factors.length === 0 ? (
          <span className="text-body-sm text-text-subtle">{ru.ai.noSource}</span>
        ) : (
          factors.map((factor) => (
            <span
              key={factor.factor}
              className="flex items-center gap-1.5 rounded-[6px] surface-gos-tint px-2 py-0.5 text-body-sm"
              // Ширина пропорциональна вкладу; сумма вкладов ничего не значит,
              // и компонент на неё не опирается — обученный ранжировщик придёт
              // с той же формой данных, но без линейности.
              style={{ minWidth: `${60 + (factor.contribution / max) * 80}px` }}
              title={`${factor.label}: ${factor.contribution.toFixed(3)}`}
            >
              {factor.label}
            </span>
          ))
        )}
      </div>

      <div className="flex items-center gap-2">
        <CopyableMono value={item.reg_num} label={ru.tender.regNum} />
        <span className="ml-auto flex items-center gap-1">
          <Button
            size="icon-sm"
            variant="ghost"
            aria-label={ru.feedback.yes}
            onClick={() =>
              rate.mutate(
                { tenderId: item.tender_id, signal: "like" },
                { onSuccess: () => toast.show({ title: ru.feedback.recorded, tone: "moss" }) },
              )
            }
          >
            <ThumbsUp className="h-4 w-4" strokeWidth={1.5} />
          </Button>
          <Button
            size="icon-sm"
            variant="ghost"
            aria-label={ru.feedback.no}
            onClick={() =>
              rate.mutate(
                { tenderId: item.tender_id, signal: "dislike" },
                { onSuccess: () => toast.show({ title: ru.feedback.recorded, tone: "moss" }) },
              )
            }
          >
            <ThumbsDown className="h-4 w-4" strokeWidth={1.5} />
          </Button>
          <DownweightPopover item={item} />
        </span>
      </div>
    </Card>
  );
}

/**
 * «Не показывать такие» спрашивает, что именно понизить. Догадываться —
 * значит испортить профиль тем, что пользователь не имел в виду.
 */
function DownweightPopover({ item }: { item: Recommendation }) {
  const rate = useRateTender();
  const toast = useToast();

  const send = (reason: string) =>
    rate.mutate(
      { tenderId: item.tender_id, signal: "hide", reason },
      { onSuccess: () => toast.show({ title: ru.feedback.recorded, tone: "moss" }) },
    );

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button size="sm" variant="quiet">
          {ru.recommendations.notLikeThis}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-64">
        <p className="mb-3 text-body-sm text-text-muted">{ru.recommendations.downweightWhat}</p>
        <div className="flex flex-col gap-1">
          <Button variant="ghost" size="sm" onClick={() => send("customer")}>
            {ru.recommendations.downweightCustomer}
          </Button>
          <Button variant="ghost" size="sm" onClick={() => send("okpd2")}>
            {ru.recommendations.downweightOkpd2}
          </Button>
          <Button variant="ghost" size="sm" onClick={() => send("region")}>
            {ru.recommendations.downweightRegion}
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}

function ColdStart({ current, target }: { current: number; target: number }) {
  return (
    <Card className="flex flex-col gap-4">
      <h2 className="text-h2">{ru.recommendations.coldStartTitle}</h2>
      <p className="measure text-body text-text-muted">{ru.recommendations.coldStartBody}</p>
      <div className="flex items-center gap-3">
        <span className="h-2 w-64 overflow-hidden rounded-full bg-hairline">
          <span
            className="block h-full rounded-full bg-gos-fg"
            style={{ width: `${Math.min(100, (current / target) * 100)}%` }}
          />
        </span>
        <span className="font-mono text-body-sm tnum text-text-muted">
          {ru.recommendations.coldStartProgress(current, target)}
        </span>
      </div>
      <Button asChild variant="primary" className="self-start">
        <Link href="/tenders">{ru.catalog.title}</Link>
      </Button>
    </Card>
  );
}
