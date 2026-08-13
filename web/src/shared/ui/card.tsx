import * as React from "react";
import { cn } from "@/shared/lib/cn";

export type CardProps = React.HTMLAttributes<HTMLDivElement> & {
  /** Тень при наведении появляется только у карточек-ссылок. */
  interactive?: boolean;
  padded?: boolean;
};

export function Card({ className, interactive, padded = true, ...props }: CardProps) {
  return (
    <div
      className={cn(
        "rounded-[10px] border border-hairline bg-surface",
        padded && "p-6",
        interactive &&
          "transition-shadow duration-(--dur-state) ease-(--ease-enter) hover:shadow-(--shadow-raise)",
        className,
      )}
      {...props}
    />
  );
}

export function CardTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h3 className={cn("text-h3", className)} {...props} />;
}

export function CardMeta({ className, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn("text-body-sm text-text-muted", className)} {...props} />;
}
