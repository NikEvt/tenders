import type { Metadata } from "next";
import { Suspense } from "react";
import { PageHeader } from "@/shared/ui/section";
import { TextSkeleton } from "@/shared/ui/skeleton";
import { ru } from "@/shared/i18n/ru";
import { FragmentSearch } from "@/widgets/fragment-search/ui/fragment-search";

export const metadata: Metadata = { title: ru.search.title };

export default function SearchPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={ru.search.title} meta={ru.search.subtitle} />
      <Suspense fallback={<TextSkeleton lines={8} />}>
        <FragmentSearch />
      </Suspense>
    </div>
  );
}
