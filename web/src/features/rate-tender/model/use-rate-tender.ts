"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { endpoints } from "@/shared/api/endpoints";
import { qk, SINGLE_PROFILE_ID } from "@/shared/api/query-keys";
import type { FeedbackSignal } from "@/shared/api/types";

export type RateInput = {
  tenderId: number;
  signal: FeedbackSignal;
  reason?: string;
};

/** Обратный сигнал для кнопки «Отменить» в тосте. */
const INVERSE: Partial<Record<FeedbackSignal, FeedbackSignal>> = {
  like: "dislike",
  dislike: "like",
};

/**
 * Оценка закупки. Инвалидация узкая: оценка меняет профиль и рекомендации,
 * но не каталог — перезапрашивать список из-за одного лайка незачем.
 */
export function useRateTender() {
  const client = useQueryClient();

  return useMutation<Record<string, string>, Error, RateInput>({
    mutationFn: ({ tenderId, signal, reason }) => endpoints.feedback(tenderId, signal, reason),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: qk.profile(SINGLE_PROFILE_ID) });
      void client.invalidateQueries({ queryKey: ["recs"] });
    },
  });
}

export function inverseSignal(signal: FeedbackSignal): FeedbackSignal | null {
  return INVERSE[signal] ?? null;
}

export function useMarkWin() {
  const client = useQueryClient();

  return useMutation({
    mutationFn: (tenderId: number) => endpoints.win({ tender_id: tenderId }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: qk.profile(SINGLE_PROFILE_ID) });
    },
  });
}

/** Просмотр — слабый сигнал, шлётся молча и без оптимистичных правок. */
export function useRecordView() {
  return useMutation({
    mutationFn: ({ tenderId, dwellMs }: { tenderId: number; dwellMs?: number }) =>
      endpoints.view(tenderId, dwellMs),
  });
}
