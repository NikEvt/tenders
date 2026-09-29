"use client";

import * as React from "react";
import { Progress } from "@/shared/ui/progress";
import { ru } from "@/shared/i18n/ru";
import { cn } from "@/shared/lib/cn";
import { useElapsed } from "@/shared/lib/hooks";
import { duration } from "@/shared/api/job-progress";

/**
 * Ожидание синхронной операции — той, у которой нет задания и не будет.
 *
 * Компиляция критерия и векторный поиск — это один HTTP-запрос, который клиент
 * и так ждёт. Заводить ради них строку в таблице заданий, воркера и опрос
 * значило бы построить механизм там, где хватает честной подписи. Но и
 * спиннера в кнопке не хватает: тридцать секунд тишины неотличимы от зависшего
 * интерфейса.
 *
 * Шкала всегда неопределённая — знаменателя у такой операции нет и быть не
 * может. Идёт время, и это всё, что здесь правда.
 */
export function WaitingBlock({
  title,
  startedAt,
  hint,
  hintAfterMs = 5000,
  className,
}: {
  title: string;
  /** Когда начали ждать. `null` — ожидание ещё не началось. */
  startedAt: number | null;
  /** Приписка для затянувшегося ожидания: объясняет, а не извиняется. */
  hint?: string;
  hintAfterMs?: number;
  className?: string;
}) {
  const elapsed = useElapsed(startedAt, startedAt !== null);
  if (startedAt === null) return null;

  return (
    <div
      aria-live="polite"
      className={cn(
        "flex flex-col gap-2 rounded-[10px] border border-hairline bg-surface-sunken px-4 py-3",
        className,
      )}
    >
      <p className="text-body-sm text-text">{title}</p>
      <Progress label={ru.waiting.scaleUnknown} />
      <p className="flex flex-wrap items-baseline gap-x-3 text-caption text-text-subtle">
        <span className="tnum">{ru.waiting.elapsed(duration(elapsed))}</span>
        {/* Приписка появляется по времени, а не по признаку `device: cpu` из
            состояния соседнего сервиса: клиент не должен выводить причину
            задержки из чужой конфигурации — он её всё равно не знает. */}
        {hint && elapsed >= hintAfterMs ? <span>{hint}</span> : null}
      </p>
    </div>
  );
}

/**
 * Момент начала ожидания.
 *
 * Ставится один раз на переход «не ждём → ждём» и снимается на обратном.
 * Считать от каждой перерисовки нельзя: время сбрасывалось бы при любом
 * обновлении соседнего состояния, и подпись всегда показывала бы «0 с».
 */
export function useWaitingSince(waiting: boolean): number | null {
  const [since, setSince] = React.useState<number | null>(null);

  React.useEffect(() => {
    setSince(waiting ? Date.now() : null);
  }, [waiting]);

  return waiting ? since : null;
}
