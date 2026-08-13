"use client";

import * as React from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Bookmark, ChevronRight, EyeOff, Inbox, SearchX, Sparkle } from "lucide-react";
import { Button } from "@/shared/ui/button";
import { Chip } from "@/shared/ui/chip";
import { EmptyState } from "@/shared/ui/empty-state";
import { ListSkeleton } from "@/shared/ui/skeleton";
import { Tooltip } from "@/shared/ui/tooltip";
import { useToast } from "@/shared/ui/toast";
import { ru } from "@/shared/i18n/ru";
import { cn } from "@/shared/lib/cn";
import { formatCount, withPlural } from "@/shared/lib/plural";
import { money } from "@/shared/lib/format";
import { useHotkeys } from "@/shared/lib/hooks";
import { endpoints } from "@/shared/api/endpoints";
import { qk, STALE } from "@/shared/api/query-keys";
import type { GroupBucket, Tender } from "@/shared/api/types";
import { TenderRow } from "@/entities/tender/ui/tender-row";
import { useRateTender } from "@/features/rate-tender/model/use-rate-tender";
import { downloadCsv } from "@/features/export-csv/lib/export-csv";
import { activeConditions } from "../model/active-conditions";
import { specToParams } from "../model/spec-to-params";
import { useRestrictiveCondition } from "../model/use-restrictive-condition";
import {
  serializeCollapsed,
  serializeSort,
  sortField,
} from "@/entities/tender/model/sort";
import {
  catalogSort,
  PAGE_SIZE,
  toTenderQuery,
  useCatalogParams,
} from "../model/use-catalog-params";
import {
  estimateSize,
  flattenGroups,
  groupHeading,
  HEADER_HEIGHT,
  type FlatItem,
} from "../model/flatten-groups";
import { SortControl } from "./sort-control";
import { Facets } from "./facets";
import { SearchBar } from "./search-bar";

const VIRTUALIZE_ABOVE = 60;

export function Catalog() {
  const [params, setParams] = useCatalogParams();
  const toast = useToast();
  const rate = useRateTender();
  const searchRef = React.useRef<HTMLInputElement>(null);
  const scrollRef = React.useRef<HTMLDivElement>(null);

  const [pages, setPages] = React.useState(1);
  const [focused, setFocused] = React.useState(0);
  const [selected, setSelected] = React.useState<Set<string>>(new Set());
  const [hidden, setHidden] = React.useState<Set<string>>(new Set());

  const query = toTenderQuery(params);
  const useSearch = Boolean(params.q && params.q.length >= 2);
  const { keys: sortKeys, group, collapsed } = catalogSort(params);

  // Страницы догружаются накопительно; ключ первой страницы — база кеша.
  const requests = React.useMemo(
    () => Array.from({ length: pages }, (_, index) => ({ ...query, page: index })),
    [query, pages],
  );

  const results = useQuery({
    queryKey: useSearch ? qk.tenders.search(requests[0]!) : qk.tenders.list(requests[0]!),
    queryFn: async ({ signal }) => {
      const responses = await Promise.all(
        requests.map((request) =>
          useSearch
            ? endpoints.searchTenders({ ...request, q: params.q }, signal)
            : endpoints.listTenders(request, signal),
        ),
      );
      const first = responses[0]!;
      return { ...first, items: responses.flatMap((response) => response.items) };
    },
    staleTime: STALE.list,
    placeholderData: (previous) => previous,
  });

  // Смена порядка или группировки обнуляет постраничность и прокрутку:
  // страницы, снятые при разной сортировке, склеивать нельзя — в списке
  // появились бы и повторы, и дыры.
  // Оглавление групп: счётчик и сумма по всей выдаче, а не по странице.
  // Запрашивается только когда группировка включена.
  const groups = useQuery({
    queryKey: qk.tenders.groups({ ...query, group: group ?? "" }),
    queryFn: ({ signal }) => endpoints.tenderGroups({ ...query, group: group! }, signal),
    enabled: group !== null,
    staleTime: STALE.list,
  });

  React.useEffect(() => {
    setPages(1);
    setFocused(0);
    scrollRef.current?.scrollTo({ top: 0 });
  }, [params.q, params.region, params.okpd2, params.price_min, params.price_max, params.since, params.until, params.only_active, params.deadline_changed, params.has_text, params.filter_id, params.sort, params.group]);

  // Порядок приходит из API — на клиенте выдача только фильтруется от скрытых.
  const items = React.useMemo(
    () => (results.data?.items ?? []).filter((item) => !hidden.has(item.reg_num)),
    [results.data, hidden],
  );

  const total = results.data?.total ?? 0;
  const loadedAll = items.length >= total;
  const conditions = activeConditions(params);

  const restrictive = useRestrictiveCondition(
    params,
    !results.isLoading && total === 0 && conditions.length > 0,
  );

  const openPreview = React.useCallback(
    (tender: Tender) => setParams({ preview: tender.reg_num }),
    [setParams],
  );

  const rowAction = React.useCallback(
    (tender: Tender, kind: "shortlist" | "hide" | "similar") => {
      if (kind === "similar") {
        setParams({ okpd2: tender.okpd2_code ?? "", q: "", page: 0 });
        return;
      }
      if (kind === "hide") {
        setHidden((prev) => new Set(prev).add(tender.reg_num));
      }
      rate.mutate(
        { tenderId: tender.tender_id, signal: kind },
        {
          onSuccess: () =>
            toast.show({
              title: kind === "hide" ? ru.tender.hidden : ru.tender.inShortlist,
              tone: "moss",
              undo:
                kind === "hide"
                  ? () =>
                      setHidden((prev) => {
                        const next = new Set(prev);
                        next.delete(tender.reg_num);
                        return next;
                      })
                  : undefined,
            }),
          onError: () => {
            setHidden((prev) => {
              const next = new Set(prev);
              next.delete(tender.reg_num);
              return next;
            });
            toast.show({ title: ru.feedback.failed, tone: "signal" });
          },
        },
      );
    },
    [rate, setParams, toast],
  );

  useHotkeys([
    { combo: "/", handler: () => searchRef.current?.focus() },
    { combo: "j", handler: () => setFocused((i) => Math.min(i + 1, items.length - 1)) },
    { combo: "k", handler: () => setFocused((i) => Math.max(i - 1, 0)) },
    {
      combo: "enter",
      handler: () => {
        const tender = items[focused];
        if (tender) openPreview(tender);
      },
    },
    {
      combo: "shift+enter",
      handler: () => {
        const tender = items[focused];
        if (tender) window.open(`/tenders/${tender.reg_num}`, "_blank", "noopener");
      },
    },
    {
      combo: "f",
      handler: () => {
        const tender = items[focused];
        if (tender) rowAction(tender, "shortlist");
      },
    },
    {
      combo: "h",
      handler: () => {
        const tender = items[focused];
        if (tender) rowAction(tender, "hide");
      },
    },
    {
      combo: "s",
      handler: () => {
        const tender = items[focused];
        if (tender) rowAction(tender, "similar");
      },
    },
  ]);

  return (
    <div className="flex flex-col gap-5">
      <SearchBar
        inputRef={searchRef}
        value={params.q}
        onValueChange={(value) => setParams({ q: value, page: 0 })}
        onSubmit={(value) => setParams({ q: value, page: 0 })}
        onApplySpec={(spec) => setParams(specToParams(spec))}
      />

      <div className="flex items-start gap-6">
        <Facets params={params} onChange={setParams} layout="column" />

        <div className="flex min-w-0 flex-1 flex-col gap-4">
          <Facets params={params} onChange={setParams} layout="popovers" />

          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              {conditions.map((condition) => (
                <Chip
                  key={condition.id}
                  kind="structural"
                  onRemove={() => setParams(condition.clear)}
                  title={condition.label}
                >
                  {condition.label}
                </Chip>
              ))}
            </div>

            <SortControl
              keys={sortKeys}
              group={group}
              context={{ q: params.q }}
              onChange={(next) =>
                setParams({
                  sort: serializeSort(next.keys),
                  group: next.group ?? "",
                  // Свёрнутость относится к прежней группировке — при смене
                  // ключа она бессмысленна.
                  collapsed: next.group === group ? params.collapsed : "",
                  page: 0,
                })
              }
            />
          </div>

          {/* Освободившееся внимание уходит настоящему предмету страницы:
              не «⌘K» в шапке, а числу найденного и следующему шагу по нему. */}
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <p className="text-h3" aria-live="polite">
              {results.isLoading
                ? ru.app.loading
                : ru.catalog.found(0).replace("0", formatCount(total))}
            </p>
            {!results.isLoading && total > 0 ? (
              <>
                <span className="text-text-subtle" aria-hidden="true">
                  ·
                </span>
                <Link
                  href="/filters/new"
                  className="text-body-sm text-gos-fg underline-offset-2 hover:underline"
                >
                  {ru.catalog.saveAsFilter}
                </Link>
              </>
            ) : null}
            <span className="text-body-sm text-text-muted">· {ru.app.mskNote}</span>
          </div>

          <div className="overflow-hidden rounded-[10px] border border-hairline bg-surface">
            {results.isLoading ? (
              <ListSkeleton rows={8} />
            ) : items.length === 0 ? (
              <EmptyResult
                hasConditions={conditions.length > 0}
                restrictiveLabel={restrictive.data?.condition.label}
                restrictiveCount={restrictive.data?.withoutCount}
                onRelax={() =>
                  restrictive.data && setParams(restrictive.data.condition.clear)
                }
              />
            ) : (
              <Rows
                items={items}
                group={group}
                buckets={groups.data?.items ?? []}
                collapsed={collapsed}
                onToggleGroup={(id) => {
                  const next = new Set(collapsed);
                  if (!next.delete(id)) next.add(id);
                  setParams({ collapsed: serializeCollapsed(next) });
                }}
                focused={focused}
                onFocus={setFocused}
                previewId={params.preview}
                selected={selected}
                onSelectedChange={setSelected}
                onOpen={openPreview}
                onAction={rowAction}
                onCopy={() => toast.show({ title: ru.tender.regNumCopied })}
                scrollRef={scrollRef}
              />
            )}
          </div>

          {!loadedAll && items.length > 0 ? (
            <Button
              variant="secondary"
              className="self-center"
              loading={results.isFetching}
              onClick={() => setPages((n) => n + 1)}
            >
              {ru.common.showMore(Math.min(PAGE_SIZE, total - items.length))}
            </Button>
          ) : null}
        </div>
      </div>

      {selected.size > 0 ? (
        <BulkBar
          count={selected.size}
          onClear={() => setSelected(new Set())}
          onExport={() =>
            downloadCsv(
              items.filter((item) => selected.has(item.reg_num)),
              `zakupki-${new Date().toISOString().slice(0, 10)}.csv`,
            )
          }
          onHideAll={() => {
            items
              .filter((item) => selected.has(item.reg_num))
              .forEach((item) => rowAction(item, "hide"));
            setSelected(new Set());
          }}
          compareHref={`/tenders/compare?ids=${[...selected].join(",")}`}
        />
      ) : null}
    </div>
  );
}

function Rows({
  items,
  group,
  buckets,
  collapsed,
  onToggleGroup,
  focused,
  onFocus,
  previewId,
  selected,
  onSelectedChange,
  onOpen,
  onAction,
  onCopy,
  scrollRef,
}: {
  items: Tender[];
  group: string | null;
  buckets: GroupBucket[];
  collapsed: Set<string>;
  onToggleGroup: (id: string) => void;
  focused: number;
  onFocus: (index: number) => void;
  previewId: string;
  selected: Set<string>;
  onSelectedChange: (next: Set<string>) => void;
  onOpen: (tender: Tender) => void;
  onAction: (tender: Tender, kind: "shortlist" | "hide" | "similar") => void;
  onCopy: () => void;
  scrollRef: React.RefObject<HTMLDivElement | null>;
}) {
  /**
   * Один плоский список и один виртуализатор. Шапки — такие же элементы, как
   * строки, только другой высоты: вложенные виртуализаторы дали бы по
   * скроллеру на группу, а группа бывает длиннее экрана.
   */
  const flat = React.useMemo<FlatItem[]>(
    () =>
      group
        ? flattenGroups(items, group, buckets, collapsed)
        : items.map((tender) => ({ kind: "row", id: tender.reg_num, groupKey: "", tender })),
    [items, group, buckets, collapsed],
  );

  /**
   * Клавиши j/k ходят по закупкам, а не по шапкам, поэтому нужны обе
   * трансляции: порядковый номер закупки → индекс в плоском списке и обратно.
   * Обе считаются один раз: искать `indexOf` на каждый видимый элемент — это
   * скан всего списка на кадр прокрутки, а список бывает в тысячи строк.
   */
  const { rowIndexes, positionOf } = React.useMemo(() => {
    const indexes: number[] = [];
    const positions = new Int32Array(flat.length).fill(-1);
    flat.forEach((item, index) => {
      if (item.kind !== "row") return;
      positions[index] = indexes.length;
      indexes.push(index);
    });
    return { rowIndexes: indexes, positionOf: positions };
  }, [flat]);

  const virtualize = flat.length > VIRTUALIZE_ABOVE;

  const virtualizer = useVirtualizer({
    count: flat.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: (index) => estimateSize(flat, index),
    overscan: 8,
    enabled: virtualize,
  });

  React.useEffect(() => {
    const index = rowIndexes[focused];
    if (virtualize && index !== undefined) virtualizer.scrollToIndex(index, { align: "auto" });
  }, [focused, rowIndexes, virtualize, virtualizer]);

  const renderItem = (item: FlatItem, index: number) => {
    if (item.kind === "header") {
      return (
        <GroupHeader
          key={item.id}
          field={group!}
          header={item}
          onToggle={() => onToggleGroup(item.id)}
        />
      );
    }
    // Порядковый номер закупки среди закупок — от него зависит фокус.
    return renderRow(item.tender, positionOf[index] ?? 0);
  };

  const renderRow = (tender: Tender, index: number) => (
    <TenderRow
      key={tender.reg_num}
      tender={tender}
      href={`/tenders/${tender.reg_num}`}
      onOpen={(item) => {
        onFocus(index);
        onOpen(item);
      }}
      active={previewId === tender.reg_num}
      focused={focused === index}
      selected={selected.has(tender.reg_num)}
      onSelectedChange={(checked) => {
        const next = new Set(selected);
        if (checked) next.add(tender.reg_num);
        else next.delete(tender.reg_num);
        onSelectedChange(next);
      }}
      onCopyRegNum={onCopy}
      actions={<RowActions tender={tender} onAction={onAction} />}
    />
  );

  if (!virtualize) {
    return <ul className="flex flex-col">{flat.map(renderItem)}</ul>;
  }

  return (
    <div ref={scrollRef} className="max-h-[calc(100dvh-320px)] overflow-y-auto">
      <ul className="relative" style={{ height: virtualizer.getTotalSize() }}>
        {virtualizer.getVirtualItems().map((virtualRow) => {
          const item = flat[virtualRow.index];
          if (!item) return null;
          return (
            <div
              key={item.id}
              className="absolute inset-x-0 top-0"
              style={{ transform: `translateY(${virtualRow.start}px)` }}
            >
              {renderItem(item, virtualRow.index)}
            </div>
          );
        })}
      </ul>
    </div>
  );
}

/** Шапка группы: категория, счётчик по всей выдаче, сумма НМЦК, шеврон. */
function GroupHeader({
  field,
  header,
  onToggle,
}: {
  field: string;
  header: Extract<FlatItem, { kind: "header" }>;
  onToggle: () => void;
}) {
  const label = sortField(field)?.groupLabel ?? field;

  return (
    <li
      className="sticky top-0 z-10 border-b border-hairline bg-surface-sunken"
      style={{ height: HEADER_HEIGHT }}
    >
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={!header.collapsed}
        aria-label={`${header.collapsed ? ru.catalog.group.expand : ru.catalog.group.collapse}: ${label} ${header.groupKey}`}
        className="flex h-full w-full items-center gap-2 px-4 text-left hover:bg-hairline"
      >
        <ChevronRight
          className={cn(
            "h-4 w-4 shrink-0 text-text-muted transition-transform duration-(--dur-state)",
            !header.collapsed && "rotate-90",
          )}
          strokeWidth={1.5}
          aria-hidden="true"
        />
        <span className="min-w-0 flex-1 truncate text-body-sm font-medium">
          {header.groupKey ? groupHeading(field, header) : ru.catalog.group.empty}
        </span>
        <span className="shrink-0 tnum text-caption text-text-muted">
          {withPlural(header.count, ["закупка", "закупки", "закупок"])}
        </span>
        {header.totalPrice !== null ? (
          <span className="shrink-0 tnum text-caption text-text-muted">
            · {ru.catalog.group.total(money(header.totalPrice))}
          </span>
        ) : null}
      </button>
    </li>
  );
}

function RowActions({
  tender,
  onAction,
}: {
  tender: Tender;
  onAction: (tender: Tender, kind: "shortlist" | "hide" | "similar") => void;
}) {
  return (
    <>
      <Tooltip content={ru.tender.addToShortlist} shortcut="f">
        <Button
          size="icon-sm"
          variant="ghost"
          aria-label={ru.tender.addToShortlist}
          onClick={() => onAction(tender, "shortlist")}
        >
          <Bookmark className="h-4 w-4" strokeWidth={1.5} />
        </Button>
      </Tooltip>
      <Tooltip content={ru.tender.hide} shortcut="h">
        <Button
          size="icon-sm"
          variant="ghost"
          aria-label={ru.tender.hide}
          onClick={() => onAction(tender, "hide")}
        >
          <EyeOff className="h-4 w-4" strokeWidth={1.5} />
        </Button>
      </Tooltip>
      <Tooltip content={ru.tender.similar} shortcut="s">
        <Button
          size="icon-sm"
          variant="ghost"
          aria-label={ru.tender.similar}
          onClick={() => onAction(tender, "similar")}
        >
          <Sparkle className="h-4 w-4" strokeWidth={1.5} />
        </Button>
      </Tooltip>
    </>
  );
}

function EmptyResult({
  hasConditions,
  restrictiveLabel,
  restrictiveCount,
  onRelax,
}: {
  hasConditions: boolean;
  restrictiveLabel?: string;
  restrictiveCount?: number;
  onRelax: () => void;
}) {
  if (!hasConditions) {
    return (
      <EmptyState
        icon={<Inbox strokeWidth={1.5} />}
        title={ru.catalog.noDataTitle}
        body={ru.catalog.noDataBody}
        action={
          <Button asChild variant="primary">
            <Link href="/monitoring/crawler">{ru.catalog.noDataAction}</Link>
          </Button>
        }
      />
    );
  }

  return (
    <EmptyState
      icon={<SearchX strokeWidth={1.5} />}
      title={ru.catalog.emptyTitle}
      body={
        <>
          {restrictiveLabel && restrictiveCount
            ? ru.catalog.emptyRestrictive(
                restrictiveLabel,
                withPlural(restrictiveCount, ["закупка", "закупки", "закупок"]),
              )
            : ru.catalog.emptyGeneric}
          <span className="mt-1 block text-text-muted">{ru.catalog.emptyPalette}</span>
        </>
      }
      action={
        restrictiveLabel ? (
          <Button variant="primary" onClick={onRelax}>
            {ru.catalog.removeCondition}: {restrictiveLabel}
          </Button>
        ) : null
      }
    />
  );
}

function BulkBar({
  count,
  onClear,
  onExport,
  onHideAll,
  compareHref,
}: {
  count: number;
  onClear: () => void;
  onExport: () => void;
  onHideAll: () => void;
  compareHref: string;
}) {
  return (
    <div
      className={cn(
        "sticky bottom-4 z-30 mx-auto flex items-center gap-3 rounded-[14px] border border-hairline",
        "bg-surface px-4 py-3 shadow-(--shadow-overlay)",
      )}
    >
      <span className="text-body-sm font-medium">{ru.catalog.bulk.selected(count)}</span>
      <Button size="sm" variant="secondary" asChild>
        <Link href={compareHref}>{ru.catalog.bulk.compare}</Link>
      </Button>
      <Button size="sm" variant="secondary" onClick={onExport}>
        {ru.catalog.bulk.exportCsv}
      </Button>
      <Button size="sm" variant="ghost" onClick={onHideAll}>
        {ru.catalog.bulk.hideAll}
      </Button>
      <Button size="sm" variant="quiet" onClick={onClear}>
        {ru.catalog.bulk.clear}
      </Button>
    </div>
  );
}

