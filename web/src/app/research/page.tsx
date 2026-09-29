import type { Metadata } from "next";
import { PageHeader } from "@/shared/ui/section";
import { RunResearchForm } from "@/features/run-research/ui/run-research-form";
import { ResearchRuns } from "@/widgets/research/ui/research-runs";
import { ru } from "@/shared/i18n/ru";

export const metadata: Metadata = { title: ru.research.title };

/**
 * Страница исследований. Форма запуска стоит здесь, а не только в карточке
 * фильтра: сюда приходят с намерением «хочу провести исследование», и
 * отсылать за этим в другое место — то, чем страница занималась раньше.
 */
export default function ResearchPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={ru.research.title} />
      <RunResearchForm />
      <ResearchRuns />
    </div>
  );
}
