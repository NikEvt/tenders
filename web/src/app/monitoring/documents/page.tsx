import type { Metadata } from "next";
import { PageHeader } from "@/shared/ui/section";
import { DocumentPipelineFunnel } from "@/widgets/document-pipeline/ui/document-pipeline";
import { ru } from "@/shared/i18n/ru";

export const metadata: Metadata = { title: ru.monitoring.documentsPipeline };

export default function DocumentsPipelinePage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={ru.monitoring.documentsPipeline} />
      <DocumentPipelineFunnel />
    </div>
  );
}
