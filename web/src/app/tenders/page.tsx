import type { Metadata } from "next";
import { Suspense } from "react";
import { PageHeader } from "@/shared/ui/section";
import { ListSkeleton } from "@/shared/ui/skeleton";
import { ru } from "@/shared/i18n/ru";
import { Catalog } from "@/widgets/tender-list/ui/catalog";
import { InspectorSlot } from "@/widgets/tender-inspector/ui/inspector-slot";

export const metadata: Metadata = { title: ru.catalog.title };

export default function TendersPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={ru.catalog.title} />
      <Suspense fallback={<ListSkeleton rows={10} />}>
        <Catalog />
        {/* Инспектор — сосед списка, а не его часть: связывает их только ?preview= */}
        <InspectorSlot />
      </Suspense>
    </div>
  );
}
