import type { Metadata } from "next";
import { PageHeader } from "@/shared/ui/section";
import { ru } from "@/shared/i18n/ru";
import { RecommendationFeed } from "@/widgets/recommendation-feed/ui/recommendation-feed";

export const metadata: Metadata = { title: ru.recommendations.title };

export default function RecommendationsPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={ru.recommendations.title} meta={ru.recommendations.explorationNote} />
      <RecommendationFeed />
    </div>
  );
}
