/**
 * Реестр сортировок каталога.
 *
 * Новое поле — один объект в `SORT_FIELDS` и ноль правок в интерфейсе:
 * ни один компонент не перечисляет сортировки руками, все читают реестр.
 * Направление тоже живёт здесь — словами, а не стрелкой: «↑» на «по
 * заказчику» не значит ничего, «А → Я» значит.
 */

export type SortDir = "asc" | "desc";

export type SortGroup = "relevance" | "money" | "dates" | "categories";

/** Контекст доступности: релевантности без запроса не существует. */
export type SortContext = { q?: string };

export interface SortField {
  id: string;
  /** «по сроку подачи» */
  label: string;
  group: SortGroup;
  /** Имя поля в API. Совпадает с `id` не всегда и не обязано. */
  apiField: string;
  /** deadline → asc, price → desc. */
  defaultDir: SortDir;
  /** «сначала ближайшие» / «сначала дальние» */
  dirLabels: Record<SortDir, string>;
  availableWhen?: (context: SortContext) => boolean;
  /** Можно ли по этому полю ещё и группировать (§4.3). */
  groupable?: boolean;
  /** Подпись поля в шапке группы: «ОКПД2», «Заказчик». */
  groupLabel?: string;
}

export const SORT_GROUP_LABELS: Record<SortGroup, string> = {
  relevance: "Соответствие",
  dates: "Даты",
  money: "Цена",
  categories: "Категории",
};

/** Порядок групп в выпадающем списке — порядок этого массива. */
export const SORT_GROUP_ORDER: readonly SortGroup[] = [
  "relevance",
  "dates",
  "money",
  "categories",
];

export const SORT_FIELDS: readonly SortField[] = [
  {
    id: "relevance",
    group: "relevance",
    label: "по релевантности",
    apiField: "relevance",
    defaultDir: "desc",
    dirLabels: { desc: "сначала точные", asc: "сначала неточные" },
    availableWhen: (context) => Boolean(context.q?.trim()),
  },
  {
    id: "deadline",
    group: "dates",
    label: "по сроку подачи",
    apiField: "deadline",
    defaultDir: "asc",
    dirLabels: { asc: "сначала ближайшие", desc: "сначала дальние" },
  },
  {
    id: "published",
    group: "dates",
    label: "по дате публикации",
    apiField: "published",
    defaultDir: "desc",
    dirLabels: { desc: "сначала новые", asc: "сначала старые" },
  },
  {
    id: "price",
    group: "money",
    label: "по начальной цене",
    apiField: "price",
    defaultDir: "desc",
    dirLabels: { desc: "сначала дорогие", asc: "сначала дешёвые" },
  },
  {
    id: "okpd",
    group: "categories",
    label: "по ОКПД2",
    apiField: "okpd",
    defaultDir: "asc",
    dirLabels: { asc: "по возрастанию кода", desc: "по убыванию кода" },
    groupable: true,
    groupLabel: "ОКПД2",
  },
  {
    id: "customer",
    group: "categories",
    label: "по заказчику",
    apiField: "customer",
    defaultDir: "asc",
    dirLabels: { asc: "А → Я", desc: "Я → А" },
    groupable: true,
    groupLabel: "Заказчик",
  },
  {
    id: "region",
    group: "categories",
    label: "по региону",
    apiField: "region",
    defaultDir: "asc",
    // В `tenders` лежит код субъекта, не название: порядок — по коду, и
    // подпись обязана говорить об этом прямо. См. docs/API-GAPS.md.
    dirLabels: { asc: "по возрастанию кода", desc: "по убыванию кода" },
    groupable: true,
    groupLabel: "Регион",
  },
];

const BY_ID = new Map(SORT_FIELDS.map((field) => [field.id, field]));

export function sortField(id: string): SortField | undefined {
  return BY_ID.get(id);
}

export const GROUPABLE_FIELDS = SORT_FIELDS.filter((field) => field.groupable);

/**
 * Ключ, по которому реально сортируется страница.
 *
 * Стабильный доборный ключ. Без него курсорная постраничность на полях с
 * малым числом значений — регион, статус — начинает дублировать и терять
 * строки: у сотни закупок одинаковый `region_code`, и порядок внутри пачки
 * между запросами не сохраняется. Вылезает это на третьей странице и
 * отлаживается мучительно.
 */
export const TIE_BREAK: SortKey = { field: "id", dir: "asc" };

export type SortKey = { field: string; dir: SortDir };

export const DEFAULT_SORT: SortKey = { field: "relevance", dir: "desc" };
/** Чем заменяем сортировку, которая в текущем контексте недоступна. */
export const FALLBACK_SORT: SortKey = { field: "published", dir: "desc" };

export function isAvailable(field: SortField, context: SortContext): boolean {
  return field.availableWhen ? field.availableWhen(context) : true;
}

/** Направление по умолчанию для поля — применяется при смене поля. */
export function defaultKey(id: string): SortKey {
  const field = sortField(id);
  return field ? { field: field.id, dir: field.defaultDir } : DEFAULT_SORT;
}

/* ------------------------------------------------------------------ URL */

const DIRS: readonly SortDir[] = ["asc", "desc"];

function parseKey(raw: string): SortKey | null {
  const [id, dir] = raw.split(":");
  const field = id ? sortField(id.trim()) : undefined;
  if (!field) return null;

  const direction = dir?.trim() as SortDir | undefined;
  // Неизвестное направление — не ошибка адреса, а повод взять умолчание поля.
  return { field: field.id, dir: direction && DIRS.includes(direction) ? direction : field.defaultDir };
}

/**
 * Разбор `?sort=okpd:asc,price:desc`.
 *
 * Принимает сколько угодно ключей — интерфейс сегодня пишет один, но формат
 * готов к нескольким с первого дня. Неизвестные поля отбрасываются, пустая
 * или полностью непонятная строка даёт сортировку по умолчанию: устаревшая
 * закладка обязана открыть каталог, а не страницу ошибки.
 */
export function parseSort(raw: string | null | undefined, context: SortContext = {}): SortKey[] {
  const keys = (raw ?? "")
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean)
    .map(parseKey)
    .filter((key): key is SortKey => key !== null)
    .filter((key) => key.field !== TIE_BREAK.field);

  // Дубликаты поля бессмысленны: второй ключ по тому же полю ничего не решает.
  const seen = new Set<string>();
  const unique = keys.filter((key) => !seen.has(key.field) && seen.add(key.field));

  const usable = unique.filter((key) => {
    const field = sortField(key.field);
    return field ? isAvailable(field, context) : false;
  });

  if (usable.length > 0) return usable;
  return [isAvailable(sortField(DEFAULT_SORT.field)!, context) ? DEFAULT_SORT : FALLBACK_SORT];
}

export function serializeSort(keys: readonly SortKey[]): string {
  return keys.map((key) => `${key.field}:${key.dir}`).join(",");
}

/** Разбор `?group=customer`. Не группируемое поле игнорируется. */
export function parseGroup(raw: string | null | undefined): string | null {
  const id = (raw ?? "").trim();
  const field = id ? sortField(id) : undefined;
  return field?.groupable ? field.id : null;
}

/**
 * Группировка и сортировка — один запрос, а не перегруппировка загруженной
 * страницы: ключ группы становится главным ключом порядка на сервере.
 * Доборный ключ дописывается всегда и последним.
 */
export function requestSort(keys: readonly SortKey[], group: string | null): SortKey[] {
  const groupField = group ? sortField(group) : undefined;
  const head: SortKey[] =
    groupField?.groupable ? [{ field: groupField.id, dir: groupField.defaultDir }] : [];

  const rest = keys.filter((key) => key.field !== head[0]?.field);
  return [...head, ...rest, TIE_BREAK];
}

/** Строка сортировки для API — с группой впереди и доборным ключом в конце. */
export function toApiSort(keys: readonly SortKey[], group: string | null): string {
  return requestSort(keys, group)
    .map((key) => {
      const field = sortField(key.field);
      return `${field ? field.apiField : key.field}:${key.dir}`;
    })
    .join(",");
}

/* ------------------------------------------------- свёрнутые группы в URL */

/** `?collapsed=okpd:32.50,okpd:41.20` → множество ключей групп. */
export function parseCollapsed(raw: string | null | undefined): Set<string> {
  return new Set(
    (raw ?? "")
      .split(",")
      .map((part) => part.trim())
      .filter(Boolean),
  );
}

export function serializeCollapsed(collapsed: ReadonlySet<string>): string {
  return [...collapsed].sort().join(",");
}

/* ------------------------------------------------------------- подписи */

/** «по сроку подачи · сначала ближайшие» — состояние словами, для кнопки. */
export function describeSort(keys: readonly SortKey[]): string {
  return keys
    .map((key) => {
      const field = sortField(key.field);
      return field ? `${field.label} · ${field.dirLabels[key.dir]}` : key.field;
    })
    .join(" · ");
}
