import type { Metadata } from "next";
import { Suspense } from "react";
import { PageHeader } from "@/shared/ui/section";
import { TextSkeleton } from "@/shared/ui/skeleton";
import { CompareTable } from "@/widgets/tender-compare/ui/compare-table";

export const metadata: Metadata = { title: "Сравнение" };

export default function ComparePage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Сравнение" />
      <Suspense fallback={<TextSkeleton lines={8} />}>
        <CompareTable />
      </Suspense>
    </div>
  );
}
