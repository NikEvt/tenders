"use client";

import Link from "next/link";
import { useQueries } from "@tanstack/react-query";
import { parseAsArrayOf, parseAsString, useQueryState } from "nuqs";
import { Columns3 } from "lucide-react";
import { Button } from "@/shared/ui/button";
import { EmptyState } from "@/shared/ui/empty-state";
import { TextSkeleton } from "@/shared/ui/skeleton";
import { Rail } from "@/shared/ui/rail/rail";
import { CopyableMono } from "@/shared/ui/mono";
import { ru } from "@/shared/i18n/ru";
import { dateShort, money, regionName, toDate } from "@/shared/lib/format";
import { endpoints } from "@/shared/api/endpoints";
import { qk, STALE } from "@/shared/api/query-keys";
import { StatusPill } from "@/entities/tender/ui/status-pill";

const MAX_COMPARED = 4;

/** Сравнение 2–4 закупок: строки — поля, колонки — закупки. */
export function CompareTable() {
  const [ids] = useQueryState("ids", parseAsArrayOf(parseAsString, ",").withDefault([]));
  const regNums = ids.slice(0, MAX_COMPARED);

  const queries = useQueries({
    queries: regNums.map((regNum) => ({
      queryKey: qk.tenders.byId(regNum),
      queryFn: ({ signal }: { signal: AbortSignal }) => endpoints.getTender(regNum, signal),
      staleTime: STALE.detail,
    })),
  });

  if (regNums.length === 0) {
    return (
      <EmptyState
        icon={<Columns3 strokeWidth={1.5} />}
        title="Нечего сравнивать"
        body="Отметьте от двух до четырёх закупок в каталоге и нажмите «Сравнить»."
        action={
          <Button asChild variant="primary">
            <Link href="/tenders">{ru.catalog.title}</Link>
          </Button>
        }
      />
    );
  }

  if (queries.some((query) => query.isLoading)) return <TextSkeleton lines={10} />;

  const tenders = queries.map((query) => query.data?.tender).filter(Boolean);

  const rows: { label: string; render: (index: number) => React.ReactNode }[] = [
    {
      label: ru.tender.price,
      render: (i) => (
        <span className="font-mono tnum">{money(tenders[i]?.price)}</span>
      ),
    },
    { label: ru.tender.customer, render: (i) => tenders[i]?.customer_name ?? "—" },
    {
      label: ru.tender.inn,
      render: (i) => <span className="font-mono tnum">{tenders[i]?.customer_inn ?? "—"}</span>,
    },
    {
      label: ru.tender.okpd2,
      render: (i) => <span className="font-mono tnum">{tenders[i]?.okpd2_code ?? "—"}</span>,
    },
    { label: ru.tender.region, render: (i) => regionName(tenders[i]?.region_code) },
    { label: ru.tender.published, render: (i) => dateShort(tenders[i]?.publish_date) },
    { label: ru.tender.deadline, render: (i) => dateShort(tenders[i]?.end_date) },
    {
      label: ru.tender.documentCount,
      render: (i) => <span className="tnum">{tenders[i]?.document_count ?? 0}</span>,
    },
    {
      label: "Сроки",
      render: (i) => {
        const tender = tenders[i];
        if (!tender) return "—";
        return (
          <Rail
            published={toDate(tender.publish_date)}
            start={toDate(tender.start_date)}
            deadline={toDate(tender.end_date)}
            previousDeadline={tender.deadline_changed ? toDate(tender.prev_end_date) : null}
            scale="micro"
          />
        );
      },
    },
  ];

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-body-sm">
        <thead>
          <tr>
            <th className="w-44" />
            {tenders.map((tender) => (
              <th key={tender!.reg_num} scope="col" className="min-w-64 border-b border-hairline p-3 text-left align-top">
                <StatusPill dates={tender!} />
                <Link
                  href={`/tenders/${tender!.reg_num}`}
                  className="clamp-2 mt-2 block text-body font-medium text-text no-underline hover:text-gos-fg"
                >
                  {tender!.name ?? tender!.reg_num}
                </Link>
                <CopyableMono value={tender!.reg_num} label={ru.tender.regNum} />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.label} className="border-b border-hairline">
              <th scope="row" className="p-3 text-left align-middle text-caption uppercase text-text-muted">
                {row.label}
              </th>
              {tenders.map((tender, index) => (
                <td key={tender!.reg_num} className="p-3 align-middle">
                  {row.render(index)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
