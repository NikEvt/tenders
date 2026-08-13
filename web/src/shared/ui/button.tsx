"use client";

import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/shared/lib/cn";
import { Spinner } from "./spinner";

const button = cva(
  [
    "inline-flex items-center justify-center gap-2 rounded-[6px] font-medium",
    "whitespace-nowrap select-none",
    "transition-[background-color,border-color,color,transform] duration-(--dur-state) ease-(--ease-enter)",
    "disabled:pointer-events-none disabled:opacity-40",
    "active:translate-y-[0.5px]",
  ],
  {
    variants: {
      variant: {
        primary: "surface-gos",
        secondary:
          "bg-surface text-text border border-hairline hover:bg-surface-sunken active:bg-canvas",
        ghost: "bg-transparent text-text hover:bg-surface-sunken active:bg-canvas",
        danger: "surface-signal hover:brightness-95 active:brightness-90",
        quiet: "bg-transparent text-text-muted hover:bg-surface-sunken hover:text-text",
      },
      size: {
        sm: "h-8 px-3 text-body-sm",
        md: "h-10 px-4 text-body",
        lg: "h-12 px-5 text-body",
        icon: "h-10 w-10 p-0",
        "icon-sm": "h-8 w-8 p-0",
      },
    },
    defaultVariants: { variant: "secondary", size: "md" },
  },
);

export type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> &
  VariantProps<typeof button> & {
    asChild?: boolean;
    loading?: boolean;
    /** Иконка слева. В состоянии loading её место занимает спиннер — ширина не прыгает. */
    icon?: React.ReactNode;
  };

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant, size, asChild, loading, icon, children, disabled, ...props },
  ref,
) {
  const leading = loading ? <Spinner /> : icon;

  // asChild отдаёт стили ссылке: у Slot должен быть ровно один потомок,
  // поэтому иконку в этом режиме кладут внутрь самой ссылки.
  if (asChild) {
    return (
      <Slot ref={ref} className={cn(button({ variant, size }), className)} {...props}>
        {children}
      </Slot>
    );
  }

  return (
    <button
      ref={ref}
      className={cn(button({ variant, size }), className)}
      disabled={disabled ?? loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {leading}
      {children}
    </button>
  );
});
