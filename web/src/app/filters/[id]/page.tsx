import type { Metadata } from "next";
import { PageHeader } from "@/shared/ui/section";
import { FilterCard } from "@/widgets/filter-list/ui/filter-card";
import { ru } from "@/shared/i18n/ru";

export const metadata: Metadata = { title: ru.filters.title };

export default async function FilterPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const filterId = Number(id);

  if (!Number.isInteger(filterId)) {
    return <PageHeader title="Фильтр не найден" meta={`«${id}» — не идентификатор фильтра`} />;
  }

  return <FilterCard filterId={filterId} />;
}
