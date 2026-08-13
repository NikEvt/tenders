"use client";

import * as React from "react";
import { cn } from "@/shared/lib/cn";

const control = [
  "w-full rounded-[6px] border border-border-strong bg-surface-sunken px-3 text-body text-text",
  "placeholder:text-text-subtle",
  "transition-[border-color,box-shadow] duration-(--dur-state)",
  "focus:border-gos-fg focus:outline-none focus:ring-[3px] focus:ring-gos-fg/12",
  "disabled:opacity-40",
].join(" ");

export function Label({ className, ...props }: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return (
    <label className={cn("block text-caption text-text-muted", className)} {...props} />
  );
}

export type FieldProps = {
  label?: string;
  hint?: React.ReactNode;
  error?: string;
  htmlFor?: string;
  children: React.ReactNode;
  className?: string;
};

export function Field({ label, hint, error, htmlFor, children, className }: FieldProps) {
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      {label ? <Label htmlFor={htmlFor}>{label}</Label> : null}
      {children}
      {error ? (
        <p className="text-body-sm text-signal-fg" role="alert">
          {error}
        </p>
      ) : hint ? (
        <p className="text-body-sm text-text-muted">{hint}</p>
      ) : null}
    </div>
  );
}

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...props }, ref) {
    return <input ref={ref} className={cn(control, "h-10", className)} {...props} />;
  },
);

export const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(function Textarea({ className, ...props }, ref) {
  return <textarea ref={ref} className={cn(control, "min-h-20 py-2", className)} {...props} />;
});

export const Select = React.forwardRef<
  HTMLSelectElement,
  React.SelectHTMLAttributes<HTMLSelectElement>
>(function Select({ className, ...props }, ref) {
  return <select ref={ref} className={cn(control, "h-10 pr-8", className)} {...props} />;
});

/** Чекбокс с квадратной формой 6px — тот же радиус, что у полей. */
export const Checkbox = React.forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement>
>(function Checkbox({ className, ...props }, ref) {
  return (
    <input
      ref={ref}
      type="checkbox"
      className={cn(
        "h-4 w-4 shrink-0 cursor-pointer rounded-[4px] border border-border-strong accent-gos-fg",
        className,
      )}
      {...props}
    />
  );
});
