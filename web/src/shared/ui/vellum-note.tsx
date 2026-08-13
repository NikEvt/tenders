import * as React from "react";
import { cn } from "@/shared/lib/cn";

export type VellumNoteProps = {
  /** Мелкая моношапка: «ИИ-ВЕРДИКТ · qwen3.6-35b». Обязательна. */
  eyebrow: string;
  /** Откуда текст: модель, версия промпта. Без источника заметка не рисуется. */
  source: string;
  extra?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
};

/**
 * «Пометка на полях» — единственная поверхность для машинного текста.
 *
 * Тёплая бумага против холодной официальной белизны: то, что написала модель,
 * никогда не выглядит как то, что опубликовало государство. Материал и есть
 * сигнал — значка робота здесь не будет.
 */
export function VellumNote({
  eyebrow,
  source,
  extra,
  actions,
  children,
  className,
}: VellumNoteProps) {
  return (
    <aside
      className={cn(
        "relative overflow-hidden rounded-[10px] border border-vellum-edge surface-vellum",
        "pl-[15px] pr-5 py-4",
        className,
      )}
    >
      <span className="absolute left-0 top-0 h-full w-[3px] bg-oak-fg" aria-hidden="true" />
      <p className="text-eyebrow font-mono uppercase text-oak-fg">
        {eyebrow} · {source}
        {extra ? ` · ${extra}` : null}
      </p>
      <div className="mt-2 text-body text-text [&_p]:leading-relaxed">{children}</div>
      {actions ? <div className="mt-3 flex flex-wrap items-center gap-2">{actions}</div> : null}
    </aside>
  );
}
