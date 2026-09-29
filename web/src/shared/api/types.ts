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
export type CorpusOverview = components["schemas"]["CorpusOverviewOut"];
export type CorpusProcessing = components["schemas"]["CorpusProcessingOut"];
export type DayBucket = components["schemas"]["DayBucketOut"];
export type Distribution = components["schemas"]["DistributionOut"];

/**
 * Ниже — формы, которые API отдаёт как «свободный» dict: FastAPI не описывает
 * их в схеме, поэтому типы объявлены здесь вручную и сверены с исходниками
 * llm-service и recsys-service. Это не выдуманный контракт, а зеркало кода:
 * services/llm_service/domain/models.py и services/recsys_service/domain/models.py.
 */

/**
 * llm-service: критерий отбора — результат компиляции свободного текста.
 * Зеркало `libs/shared/contracts/criteria_spec.py`.
 *
 * Сменил прежний `FilterSpec` (ключевые слова + семантический запрос +
 * критерий для судьи). Точность держится не на словах, а на правилах по
 * контексту, и вывести их из списка слов невозможно.
 */
export type TermRole = "primary" | "supporting";

export type Term = {
  name: string;
  /** Регулярное выражение, применяется без учёта регистра. */
  pattern: string;
  /**
   * `supporting` сам по себе не значит ничего: закупка, где сработали только
   * такие термины, отвергается целиком.
   */
  role: TermRole;
};

export type ContextRule = {
  name: string;
  pattern: string;
  verdict: "confirmed" | "rejected";
  /**
   * Сколько символов вокруг совпадения смотреть. У правил отказа окно узкое:
   * слова, выдающие название организации, стоят вплотную к совпадению.
   */
  window: number | null;
};

export type StructuralSpec = {
  regions: string[];
  customer_inns: string[];
  price_min: number | string | null;
  price_max: number | string | null;
  only_active: boolean;
};

export type CriteriaSpec = {
  name: string;
  terms: Term[];
  context_rules: ContextRule[];
  /** Предфильтр по карточке: сужает круг до закупок, где упоминание возможно. */
  card_pattern: string | null;
  okpd2_prefixes: string[];
  structural: StructuralSpec;
  version: string;
};

/** POST /filters/compile -> { spec } */
export type CompileResult = { spec: CriteriaSpec };

/** POST /filters -> { filter_id, spec } */
export type SavedFilter = { filter_id: number; spec: CriteriaSpec };

/**
 * Воронка прогона: GET /jobs/{id}.result.funnel.
 *
 * **Не каскад, а ветвление.** «Принято правилами» не является подмножеством
 * «отсеяно правилами» — рисовать их лестницей значило бы врать.
 *
 * `documents_pending` и `not_reached` — знаменатели, и они обязательны:
 * «находок нет» читается только рядом с «прочитано столько-то», а
 * «спорных 8, решено 5» — рядом с «до трёх не дошли».
 */
export type ResearchFunnel = {
  tenders_total: number;
  tenders_candidate: number;
  documents_scanned: number;
  /** Документы без извлечённого текста — до них не дошли. */
  documents_pending: number;
  hits_found: number;

  reviewed: number;
  rejected_by_rules: number;
  confirmed_by_rules: number;
  disputed: number;
  from_cache: number;
  asked_model: number;
  /** Модель легла на середине — остаток очереди не разобран. */
  not_reached: number;
  failed: number;
};

export type ResearchResult = {
  run_id?: number;
  matched?: number[];
  confirmed?: number;
  rejected?: number;
  /** Прогон оборван: модель перестала отвечать. */
  interrupted?: boolean;
  funnel?: ResearchFunnel;
};

/** POST /filters/{id}/run, POST /digest/{date} -> { job_id } */
export type JobAccepted = { job_id: string };

/**
 * GET /jobs/{id}
 *
 * Приезжает из схемы, а не пишется руками: по этому ответу рисуется шкала
 * ожидания, и расхождение с сервером здесь означает шкалу, которая врёт.
 * `total: null` — «объём фазы ещё не считали», и это не то же самое, что ноль.
 */
export type Job = components["schemas"]["JobOut"];

/** GET /digest/{date} */
export type Digest = {
  digest_date: string;
  summary_md: string;
  sections: DigestSections;
  tender_count: number;
  model: string;
  generated_at: string;
  /**
   * Собрана ли сводка после окончания своего дня.
   *
   * `false` — черновик: день ещё идёт, данные по нему доезжают, и `tender_count`
   * описывает не день, а то, что успело приехать к моменту сборки. Выдавать его
   * за итог нельзя — сводка за 13 августа так и осталась с 400 закупками из 4878.
   */
  final: boolean;
};

/** Область отбора: по каким фильтрам собрана сводка. */
export type DigestScope = {
  filters: string[];
  /** Включены в сводку, но ни разу не запускались — вердиктов у них нет. */
  unrun_filters: string[];
  filtered: boolean;
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
  scope?: DigestScope;
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

/**
 * Элемент вердикта в `TenderDetailOut.verdicts` — решение движка отбора.
 *
 * `decided_by` показывает, во что обошлось решение: правила по контексту
 * бесплатны, модель — нет. Скрывать это значит выдавать дешёвое решение за
 * работу модели и наоборот.
 */
export type Verdict = {
  criteria_version: string;
  confidence: "confirmed" | "rejected" | "disputed";
  reason: string | null;
  score: number | null;
  decided_by: "rules" | "model";
  /** Цитаты общие на закупку: вердикт ссылается на находки прогона. */
  hits: Evidence[] | null;
};

/** Цитата со смещением совпадения — то, что можно подсветить. */
export type Evidence = {
  term: string;
  quote: string;
  match_start: number;
  match_end: number;
  file_name: string | null;
  page: number | null;
};

export type DocumentText = {
  document_id: number;
  content: string;
  char_count: number;
};

export type FeedbackSignal = "like" | "dislike" | "hide" | "shortlist";

/** Исследования — эти формы шлюз описывает в OpenAPI. */
export type ResearchRun = components["schemas"]["ResearchRunOut"];
export type ResearchRunFunnel = components["schemas"]["ResearchFunnelOut"];
export type ResearchTender = components["schemas"]["ResearchTenderOut"];
export type ResearchTenders = components["schemas"]["ResearchTendersOut"];
export type ResearchHit = components["schemas"]["ResearchHitOut"];
export type Market = components["schemas"]["MarketOut"];
export type MarketBucket = components["schemas"]["MarketBucketOut"];
export type LoadLevel = components["schemas"]["LoadLevelOut"];
