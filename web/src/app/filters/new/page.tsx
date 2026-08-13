import type { Metadata } from "next";
import { ru } from "@/shared/i18n/ru";
import { FilterBuilder } from "@/widgets/filter-builder/ui/filter-builder";

export const metadata: Metadata = { title: ru.filters.builderTitle };

export default function NewFilterPage() {
  return <FilterBuilder />;
}
