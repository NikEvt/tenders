"use client";

import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { NuqsAdapter } from "nuqs/adapters/next/app";
import { TooltipProvider } from "@/shared/ui/tooltip";
import { ToastProvider } from "@/shared/ui/toast";
import { ApiError } from "@/shared/api/client";

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Данные каталога обновляются выгрузкой раз в час — фокус окна не повод
        // дёргать API, а вот возвращение в сеть повод.
        refetchOnWindowFocus: false,
        refetchOnReconnect: true,
        retry: (failureCount, error) => {
          if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
          return failureCount < 2;
        },
      },
    },
  });
}

let browserClient: QueryClient | undefined;

function getQueryClient() {
  if (typeof window === "undefined") return makeQueryClient();
  browserClient ??= makeQueryClient();
  return browserClient;
}

export function Providers({ children }: { children: React.ReactNode }) {
  const client = React.useMemo(getQueryClient, []);

  return (
    <QueryClientProvider client={client}>
      <NuqsAdapter>
        <ThemeProvider attribute="data-theme" defaultTheme="system" enableSystem>
          <TooltipProvider delayDuration={300} skipDelayDuration={200}>
            <ToastProvider>{children}</ToastProvider>
          </TooltipProvider>
        </ThemeProvider>
      </NuqsAdapter>
    </QueryClientProvider>
  );
}
