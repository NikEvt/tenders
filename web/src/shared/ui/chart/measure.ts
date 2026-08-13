/**
 * Измерение ширины текста через canvas: без вставки узлов в документ и без
 * `getBBox`. Разница принципиальная — `getBBox` заставляет браузер считать
 * layout синхронно, а шкал в виртуализированном списке шестьдесят.
 */

const cache = new Map<string, number>();

let context: CanvasRenderingContext2D | null | undefined;

function measureContext(): CanvasRenderingContext2D | null {
  if (context !== undefined) return context;
  try {
    context = document.createElement("canvas").getContext("2d");
  } catch {
    // SSR или окружение без canvas (jsdom без пакета `canvas`).
    context = null;
  }
  return context;
}

/**
 * Детерминированная замена измерению.
 *
 * Тесты и серверный рендер обязаны получать одну и ту же раскладку, поэтому
 * там ширина считается по формуле, а не по метрикам шрифта.
 */
export const stubMeasurer = (text: string): number => text.length * 6.2;

/**
 * Измеритель для конкретного шрифта.
 *
 * @param font значение CSS-свойства `font`, например `500 12px 'Golos Text'`.
 */
export function makeMeasurer(font: string): (text: string) => number {
  return (text: string) => {
    const key = `${font}|${text}`;
    const hit = cache.get(key);
    if (hit !== undefined) return hit;

    const ctx = measureContext();
    const width = ctx ? ((ctx.font = font), ctx.measureText(text).width) : stubMeasurer(text);

    cache.set(key, width);
    return width;
  };
}

/**
 * Сброс кеша.
 *
 * Вызывается после `document.fonts.ready`: до загрузки веб-шрифта измерения
 * сняты с подменного начертания и врут — именно поэтому наложение появлялось
 * только после жёсткой перезагрузки.
 */
export function clearMeasureCache(): void {
  cache.clear();
}
