"use client";

import { useSyncExternalStore } from "react";

/**
 * Реестр идущих операций.
 *
 * Раньше идентификатор задания жил в `useState` того виджета, который его
 * запустил. Уход со страницы размонтировал виджет — и опрос прекращался вместе
 * с ним: аналитик запускал часовой прогон, шёл в каталог, и с этого момента
 * интерфейс никак не показывал, что машина занята. Бриф §7.4 п.5 требует
 * обратного, и держать обещание может только хранилище вне дерева.
 *
 * Зеркалится в `localStorage`, потому что перезагрузка страницы — это тот же
 * уход, только полный.
 */

export type TrackedJob = {
  jobId: string;
  /** Что запустили — строка для человека, не `kind` из базы. */
  title: string;
  /** Куда идти за результатом. */
  href: string;
  startedAt: number;
};

const STORAGE_KEY = "zakupki:jobs";

/**
 * Дольше суток не живёт ничто.
 *
 * Задание, о котором сервер давно забыл (база пересоздана, а `localStorage`
 * пережил), иначе опрашивалось бы вечно — по разу в пять секунд, до конца
 * времён.
 */
const MAX_AGE_MS = 24 * 60 * 60 * 1000;

let state: TrackedJob[] = [];
const listeners = new Set<() => void>();

function emit(next: TrackedJob[]) {
  state = next;
  persist(next);
  listeners.forEach((listener) => listener());
}

function persist(jobs: TrackedJob[]) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(jobs));
  } catch {
    // Приватный режим — реестр живёт до перезагрузки. Это хуже, но работает.
  }
}

function readStorage(now: number): TrackedJob[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (item): item is TrackedJob =>
        typeof item === "object" &&
        item !== null &&
        typeof (item as TrackedJob).jobId === "string" &&
        typeof (item as TrackedJob).startedAt === "number" &&
        now - (item as TrackedJob).startedAt < MAX_AGE_MS,
    );
  } catch {
    // Испорченное значение — начинаем с пустого реестра, а не падаем.
    return [];
  }
}

export const jobRegistry = {
  /** Начать следить. Повторный вызов с тем же id ничего не портит. */
  track(job: Omit<TrackedJob, "startedAt"> & { startedAt?: number }) {
    if (state.some((tracked) => tracked.jobId === job.jobId)) return;
    emit([...state, { ...job, startedAt: job.startedAt ?? Date.now() }]);
  },

  /**
   * Перестать следить: операция закончилась, упала или её вовсе нет на сервере.
   * Последнее — не крайний случай, а обычный: реестр переживает пересоздание
   * базы, и без выселения по 404 он опрашивал бы призрака вечно.
   */
  forget(jobId: string) {
    if (!state.some((tracked) => tracked.jobId === jobId)) return;
    emit(state.filter((tracked) => tracked.jobId !== jobId));
  },

  /** Поднять реестр из хранилища. Зовётся один раз, из каркаса приложения. */
  hydrate(now: number = Date.now()) {
    emit(readStorage(now));
  },

  subscribe(listener: () => void) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },

  snapshot(): TrackedJob[] {
    return state;
  },

  /** Только для тестов: вернуть хранилище в исходное состояние. */
  reset() {
    state = [];
    listeners.clear();
  },
};

const SERVER_STATE: TrackedJob[] = [];

export function useTrackedJobs(): TrackedJob[] {
  return useSyncExternalStore(jobRegistry.subscribe, jobRegistry.snapshot, () => SERVER_STATE);
}
