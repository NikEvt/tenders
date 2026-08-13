"use client";

import { useMutation } from "@tanstack/react-query";
import { endpoints } from "@/shared/api/endpoints";
import type { CompileResult } from "@/shared/api/types";
import { isDegraded } from "../lib/detect-degraded";
import { degradedStore } from "./degraded-store";

/**
 * Компиляция свободного текста в фильтр. Каждый ответ проверяется на признак
 * деградации — баннер поднимается отсюда, а не с конкретного экрана.
 */
export function useCompileFilter() {
  return useMutation<CompileResult, Error, string>({
    mutationFn: (query) => endpoints.compileFilter(query),
    onSuccess: (result, query) => {
      degradedStore.report(isDegraded(query, result.spec));
    },
  });
}
