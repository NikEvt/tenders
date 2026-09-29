"use client";

import { useMutation } from "@tanstack/react-query";
import { endpoints } from "@/shared/api/endpoints";
import type { CompileResult } from "@/shared/api/types";
import { isFallbackCriteria } from "../lib/detect-degraded";
import { degradedStore } from "./degraded-store";

/**
 * Компиляция свободного текста в критерий.
 *
 * Признак деградации теперь виден прямо в ответе: критерий без единого правила
 * по контексту и без предфильтра — это откат на слова запроса, то есть модель
 * не отвечала. Гадать по совпадению слов больше не нужно.
 */
export function useCompileFilter() {
  return useMutation<CompileResult, Error, string>({
    mutationFn: (query) => endpoints.compileFilter(query),
    onSuccess: (result) => {
      degradedStore.report(isFallbackCriteria(result.spec));
    },
  });
}
