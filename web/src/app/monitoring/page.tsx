import type { Metadata } from "next";
import Link from "next/link";
import { Button } from "@/shared/ui/button";
import { PageHeader } from "@/shared/ui/section";
import { ru } from "@/shared/i18n/ru";
import { ServiceHealthGrid } from "@/widgets/service-health/ui/service-health-grid";

export const metadata: Metadata = { title: ru.monitoring.title };

export default function MonitoringPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={ru.monitoring.title}
        actions={
          <>
            <Button asChild variant="secondary" size="sm">
              <Link href="/monitoring/crawler">{ru.monitoring.crawler}</Link>
            </Button>
            <Button asChild variant="secondary" size="sm">
              <Link href="/monitoring/queues">{ru.monitoring.queues}</Link>
            </Button>
            <Button asChild variant="secondary" size="sm">
              <Link href="/monitoring/documents">{ru.monitoring.documentsPipeline}</Link>
            </Button>
          </>
        }
      />
      <ServiceHealthGrid />
    </div>
  );
}
