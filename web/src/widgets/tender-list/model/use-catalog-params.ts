"use client";

import {
  parseAsArrayOf,
  parseAsBoolean,
  parseAsFloat,
  parseAsInteger,
  parseAsString,
  useQueryStates,
} from "nuqs";
import type { TenderQuery } from "@/shared/api/endpoints";
import {
  parseCollapsed,
  parseGroup,
  parseSort,
  toApiSort,
  type SortKey,
} from "@/entities/tender/model/sort";

/**
 * Всё состояние списка живёт в адресной строке: вставленная ссылка
 * воспроизводит ровно тот же экран. Аналитик пересылает ссылки коллегам —
 * это требование, а не удобство.
 *
 * Значения по умолчанию сериализуются в пустоту: без условий адрес — просто
 * `/tenders`.
 */
export const catalogParsers = {
  q: parseAsString.withDefault(""),
  region: parseAsArrayOf(parseAsString, ",").withDefault([]),
  okpd2: parseAsString.withDefault(""),
  customer_inn: parseAsString.withDefault(""),
  price_min: parseAsFloat,
  price_max: parseAsFloat,
  since: parseAsString.withDefault(""),
  until: parseAsString.withDefault(""),
  only_active: parseAsBoolean.withDefault(false),
  deadline_changed: parseAsBoolean.withDefault(false),
  // «Распознан текст» — про наличие текста, а не про статус обработки
  // вложений: они расходятся в обе стороны.
  has_text: parseAsBoolean.withDefault(false),
  filter_id: parseAsInteger,
  /**
   * Сортировка и группировка живут в адресе как есть, строками: разбирает их
   * реестр (`entities/tender/model/sort.ts`), а не парсер nuqs. Иначе
   * добавление поля пришлось бы дублировать в двух местах, а устаревшая
   * закладка с неизвестным полем ловилась бы литеральным парсером как ошибка
   * вместо мягкого отката к умолчанию.
   */
  sort: parseAsString.withDefault(""),
  group: parseAsString.withDefault(""),
  /** Свёрнутые группы: `okpd:32.50,okpd:41.20`. */
  collapsed: parseAsString.withDefault(""),
  page: parseAsInteger.withDefault(0),
  /** Открытая карточка в панели-инспекторе. */
  preview: parseAsString.withDefault(""),
};

export function useCatalogParams() {
  return useQueryStates(catalogParsers, { history: "push", clearOnDefault: true });
}

export type CatalogParams = ReturnType<typeof useCatalogParams>[0];

/** Разобранное состояние порядка: то, что читают контрол и запрос. */
export function catalogSort(params: CatalogParams): {
  keys: SortKey[];
  group: string | null;
  collapsed: Set<string>;
} {
  const keys = parseSort(params.sort, { q: params.q });

  return {
    keys,
    // Группировка и релевантность противоречат друг другу: порядок по
    // категории и порядок по близости к запросу — разные порядки. Контрол
    // говорит об этом словами, а здесь группировка просто не применяется.
    group: keys[0]?.field === "relevance" ? null : parseGroup(params.group),
    collapsed: parseCollapsed(params.collapsed),
  };
}

const PAGE_SIZE = 50;

/** Параметры экрана → параметры запроса. Пустые значения не уходят в API. */
export function toTenderQuery(params: CatalogParams): TenderQuery & { q?: string } {
  const query: TenderQuery = { page: params.page, page_size: PAGE_SIZE };

  // Порядок считает сервер по всей выборке. Ключ группы уходит первым, добор
  // по id — последним; и то и другое собирает реестр, а не это место.
  const { keys, group } = catalogSort(params);
  query.sort = toApiSort(keys, group);

  if (params.q) query.q = params.q;
  if (params.region.length) query.region = params.region;
  if (params.okpd2) query.okpd2 = params.okpd2;
  if (params.customer_inn) query.customer_inn = params.customer_inn;
  if (params.price_min !== null) query.price_min = params.price_min;
  if (params.price_max !== null) query.price_max = params.price_max;
  if (params.since) query.since = params.since;
  if (params.until) query.until = params.until;
  if (params.only_active) query.only_active = true;
  if (params.deadline_changed) query.deadline_changed = true;
  if (params.has_text) query.has_text = true;
  if (params.filter_id !== null) query.filter_id = params.filter_id;

  return query;
}

export { PAGE_SIZE };
