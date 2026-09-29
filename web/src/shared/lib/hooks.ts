"use client";

import * as React from "react";

/**
 * Глобальные горячие клавиши. Не срабатывают, когда пользователь печатает,
 * и не перехватывают браузерные сочетания без явного requestDefault: false.
 */
export type Hotkey = {
  /** `k`, `Ctrl+k`, `Shift+Enter`, `g d` (последовательность). */
  combo: string;
  handler: (event: KeyboardEvent) => void;
  /** Разрешить срабатывание внутри полей ввода. */
  inInputs?: boolean;
  enabled?: boolean;
};

const SEQUENCE_TIMEOUT_MS = 900;

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return (
    target.tagName === "INPUT" ||
    target.tagName === "TEXTAREA" ||
    target.tagName === "SELECT" ||
    target.isContentEditable
  );
}

function matches(event: KeyboardEvent, combo: string): boolean {
  const parts = combo.split("+").map((p) => p.trim().toLowerCase());
  const key = parts[parts.length - 1] ?? "";
  const needsCtrl = parts.includes("ctrl") || parts.includes("mod");
  const needsShift = parts.includes("shift");
  const needsAlt = parts.includes("alt");

  const ctrlHeld = event.ctrlKey || event.metaKey;
  if (needsCtrl !== ctrlHeld) return false;
  if (needsShift !== event.shiftKey) return false;
  if (needsAlt !== event.altKey) return false;

  return event.key.toLowerCase() === key || event.code.toLowerCase() === `key${key}`;
}

export function useHotkeys(hotkeys: Hotkey[]): void {
  const ref = React.useRef(hotkeys);
  ref.current = hotkeys;

  React.useEffect(() => {
    let pending: string | null = null;
    let timer: number | undefined;

    const onKeyDown = (event: KeyboardEvent) => {
      const typing = isTypingTarget(event.target);

      for (const hotkey of ref.current) {
        if (hotkey.enabled === false) continue;
        if (typing && !hotkey.inInputs) continue;

        const [first, second] = hotkey.combo.split(" ");
        if (second) {
          if (pending === first && matches(event, second)) {
            event.preventDefault();
            pending = null;
            hotkey.handler(event);
            return;
          }
          continue;
        }

        if (matches(event, hotkey.combo)) {
          event.preventDefault();
          hotkey.handler(event);
          return;
        }
      }

      // Начало последовательности вида `g d`.
      const prefixes = ref.current
        .filter((h) => h.combo.includes(" ") && h.enabled !== false)
        .map((h) => h.combo.split(" ")[0]);
      if (!typing && prefixes.includes(event.key.toLowerCase())) {
        pending = event.key.toLowerCase();
        window.clearTimeout(timer);
        timer = window.setTimeout(() => (pending = null), SEQUENCE_TIMEOUT_MS);
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.clearTimeout(timer);
    };
  }, []);
}

export function useLocalStorage<T>(key: string, initial: T): [T, (value: T) => void] {
  const [value, setValue] = React.useState<T>(initial);

  React.useEffect(() => {
    try {
      const raw = window.localStorage.getItem(key);
      if (raw !== null) setValue(JSON.parse(raw) as T);
    } catch {
      // Приватный режим или испорченное значение — работаем со значением по умолчанию.
    }
  }, [key]);

  const write = React.useCallback(
    (next: T) => {
      setValue(next);
      try {
        window.localStorage.setItem(key, JSON.stringify(next));
      } catch {
        // Записать некуда — состояние живёт только в этой вкладке.
      }
    },
    [key],
  );

  return [value, write];
}

export function useMediaQuery(query: string): boolean {
  const [matched, setMatched] = React.useState(false);

  React.useEffect(() => {
    const list = window.matchMedia(query);
    const update = () => setMatched(list.matches);
    update();
    list.addEventListener("change", update);
    return () => list.removeEventListener("change", update);
  }, [query]);

  return matched;
}

export function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = React.useState(value);

  React.useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delayMs);
    return () => window.clearTimeout(timer);
  }, [value, delayMs]);

  return debounced;
}

/* --------------------------------------------------------- ширина элемента */

/**
 * Один `ResizeObserver` на всё приложение.
 *
 * В списке из шестидесяти строк у каждой своя шкала сроков; шестьдесят
 * наблюдателей — это шестьдесят подписок и шестьдесят колбэков на каждый
 * кадр перетаскивания границы панели. Здесь наблюдатель один, а рассылка
 * склеена до одного кадра анимации.
 */
type WidthListener = (width: number) => void;

const widthListeners = new Map<Element, WidthListener>();
const pendingWidths = new Map<Element, number>();
let sharedObserver: ResizeObserver | null = null;
let flushHandle = 0;

function widthObserver(): ResizeObserver | null {
  if (sharedObserver || typeof ResizeObserver === "undefined") return sharedObserver;

  sharedObserver = new ResizeObserver((entries) => {
    for (const entry of entries) pendingWidths.set(entry.target, entry.contentRect.width);
    if (flushHandle) return;

    flushHandle = requestAnimationFrame(() => {
      flushHandle = 0;
      const batch = [...pendingWidths];
      pendingWidths.clear();
      for (const [element, width] of batch) widthListeners.get(element)?.(width);
    });
  });

  return sharedObserver;
}

/**
 * Ширина элемента, обновляемая не чаще кадра.
 *
 * `fallback` — что вернуть до первого измерения: на сервере и в первом
 * рендере элемента ещё нет, а раскладке подписей ширина нужна сразу.
 */
export function useElementWidth(
  ref: React.RefObject<HTMLElement | null>,
  fallback: number,
): number {
  const [width, setWidth] = React.useState(fallback);

  React.useEffect(() => {
    const element = ref.current;
    const observer = widthObserver();
    if (!element || !observer) return;

    setWidth(Math.round(element.getBoundingClientRect().width) || fallback);
    widthListeners.set(element, (next) => setWidth(Math.round(next)));
    observer.observe(element);

    return () => {
      observer.unobserve(element);
      widthListeners.delete(element);
      pendingWidths.delete(element);
    };
  }, [ref, fallback]);

  return width;
}

/** Первая отрисовка за сегодня — для однократной анимации сводки (§2.8). */
export function useFirstVisitToday(key: string): boolean {
  const [first, setFirst] = React.useState(false);

  React.useEffect(() => {
    const today = new Date().toISOString().slice(0, 10);
    try {
      if (window.localStorage.getItem(key) !== today) {
        window.localStorage.setItem(key, today);
        setFirst(true);
      }
    } catch {
      // Без localStorage анимация просто не проигрывается — это не потеря.
    }
  }, [key]);

  return first;
}

/**
 * Часы ожидания: сколько миллисекунд прошло с `startedAt`, с шагом в секунду.
 *
 * Отдельный хук, потому что ожиданий в интерфейсе два вида — с заданием и без
 * него, — а подпись «идёт 1 мин 20 с» в обоих обязана идти сама. Опрос
 * задания идёт раз в пять секунд, и без собственного тика подпись дёргалась бы
 * пятисекундными скачками, то есть выглядела бы подвисшей ровно там, где
 * доказывает обратное.
 *
 * `running: false` останавливает часы: считать время после завершения незачем.
 */
export function useElapsed(startedAt: number | null, running: boolean): number {
  const [now, setNow] = React.useState(() => Date.now());

  React.useEffect(() => {
    if (!running || startedAt === null) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [running, startedAt]);

  return startedAt === null ? 0 : Math.max(0, now - startedAt);
}
