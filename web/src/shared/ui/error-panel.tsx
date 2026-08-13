"use client";

import * as React from "react";
import { TriangleAlert } from "lucide-react";
import { Button } from "@/shared/ui/button";
import { Mono } from "@/shared/ui/mono";
import { ru } from "@/shared/i18n/ru";
import { ApiError } from "@/shared/api/client";

/**
 * Ошибка называет, что именно не сработало и что делать. Без «упс», без
 * «что-то пошло не так» и без извинений — они не помогают чинить.
 */
export function ErrorPanel({ error, reset }: { error: Error; reset?: () => void }) {
  const [copied, setCopied] = React.useState(false);
  const apiError = error instanceof ApiError ? error : null;

  const details =
    apiError?.toClipboard() ??
    [`error: ${error.message}`, `time: ${new Date().toISOString()}`].join("\n");

  return (
    <div
      role="alert"
      className="mx-auto flex max-w-2xl flex-col items-start gap-4 rounded-[10px] border border-signal-fg/30 surface-signal-tint p-6"
    >
      <TriangleAlert className="h-8 w-8 text-signal-fg" strokeWidth={1.5} aria-hidden="true" />
      <div>
        <h2 className="text-h2">{ru.errors.title}</h2>
        <p className="mt-2 text-body text-text">
          {apiError?.status === 0 ? ru.errors.network : (apiError?.detail ?? error.message)}
        </p>
        {apiError ? (
          <Mono className="mt-3 block">
            {apiError.endpoint} · {apiError.status}
          </Mono>
        ) : null}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {reset ? (
          <Button variant="primary" onClick={reset}>
            {ru.common.retry}
          </Button>
        ) : null}
        <Button
          variant="secondary"
          onClick={async () => {
            await navigator.clipboard.writeText(details);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1600);
          }}
        >
          {copied ? ru.common.copied : ru.common.copyDetails}
        </Button>
      </div>
    </div>
  );
}
