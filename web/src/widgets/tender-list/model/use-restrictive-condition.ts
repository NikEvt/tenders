"use client";

import { useQuery } from "@tanstack/react-query";
import { ru } from "@/shared/i18n/ru";
import { endpoints } from "@/shared/api/endpoints";
import type { CatalogParams } from "./use-catalog-params";
import { toTenderQuery } from "./use-catalog-params";
import { activeConditions, type ActiveCondition } from "./active-conditions";

export type RestrictiveHint = {
  condition: ActiveCondition;
  /** Сколько нашлось бы без этого условия. Настоящее число, а не оценка. */
  withoutCount: number;
};

/**
 * Какое одно условие отсекает больше всего.
 *
 * Считает сервер: `GET /tenders/facets?explain_empty=true` возвращает имя
 * параметра и число строк без него. Раньше клиент выяснял это перебором —
 * по запросу на каждое условие; теперь это один запрос и один проход по базе.
 *
 * Запускается только на пустой выдаче: там от подсказки есть польза.
 */
export function useRestrictiveCondition(params: CatalogParams, enabled: boolean) {
  const conditions = activeConditions(params);

  return useQuery<RestrictiveHint | null>({
    queryKey: ["tenders", "restrictive", toTenderQuery(params)],
    enabled: enabled && conditions.length > 0,
    staleTime: 60_000,
    queryFn: async ({ signal }) => {
      const facets = await endpoints.tenderFacets(
        { ...toTenderQuery(params), explain_empty: true },
        signal,
      );

      const hint = facets.restrictive;
      if (!hint) return null;

      const condition = matchCondition(hint.param, conditions, params);
      if (!condition) return null;

      return { condition, withoutCount: hint.kept };
    },
  });
}

/**
 * Имя серверного параметра → снимаемое условие интерфейса.
 *
 * Совпадает почти везде, кроме регионов: в адресной строке это отдельный чип
 * на каждый регион, а в запросе — одно условие `region`. Снимать надо все,
 * иначе обещанное число не сойдётся с тем, что увидит пользователь.
 */
function matchCondition(
  param: string,
  conditions: ActiveCondition[],
  params: CatalogParams,
): ActiveCondition | null {
  if (param === "region") {
    if (!params.region.length) return null;
    return {
      id: "region",
      label:
        params.region.length === 1
          ? conditions.find((c) => c.id.startsWith("region:"))!.label
          : `${ru.catalog.facets.region}: ${params.region.length}`,
      clear: { region: [], page: 0 },
    };
  }
  return conditions.find((condition) => condition.id === param) ?? null;
}
