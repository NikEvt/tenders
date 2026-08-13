import type { components, paths } from "./schema";

export type Tender = components["schemas"]["TenderOut"];
export type TenderPage = components["schemas"]["PageOut"];
export type TenderDetail = components["schemas"]["TenderDetailOut"];
export type TenderDocument = components["schemas"]["DocumentOut"];
export type DownloadLink = components["schemas"]["DownloadOut"];
export type Facets = components["schemas"]["FacetsOut"];
export type TenderGroups = components["schemas"]["GroupsOut"];
export type GroupBucket = components["schemas"]["GroupBucketOut"];
export type FacetBucket = components["schemas"]["FacetBucketOut"];
export type PriceBucket = components["schemas"]["PriceBucketOut"];
export type RestrictiveHint = components["schemas"]["RestrictiveHintOut"];
export type SimilarTenders = components["schemas"]["SimilarOut"];
export type DigestDates = components["schemas"]["DigestDatesOut"];
export type Filter = components["schemas"]["FilterOut"];
export type MatchCount = components["schemas"]["MatchCountOut"];
export type DocumentChunks = components["schemas"]["DocumentChunksOut"];
export type ChunkOutline = components["schemas"]["ChunkOutlineOut"];
export type Fragment = components["schemas"]["FragmentOut"];
export type FragmentPage = components["schemas"]["FragmentPageOut"];
export type SearchMode = "lexical" | "semantic" | "rrf";
/** Перечень приходит из OpenAPI: неверное значение перестаёт компилироваться. */
export type DocumentsStatus = NonNullable<
  NonNullable<paths["/tenders"]["get"]["parameters"]["query"]>["documents_status"]
>;
export type ServicesHealth = components["schemas"]["HealthOut"];
export type ServiceHealth = components["schemas"]["ServiceHealthOut"];
export type Queues = components["schemas"]["QueuesOut"];
export type CrawlerRuns = components["schemas"]["CrawlerRunsOut"];
export type DocumentPipeline = components["schemas"]["DocumentPipelineOut"];
export type TenderEvents = components["schemas"]["TenderEventsOut"];
export type Settings = components["schemas"]["SettingsOut"];
export type RatingHistory = components["schemas"]["RatingHistoryOut"];
export type ProfileWins = components["schemas"]["WinsOut"];

/**
 * Ниже — формы, которые API отдаёт как «свободный» dict: FastAPI не описывает
 * их в схеме, поэтому типы объявлены здесь вручную и сверены с исходниками
 * llm-service и recsys-service. Это не выдуманный контракт, а зеркало кода:
 * services/llm_service/domain/models.py и services/recsys_service/domain/models.py.
 */

/** llm-service: FilterSpec — результат компиляции свободного текста. */
export type FilterSpec = {
  keywords: string[];
  okpd2_prefixes: string[];
  price_min: number | string | null;
  price_max: number | string | null;
  regions: string[];
  customer_inns: string[];
  date_range: { since?: string | null; until?: string | null } | null;
  only_active: boolean;
  semantic_query: string;
  llm_criteria: string;
};

/** POST /filters/compile -> { spec } */
export type CompileResult = { spec: FilterSpec };

/** POST /filters -> { filter_id, spec } */
export type SavedFilter = { filter_id: number; spec: FilterSpec };

/** Воронка пробного прогона: GET /jobs/{id}.result при kind="filter_test". */
export type FilterFunnel = {
  total: number;
  after_structural: number;
  after_semantic: number;
  after_judge: number;
};

export type FilterTestResult = {
  funnel?: FilterFunnel;
  dropped?: { structural: number[]; semantic: number[]; judge: number[] };
  /** Отсеянных на первом этапе могут быть тысячи — в ответе выборка. */
  dropped_truncated?: boolean;
};

/** POST /filters/{id}/run, POST /digest/{date} -> { job_id } */
export type JobAccepted = { job_id: string };

/** GET /jobs/{id} */
export type Job = {
  job_id: string;
  kind: string;
  status: "pending" | "running" | "done" | "failed" | string;
  total: number | null;
  processed: number | null;
  result: Record<string, unknown> | null;
  error: string | null;
  updated_at: string;
};

/** GET /digest/{date} */
export type Digest = {
  digest_date: string;
  summary_md: string;
  sections: DigestSections;
  tender_count: number;
  model: string;
  generated_at: string;
};

export type DigestSections = {
  /** map-шаг: резюме по каждой категории. Ключ — категория. */
  clusters?: Record<string, string>;
  top?: { reg_num: string; name: string | null; price: string | null }[];
  /** Сейчас только реестровые номера — см. docs/API-GAPS.md §12. */
  deadline_changes?: string[];
  /** Сейчас только названия — см. docs/API-GAPS.md §12. */
  new_customers?: string[];
  total?: number;
};

/** GET /recommendations */
export type Recommendation = {
  tender_id: number;
  reg_num: string;
  name: string | null;
  description: string | null;
  price: number | string | null;
  customer_name: string | null;
  okpd2_code: string | null;
  end_date: string | null;
  score: number;
  explanation: RecommendationExplanation;
};

export type RecommendationExplanation = {
  reasons: string[];
  factors: Record<string, number>;
  exploration: boolean;
};

/** GET /profile */
export type Profile = {
  signal_count: number;
  has_embedding: boolean;
  okpd2_weights: Record<string, number>;
  price_stats: Record<string, number>;
  is_usable: boolean;
};

/** Элемент вердикта в TenderDetailOut.verdicts (llm_verdicts). */
export type Verdict = {
  filter_id: number;
  match: boolean | null;
  score: number | null;
  reasoning: string | null;
  evidence: Evidence[] | null;
};

export type Evidence = {
  document_id: number | null;
  chunk_id: number | null;
  page: number | null;
  quote?: string | null;
};

export type DocumentText = {
  document_id: number;
  content: string;
  char_count: number;
};

export type FeedbackSignal = "like" | "dislike" | "hide" | "shortlist";
