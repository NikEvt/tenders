import { api, unwrap } from "./client";
import type {
  CompileResult,
  Digest,
  DigestDates,
  Facets,
  TenderGroups,
  CrawlerRuns,
  DocumentChunks,
  DocumentPipeline,
  DocumentsStatus,
  Filter,
  FilterSpec,
  FragmentPage,
  ProfileWins,
  Queues,
  RatingHistory,
  SearchMode,
  ServicesHealth,
  Settings,
  TenderEvents,
  DocumentText,
  DownloadLink,
  FeedbackSignal,
  Job,
  JobAccepted,
  Profile,
  Recommendation,
  SavedFilter,
  SimilarTenders,
  TenderDetail,
  TenderPage,
} from "./types";

/** Параметры каталога — ровно то, что принимает GET /tenders. */
export type TenderQuery = {
  q?: string;
  price_min?: number;
  price_max?: number;
  okpd2?: string;
  region?: string[];
  customer_inn?: string;
  since?: string;
  until?: string;
  only_active?: boolean;
  deadline_changed?: boolean;
  documents_status?: DocumentsStatus;
  has_text?: boolean;
  filter_id?: number;
  page?: number;
  page_size?: number;
  /**
   * Порядок выдачи — строка ключей `поле:направление` через запятую.
   * Считается сервером по всей выборке, а не по загруженным строкам.
   * Собирается реестром в `entities/tender/model/sort.ts`, руками не пишется.
   */
  sort?: string;
  order?: "asc" | "desc";
  /** Курсор последней строки. Задан — `page` игнорируется, в ответе `page` равен null. */
  cursor?: string;
  limit?: number;
};

type Signal = AbortSignal | undefined;

export const endpoints = {
  listTenders: (params: TenderQuery, signal?: Signal) =>
    unwrap<TenderPage>(
      "GET /tenders",
      (init) => api.GET("/tenders", { params: { query: params }, ...init }),
      signal,
    ),

  /** Гибридный поиск: лексика ⊕ вектор, в том числе по тексту документов. */
  searchTenders: (params: TenderQuery & { q: string }, signal?: Signal) =>
    unwrap<TenderPage>(
      "GET /tenders/search",
      (init) => api.GET("/tenders/search", { params: { query: params }, ...init }),
      signal,
    ),

  /** Оглавление сгруппированного списка: счётчик и сумма НМЦК на группу. */
  tenderGroups: (params: TenderQuery & { group: string }, signal?: Signal) =>
    unwrap<TenderGroups>(
      "GET /tenders/groups",
      (init) => api.GET("/tenders/groups", { params: { query: params }, ...init }),
      signal,
    ),

  /** Счётчики по всей выдаче запроса, а не по текущей странице. */
  tenderFacets: (
    params: TenderQuery & { explain_empty?: boolean },
    signal?: Signal,
  ) =>
    unwrap<Facets>(
      "GET /tenders/facets",
      (init) => api.GET("/tenders/facets", { params: { query: params }, ...init }),
      signal,
    ),

  similarTenders: (regNum: string, limit = 6, signal?: Signal) =>
    unwrap<SimilarTenders>(
      `GET /tenders/${regNum}/similar`,
      (init) =>
        api.GET("/tenders/{reg_num}/similar", {
          params: { path: { reg_num: regNum }, query: { limit } },
          ...init,
        }),
      signal,
    ),

  getTender: (regNum: string, signal?: Signal) =>
    unwrap<TenderDetail>(
      `GET /tenders/${regNum}`,
      (init) => api.GET("/tenders/{reg_num}", { params: { path: { reg_num: regNum } }, ...init }),
      signal,
    ),

  documentText: (documentId: number, signal?: Signal) =>
    unwrap<DocumentText>(
      `GET /documents/${documentId}/text`,
      (init) =>
        api.GET("/documents/{document_id}/text", {
          params: { path: { document_id: documentId } },
          ...init,
        }),
      signal,
    ),

  documentDownload: (documentId: number, signal?: Signal) =>
    unwrap<DownloadLink>(
      `GET /documents/${documentId}/download`,
      (init) =>
        api.GET("/documents/{document_id}/download", {
          params: { path: { document_id: documentId } },
          ...init,
        }),
      signal,
    ),

  /** Границы фрагментов: по ним цитата из вердикта резолвится до места в тексте. */
  documentChunks: (documentId: number, signal?: Signal) =>
    unwrap<DocumentChunks>(
      `GET /documents/${documentId}/chunks`,
      (init) =>
        api.GET("/documents/{document_id}/chunks", {
          params: { path: { document_id: documentId } },
          ...init,
        }),
      signal,
    ),

  /** Поиск по фрагментам документации: единица выдачи — фрагмент, а не закупка. */
  searchFragments: (
    params: { q: string; mode?: SearchMode; page?: number; page_size?: number },
    signal?: Signal,
  ) =>
    unwrap<FragmentPage>(
      "GET /search/fragments",
      (init) => api.GET("/search/fragments", { params: { query: params }, ...init }),
      signal,
    ),

  compileFilter: (query: string, signal?: Signal) =>
    unwrap<CompileResult>(
      "POST /filters/compile",
      (init) => api.POST("/filters/compile", { body: { query }, ...init }),
      signal,
    ),

  listFilters: (signal?: Signal) =>
    unwrap<Filter[]>("GET /filters", (init) => api.GET("/filters", init), signal),

  getFilter: (filterId: number, signal?: Signal) =>
    unwrap<Filter>(
      `GET /filters/${filterId}`,
      (init) =>
        api.GET("/filters/{filter_id}", {
          params: { path: { filter_id: filterId } },
          ...init,
        }),
      signal,
    ),

  /**
   * `spec` передаётся, когда пользователь правил условия в конструкторе:
   * без него сервер скомпилировал бы текст заново и правки бы потерялись.
   */
  saveFilter: (name: string, query: string, spec?: FilterSpec, signal?: Signal) =>
    unwrap<SavedFilter>(
      "POST /filters",
      (init) =>
        api.POST("/filters", {
          body: { name, query, ...(spec ? { spec: spec as unknown as Record<string, never> } : {}) },
          ...init,
        }),
      signal,
    ),

  patchFilter: (
    filterId: number,
    patch: { name?: string; in_digest?: boolean; notify?: boolean; is_active?: boolean },
  ) =>
    unwrap<Filter>(`PATCH /filters/${filterId}`, (init) =>
      api.PATCH("/filters/{filter_id}", {
        params: { path: { filter_id: filterId } },
        body: patch,
        ...init,
      }),
    ),

  deleteFilter: (filterId: number) =>
    unwrap<void>(`DELETE /filters/${filterId}`, (init) =>
      api.DELETE("/filters/{filter_id}", {
        params: { path: { filter_id: filterId } },
        ...init,
      }),
    ),

  duplicateFilter: (filterId: number) =>
    unwrap<Filter>(`POST /filters/${filterId}/duplicate`, (init) =>
      api.POST("/filters/{filter_id}/duplicate", {
        params: { path: { filter_id: filterId } },
        ...init,
      }),
    ),

  /** Пробный прогон: результат с воронкой приходит в GET /jobs/{id}. */
  testFilter: (filterId: number, days = 30) =>
    unwrap<JobAccepted>(`POST /filters/${filterId}/test`, (init) =>
      api.POST("/filters/{filter_id}/test", {
        params: { path: { filter_id: filterId } },
        body: { days },
        ...init,
      }),
    ),

  runFilter: (filterId: number, body: { since?: string; tender_ids?: number[] }, signal?: Signal) =>
    unwrap<JobAccepted>(
      `POST /filters/${filterId}/run`,
      (init) =>
        api.POST("/filters/{filter_id}/run", {
          params: { path: { filter_id: filterId } },
          body: { since: body.since ?? null, tender_ids: body.tender_ids ?? [] },
          ...init,
        }),
      signal,
    ),

  job: (jobId: string, signal?: Signal) =>
    unwrap<Job>(
      `GET /jobs/${jobId}`,
      (init) =>
        api.GET("/jobs/{job_id}", { params: { path: { job_id: jobId } }, ...init }),
      signal,
    ),

  digest: (date: string, signal?: Signal) =>
    unwrap<Digest>(
      `GET /digest/${date}`,
      (init) =>
        api.GET("/digest/{digest_date}", {
          params: { path: { digest_date: date } },
          ...init,
        }),
      signal,
    ),

  /** За какие дни сводка есть — точки в календаре. */
  digestDates: (from: string, to: string, signal?: Signal) =>
    unwrap<DigestDates>(
      "GET /digest",
      (init) => api.GET("/digest", { params: { query: { from, to } }, ...init }),
      signal,
    ),

  requestDigest: (date: string, force = false, signal?: Signal) =>
    unwrap<JobAccepted>(
      `POST /digest/${date}`,
      (init) =>
        api.POST("/digest/{digest_date}", {
          params: { path: { digest_date: date }, query: { force } },
          ...init,
        }),
      signal,
    ),

  recommendations: (limit: number, signal?: Signal) =>
    unwrap<Recommendation[]>(
      "GET /recommendations",
      (init) => api.GET("/recommendations", { params: { query: { limit } }, ...init }),
      signal,
    ),

  feedback: (tenderId: number, signal: FeedbackSignal, reason?: string) =>
    unwrap<Record<string, string>>("POST /feedback", (init) =>
      api.POST("/feedback", {
        body: { tender_id: tenderId, signal, reason: reason ?? null },
        ...init,
      }),
    ),

  view: (tenderId: number, dwellMs?: number) =>
    unwrap<Record<string, string>>("POST /views", (init) =>
      api.POST("/views", { body: { tender_id: tenderId, dwell_ms: dwellMs ?? null }, ...init }),
    ),

  win: (body: { tender_id: number; won_at?: string; contract_price?: number; notes?: string }) =>
    unwrap<Record<string, string>>("POST /wins", (init) =>
      api.POST("/wins", {
        body: {
          tender_id: body.tender_id,
          won_at: body.won_at ?? null,
          contract_price: body.contract_price ?? null,
          notes: body.notes ?? null,
        },
        ...init,
      }),
    ),

  profile: (signal?: Signal) =>
    unwrap<Profile>("GET /profile", (init) => api.GET("/profile", init), signal),

  tenderEvents: (regNum: string, signal?: Signal) =>
    unwrap<TenderEvents>(
      `GET /tenders/${regNum}/events`,
      (init) =>
        api.GET("/tenders/{reg_num}/events", {
          params: { path: { reg_num: regNum } },
          ...init,
        }),
      signal,
    ),

  /** Состояние сервисов одним ответом: браузер не ходит на шесть портов. */
  servicesHealth: (signal?: Signal) =>
    unwrap<ServicesHealth>(
      "GET /monitoring/health",
      (init) => api.GET("/monitoring/health", init),
      signal,
    ),

  queues: (signal?: Signal) =>
    unwrap<Queues>("GET /monitoring/queues", (init) => api.GET("/monitoring/queues", init), signal),

  retryDeadLetter: (messageId: string) =>
    unwrap<void>(`POST /monitoring/queues/dead-letters/${messageId}/retry`, (init) =>
      api.POST("/monitoring/queues/dead-letters/{message_id}/retry", {
        params: { path: { message_id: messageId } },
        ...init,
      }),
    ),

  crawlerRuns: (limit = 60, signal?: Signal) =>
    unwrap<CrawlerRuns>(
      "GET /monitoring/crawler/runs",
      (init) => api.GET("/monitoring/crawler/runs", { params: { query: { limit } }, ...init }),
      signal,
    ),

  documentPipeline: (signal?: Signal) =>
    unwrap<DocumentPipeline>(
      "GET /monitoring/documents",
      (init) => api.GET("/monitoring/documents", init),
      signal,
    ),

  settings: (signal?: Signal) =>
    unwrap<Settings>("GET /settings", (init) => api.GET("/settings", init), signal),

  confirmTokenRotation: () =>
    unwrap<void>("POST /settings/eis-token/rotated", (init) =>
      api.POST("/settings/eis-token/rotated", init),
    ),

  profileWeights: (signal?: Signal) =>
    unwrap<Record<string, unknown>[]>(
      "GET /profile/weights",
      (init) => api.GET("/profile/weights", init),
      signal,
    ),

  setProfileWeight: (key: string, weight: number | null, facet = "okpd2") =>
    unwrap<Record<string, unknown>[]>("PATCH /profile/weights", (init) =>
      api.PATCH("/profile/weights", { body: { facet, key, weight }, ...init }),
    ),

  profileRanker: (signal?: Signal) =>
    unwrap<{ kind: string; signals: number; threshold: number }>(
      "GET /profile/ranker",
      (init) => api.GET("/profile/ranker", init),
      signal,
    ),

  profileHistory: (page = 0, signal?: Signal) =>
    unwrap<RatingHistory>(
      "GET /profile/history",
      (init) => api.GET("/profile/history", { params: { query: { page } }, ...init }),
      signal,
    ),

  deleteRating: (signalId: number) =>
    unwrap<void>(`DELETE /profile/history/${signalId}`, (init) =>
      api.DELETE("/profile/history/{signal_id}", {
        params: { path: { signal_id: signalId } },
        ...init,
      }),
    ),

  profileWins: (signal?: Signal) =>
    unwrap<ProfileWins>("GET /profile/wins", (init) => api.GET("/profile/wins", init), signal),

  health: (signal?: Signal) =>
    unwrap<{ status: string }>("GET /health", (init) => api.GET("/health", init), signal),
} as const;
