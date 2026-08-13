import type { TenderQuery } from "./endpoints";

/**
 * Ключи запросов. Профиль в режиме одного пользователя один, но его id уже
 * входит в ключи (§9.10): при появлении многопользовательского режима кеш
 * не придётся переписывать.
 */
export const SINGLE_PROFILE_ID = "self";

export const qk = {
  tenders: {
    all: ["tenders"] as const,
    list: (params: TenderQuery) => ["tenders", "list", params] as const,
    search: (params: TenderQuery) => ["tenders", "search", params] as const,
    groups: (params: TenderQuery & { group: string }) =>
      ["tenders", "groups", params] as const,
    byId: (regNum: string) => ["tenders", "detail", regNum] as const,
    similar: (regNum: string) => ["tenders", "similar", regNum] as const,
    events: (regNum: string) => ["tenders", "events", regNum] as const,
  },
  documents: {
    text: (id: number) => ["docs", "text", id] as const,
    chunks: (id: number) => ["docs", "chunks", id] as const,
    download: (id: number) => ["docs", "download", id] as const,
  },
  filters: {
    all: ["filters"] as const,
    byId: (id: number) => ["filters", id] as const,
    compile: (query: string) => ["filters", "compile", query] as const,
  },
  jobs: (jobId: string) => ["jobs", jobId] as const,
  digest: (date: string) => ["digest", date] as const,
  digestDates: (from: string, to: string) => ["digest", "dates", from, to] as const,
  recs: (profileId: string, limit: number) => ["recs", profileId, limit] as const,
  profile: (profileId: string) => ["profile", profileId] as const,
  health: ["health"] as const,
  monitoring: {
    health: ["monitoring", "health"] as const,
    queues: ["monitoring", "queues"] as const,
    documents: ["monitoring", "documents"] as const,
  },
  crawlerRuns: (limit: number) => ["crawler", "runs", limit] as const,
  settings: ["settings"] as const,
} as const;

/**
 * Насколько долго данные считаются свежими. Каталог живёт минуту — выгрузка
 * идёт раз в час; текст документа не меняется никогда.
 */
export const STALE = {
  list: 60_000,
  detail: 5 * 60_000,
  documentText: Infinity,
  digestToday: 60_000,
  digestPast: Infinity,
  health: 15_000,
  profile: 30_000,
} as const;
