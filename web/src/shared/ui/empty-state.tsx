import * as React from "react";
import { cn } from "@/shared/lib/cn";

export type EmptyStateProps = {
  icon?: React.ReactNode;
  title: string;
  /** Что делать дальше. Не извинение и не пожатие плечами. */
  body?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
};

export function EmptyState({ icon, title, body, action, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 px-6 py-14 text-center",
        className,
      )}
    >
      {icon ? <div className="text-text-subtle [&>svg]:h-8 [&>svg]:w-8">{icon}</div> : null}
      <h3 className="text-h3">{title}</h3>
      {body ? <div className="measure text-body-sm text-text-muted">{body}</div> : null}
      {action ? <div className="mt-1">{action}</div> : null}
    </div>
  );
}
