"use client";

import { useSyncExternalStore } from "react";

/**
 * Баннер деградации живёт на уровне сессии: он липкий, закрывается вручную и
 * возвращается на следующий деградированный ответ. Хранилище вне React —
 * сообщить о деградации может любой запрос, из любого места дерева.
 */
type State = { degraded: boolean; dismissed: boolean };

let state: State = { degraded: false, dismissed: false };
const listeners = new Set<() => void>();

function emit(next: State) {
  state = next;
  listeners.forEach((listener) => listener());
}

export const degradedStore = {
  report(degraded: boolean) {
    if (degraded && !state.degraded) emit({ degraded: true, dismissed: false });
    if (!degraded && state.degraded) emit({ degraded: false, dismissed: false });
  },
  dismiss() {
    emit({ ...state, dismissed: true });
  },
  subscribe(listener: () => void) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
  snapshot(): State {
    return state;
  },
};

const SERVER_STATE: State = { degraded: false, dismissed: false };

export function useDegraded(): State {
  return useSyncExternalStore(
    degradedStore.subscribe,
    degradedStore.snapshot,
    () => SERVER_STATE,
  );
}
