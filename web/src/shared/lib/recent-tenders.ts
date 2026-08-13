"use client";

import * as React from "react";
import { useLocalStorage } from "./hooks";

export type RecentTender = { regNum: string; name: string };

const RECENT_KEY = "zakupki:recent-tenders";
const RECENT_LIMIT = 8;

/**
 * Недавно открытые закупки: их показывает командная строка, а пополняет
 * карточка. Двум виджетам нужен один список — значит, его место в shared,
 * а не в одном из них.
 */
export function useRecentTenders() {
  const [recent, setRecent] = useLocalStorage<RecentTender[]>(RECENT_KEY, []);

  const remember = React.useCallback(
    (tender: RecentTender) => {
      setRecent(
        [tender, ...recent.filter((item) => item.regNum !== tender.regNum)].slice(0, RECENT_LIMIT),
      );
    },
    [recent, setRecent],
  );

  return { recent, remember };
}
