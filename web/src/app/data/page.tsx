import type { Metadata } from "next";
import { Suspense } from "react";
import { TextSkeleton } from "@/shared/ui/skeleton";
import { ru } from "@/shared/i18n/ru";
import { DataOverview } from "@/widgets/data-overview/ui/data-overview";

export const metadata: Metadata = { title: ru.data.title };

export default function DataPage() {
  // Период живёт в URL (nuqs), поэтому виджет читает параметры запроса —
  // при пререндере это требует границы ожидания, как на каталоге и поиске.
  return (
    <Suspense fallback={<TextSkeleton lines={10} />}>
      <DataOverview />
    </Suspense>
  );
}
