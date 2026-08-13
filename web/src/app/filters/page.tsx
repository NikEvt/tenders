import type { Metadata } from "next";
import Link from "next/link";
import { Button } from "@/shared/ui/button";
import { PageHeader } from "@/shared/ui/section";
import { FilterList } from "@/widgets/filter-list/ui/filter-list";
import { ru } from "@/shared/i18n/ru";

export const metadata: Metadata = { title: ru.filters.title };

export default function FiltersPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={ru.filters.title}
        actions={
          <Button asChild variant="primary">
            <Link href="/filters/new">{ru.filters.newFilter}</Link>
          </Button>
        }
      />
      <FilterList />
    </div>
  );
}
