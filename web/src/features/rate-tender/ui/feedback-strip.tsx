"use client";

import * as React from "react";
import { EyeOff, ThumbsDown, ThumbsUp, Trophy } from "lucide-react";
import { Button } from "@/shared/ui/button";
import { useToast } from "@/shared/ui/toast";
import { ru } from "@/shared/i18n/ru";
import { cn } from "@/shared/lib/cn";
import type { FeedbackSignal } from "@/shared/api/types";
import { inverseSignal, useMarkWin, useRateTender } from "../model/use-rate-tender";

/**
 * Полоса оценки. Оптимистичная: кнопка отмечается сразу, а «Отменить» в тосте
 * шлёт обратную мутацию — не правку кеша, иначе сервер и экран разойдутся.
 */
export function FeedbackStrip({
  tenderId,
  okpd2,
  region,
  className,
}: {
  tenderId: number;
  okpd2?: string | null;
  region?: string | null;
  className?: string;
}) {
  const rate = useRateTender();
  const win = useMarkWin();
  const toast = useToast();
  const [given, setGiven] = React.useState<FeedbackSignal | null>(null);

  const send = (signal: FeedbackSignal) => {
    const previous = given;
    setGiven(signal);

    rate.mutate(
      { tenderId, signal },
      {
        onSuccess: () => {
          const inverse = inverseSignal(signal);
          toast.show({
            title: weightsPreview(signal, okpd2, region),
            tone: "moss",
            undo: inverse
              ? () => {
                  setGiven(previous);
                  rate.mutate({ tenderId, signal: inverse });
                }
              : undefined,
          });
        },
        onError: () => {
          setGiven(previous);
          toast.show({ title: ru.feedback.failed, tone: "signal" });
        },
      },
    );
  };

  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-2 border-t border-hairline bg-surface px-4 py-3",
        className,
      )}
    >
      <span className="text-body-sm text-text-muted">{ru.feedback.useful}</span>
      <Button
        size="sm"
        variant={given === "like" ? "primary" : "secondary"}
        icon={<ThumbsUp className="h-4 w-4" strokeWidth={1.5} />}
        onClick={() => send("like")}
      >
        {ru.feedback.yes}
      </Button>
      <Button
        size="sm"
        variant={given === "dislike" ? "primary" : "secondary"}
        icon={<ThumbsDown className="h-4 w-4" strokeWidth={1.5} />}
        onClick={() => send("dislike")}
      >
        {ru.feedback.no}
      </Button>
      <Button
        size="sm"
        variant="ghost"
        icon={<EyeOff className="h-4 w-4" strokeWidth={1.5} />}
        onClick={() => send("hide")}
      >
        {ru.feedback.hideSimilar}
      </Button>
      <Button
        size="sm"
        variant="ghost"
        className="ml-auto"
        loading={win.isPending}
        icon={<Trophy className="h-4 w-4" strokeWidth={1.5} />}
        onClick={() =>
          win.mutate(tenderId, {
            onSuccess: () => toast.show({ title: ru.feedback.recorded, tone: "moss" }),
          })
        }
      >
        {ru.feedback.markWin}
      </Button>
    </div>
  );
}

/**
 * Что именно уехало в профиль. Показать это сразу — единственный способ
 * объяснить, почему завтра выдача другая.
 */
function weightsPreview(
  signal: FeedbackSignal,
  okpd2?: string | null,
  region?: string | null,
): string {
  const sign = signal === "dislike" || signal === "hide" ? "−" : "+";
  const parts = [
    okpd2 ? `${sign}${ru.tender.okpd2} ${okpd2}` : null,
    region ? `${sign}${region}` : null,
  ].filter(Boolean);

  return parts.length ? ru.feedback.recordedWeights(parts.join(", ")) : ru.feedback.recorded;
}
