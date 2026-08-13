"use client";

import { useSyncExternalStore } from "react";

/**
 * Открытость командной строки — состояние уровня приложения.
 *
 * Хранилище вне React по той же причине, что и у баннера деградации: открыть
 * командную строку просят из мест, которые не лежат под её владельцем. Она
 * живёт в каркасе, а подсказка `⌘K` — внутри поля поиска на странице каталога;
 * протащить колбэк через слои каркаса нельзя, они не знают друг о друге.
 */
let open = false;
const listeners = new Set<() => void>();

function emit(next: boolean) {
  if (next === open) return;
  open = next;
  listeners.forEach((listener) => listener());
}

export const commandPalette = {
  open: () => emit(true),
  close: () => emit(false),
  toggle: () => emit(!open),
  setOpen: (next: boolean) => emit(next),
  subscribe(listener: () => void) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
  snapshot: () => open,
};

export function useCommandPaletteOpen(): boolean {
  return useSyncExternalStore(commandPalette.subscribe, commandPalette.snapshot, () => false);
}
