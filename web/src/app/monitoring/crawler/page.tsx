import type { Metadata } from "next";
import { PageHeader } from "@/shared/ui/section";
import { CrawlerRunsTable } from "@/widgets/crawler-runs/ui/crawler-runs";
import { RefreshCrawlButton } from "@/features/request-crawl/ui/refresh-button";
import { ru } from "@/shared/i18n/ru";

export const metadata: Metadata = { title: ru.monitoring.crawler };

export default function CrawlerPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={ru.monitoring.crawler} />
      <RefreshCrawlButton />
      <CrawlerRunsTable />
    </div>
  );
}
