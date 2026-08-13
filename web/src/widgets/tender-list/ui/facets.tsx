"use client";

import * as React from "react";
import { ChevronDown } from "lucide-react";
import { Button } from "@/shared/ui/button";
import { Checkbox, Field, Input, Label } from "@/shared/ui/field";
import { Popover, PopoverContent, PopoverTrigger } from "@/shared/ui/popover";
import { Tooltip } from "@/shared/ui/tooltip";
import { ru } from "@/shared/i18n/ru";
import { REGIONS } from "@/shared/lib/format";
import { cn } from "@/shared/lib/cn";
import { useQuery } from "@tanstack/react-query";
import { endpoints } from "@/shared/api/endpoints";
import { formatCount } from "@/shared/lib/format";
import type { Facets as FacetCounts } from "@/shared/api/types";
import type { CatalogParams } from "../model/use-catalog-params";
import { toTenderQuery } from "../model/use-catalog-params";

export type FacetsProps = {
  params: CatalogParams;
  onChange: (patch: Partial<CatalogParams>) => void;
  /** Колонкой на широком экране, поповерами — на остальных. */
  layout: "column" | "popovers";
};

/**
 * Счётчики считаются по всей выдаче запроса, а не по загруженной странице:
 * `GET /tenders/facets` принимает те же условия, что и список.
 */
function useFacetCounts(params: CatalogParams) {
  return useQuery<FacetCounts>({
    queryKey: ["tenders", "facets", toTenderQuery(params)],
    staleTime: 60_000,
    queryFn: ({ signal }) => endpoints.tenderFacets(toTenderQuery(params), signal),
  });
}

/** Счётчик рядом с пунктом фасета. Пока не приехал — места не занимает. */
function Count({ value }: { value: number | undefined }) {
  if (value === undefined) return null;
  return <span className="ml-auto tnum text-caption text-text-subtle">{formatCount(value)}</span>;
}

export function Facets({ params, onChange, layout }: FacetsProps) {
  const counts = useFacetCounts(params);
  const byRegion = new Map(counts.data?.regions.map((b) => [b.key, b.count]));
  if (layout === "column") {
    return (
      <aside className="hidden w-70 shrink-0 flex-col gap-6 2xl:flex" aria-label={ru.catalog.conditions}>
        <RegionFacet params={params} onChange={onChange} counts={byRegion} />
        <PriceFacet params={params} onChange={onChange} />
        <Okpd2Facet params={params} onChange={onChange} />
        <DateFacet params={params} onChange={onChange} />
        <FlagsFacet params={params} onChange={onChange} />
        <LawFacet />
      </aside>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2 2xl:hidden">
      <FacetPopover label={ru.catalog.facets.region} active={params.region.length > 0}>
        <RegionFacet params={params} onChange={onChange} counts={byRegion} />
      </FacetPopover>
      <FacetPopover
        label={ru.catalog.facets.price}
        active={params.price_min !== null || params.price_max !== null}
      >
        <PriceFacet params={params} onChange={onChange} />
      </FacetPopover>
      <FacetPopover label={ru.catalog.facets.okpd2} active={Boolean(params.okpd2)}>
        <Okpd2Facet params={params} onChange={onChange} />
      </FacetPopover>
      <FacetPopover
        label={ru.catalog.facets.published}
        active={Boolean(params.since || params.until)}
      >
        <DateFacet params={params} onChange={onChange} />
      </FacetPopover>
      <FacetPopover
        label={ru.common.more}
        active={params.only_active || params.deadline_changed || params.has_text}
      >
        <FlagsFacet params={params} onChange={onChange} />
        <LawFacet className="mt-4" />
      </FacetPopover>
    </div>
  );
}

function FacetPopover({
  label,
  active,
  children,
}: {
  label: string;
  active: boolean;
  children: React.ReactNode;
}) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          size="sm"
          variant={active ? "primary" : "secondary"}
          icon={<ChevronDown className="h-4 w-4" strokeWidth={1.5} />}
        >
          {label}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80">{children}</PopoverContent>
    </Popover>
  );
}

function FacetBlock({
  title,
  children,
  hint,
}: {
  title: string;
  children: React.ReactNode;
  hint?: string;
}) {
  return (
    <section className="flex flex-col gap-2">
      <h3 className="text-caption uppercase text-text-muted">{title}</h3>
      {children}
      {hint ? <p className="text-body-sm text-text-subtle">{hint}</p> : null}
    </section>
  );
}

function RegionFacet({
  params,
  onChange,
  counts,
}: Omit<FacetsProps, "layout"> & { counts: Map<string, number> }) {
  return (
    <FacetBlock title={ru.catalog.facets.region}>
      <ul className="flex max-h-64 flex-col gap-1 overflow-y-auto">
        {Object.entries(REGIONS).map(([code, name]) => {
          const checked = params.region.includes(code);
          return (
            <li key={code}>
              <label className="flex cursor-pointer items-center gap-2 rounded-[6px] px-1 py-1 text-body-sm hover:bg-surface-sunken">
                <Checkbox
                  checked={checked}
                  onChange={(event) =>
                    onChange({
                      region: event.target.checked
                        ? [...params.region, code]
                        : params.region.filter((r) => r !== code),
                      page: 0,
                    })
                  }
                />
                {name}
                <Count value={counts.get(code)} />
              </label>
            </li>
          );
        })}
      </ul>
    </FacetBlock>
  );
}

function PriceFacet({ params, onChange }: Omit<FacetsProps, "layout">) {
  return (
    <FacetBlock title={ru.catalog.facets.price}>
      <div className="flex items-center gap-2">
        <Input
          type="number"
          inputMode="numeric"
          placeholder={ru.catalog.facets.from}
          aria-label={`${ru.catalog.facets.price} ${ru.catalog.facets.from}`}
          value={params.price_min ?? ""}
          onChange={(event) =>
            onChange({ price_min: event.target.value ? Number(event.target.value) : null, page: 0 })
          }
          className="tnum"
        />
        <span className="text-text-subtle">—</span>
        <Input
          type="number"
          inputMode="numeric"
          placeholder={ru.catalog.facets.to}
          aria-label={`${ru.catalog.facets.price} ${ru.catalog.facets.to}`}
          value={params.price_max ?? ""}
          onChange={(event) =>
            onChange({ price_max: event.target.value ? Number(event.target.value) : null, page: 0 })
          }
          className="tnum"
        />
      </div>
    </FacetBlock>
  );
}

function Okpd2Facet({ params, onChange }: Omit<FacetsProps, "layout">) {
  return (
    <FacetBlock title={ru.catalog.facets.okpd2} hint="Префикс кода: 32.50 найдёт всю группу.">
      <Input
        value={params.okpd2}
        placeholder="32.50"
        aria-label={ru.catalog.facets.okpd2}
        onChange={(event) => onChange({ okpd2: event.target.value, page: 0 })}
        className="font-mono tnum"
      />
    </FacetBlock>
  );
}

function DateFacet({ params, onChange }: Omit<FacetsProps, "layout">) {
  return (
    <FacetBlock title={ru.catalog.facets.published}>
      <div className="flex flex-col gap-2">
        <Field label={ru.catalog.facets.from} htmlFor="since">
          <Input
            id="since"
            type="date"
            value={params.since}
            onChange={(event) => onChange({ since: event.target.value, page: 0 })}
          />
        </Field>
        <Field label={ru.catalog.facets.to} htmlFor="until">
          <Input
            id="until"
            type="date"
            value={params.until}
            onChange={(event) => onChange({ until: event.target.value, page: 0 })}
          />
        </Field>
      </div>
    </FacetBlock>
  );
}

function FlagsFacet({ params, onChange }: Omit<FacetsProps, "layout">) {
  return (
    <FacetBlock title={ru.common.more}>
      <label className="flex cursor-pointer items-center gap-2 text-body-sm">
        <Checkbox
          checked={params.only_active}
          onChange={(event) => onChange({ only_active: event.target.checked, page: 0 })}
        />
        {ru.catalog.facets.onlyActive}
      </label>
      <label className="flex cursor-pointer items-center gap-2 text-body-sm">
        <Checkbox
          checked={params.deadline_changed}
          onChange={(event) => onChange({ deadline_changed: event.target.checked, page: 0 })}
        />
        {ru.catalog.facets.deadlineChanged}
      </label>
      <label className="flex cursor-pointer items-center gap-2 text-body-sm">
        <Checkbox
          checked={params.has_text}
          onChange={(event) =>
            onChange({ has_text: event.target.checked, page: 0 })
          }
        />
        {ru.catalog.facets.hasText}
      </label>
    </FacetBlock>
  );
}

/** 223-ФЗ не поддерживается — и об этом сказано прямо, а не умолчанием. */
function LawFacet({ className }: { className?: string }) {
  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <Label>Закон</Label>
      <div className="flex items-center gap-2">
        <Button size="sm" variant="primary" disabled className="opacity-100">
          44-ФЗ
        </Button>
        <Tooltip content={ru.common.lawUnsupported}>
          <span>
            <Button size="sm" variant="secondary" disabled>
              223-ФЗ
            </Button>
          </span>
        </Tooltip>
      </div>
    </div>
  );
}
