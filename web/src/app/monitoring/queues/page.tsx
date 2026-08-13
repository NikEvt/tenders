import type { Metadata } from "next";
import { PageHeader } from "@/shared/ui/section";
import { ServiceHealthGrid } from "@/widgets/service-health/ui/service-health-grid";
import { ru } from "@/shared/i18n/ru";

export const metadata: Metadata = { title: ru.monitoring.queues };

export default function QueuesPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={ru.monitoring.queues} />
      <ServiceHealthGrid />
    </div>
  );
}
