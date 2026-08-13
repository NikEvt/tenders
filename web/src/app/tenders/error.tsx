"use client";

import { ErrorPanel } from "@/shared/ui/error-panel";

export default function Error({ error, reset }: { error: Error; reset: () => void }) {
  return <ErrorPanel error={error} reset={reset} />;
}
