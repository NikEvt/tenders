"use client";

import * as React from "react";
import { clearMeasureCache, makeMeasurer } from "./measure";

/**
 * Измеритель, который знает про загрузку веб-шрифта.
 *
 * С `font-display: swap` первая раскладка считается по метрикам подменного
 * начертания. Golos Text шире системного — подписи, разведённые «по запасному
 * шрифту», после подмены налезают друг на друга. Отсюда и жалоба «съезжает
 * только после жёсткой перезагрузки»: при тёплом кеше шрифт успевает
 * приехать до первого измерения, при холодном — нет.
 *
 * Кеш сбрасывается ВНУТРИ колбэка `fonts.ready`, до `setState`. Сделать это
 * эффектом нельзя: эффект отработает уже после перерисовки, и та посчитается
 * по старым, «подменным» ширинам.
 */
export function useMeasurer(font: string): (text: string) => number {
  // Значение счётчика никого не интересует — важен сам факт перерисовки после
  // подмены шрифта. Кеш к этому моменту уже сброшен, а измеритель читает его
  // лениво, поэтому пересоздавать саму функцию не нужно.
  const [, setGeneration] = React.useState(0);

  React.useEffect(() => {
    const fonts = typeof document === "undefined" ? undefined : document.fonts;
    if (!fonts || fonts.status === "loaded") return;

    let cancelled = false;
    void fonts.ready.then(() => {
      if (cancelled) return;
      clearMeasureCache();
      setGeneration((value) => value + 1);
    });

    return () => {
      cancelled = true;
    };
  }, []);

  return React.useMemo(() => makeMeasurer(font), [font]);
}
