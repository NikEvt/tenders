import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ResearchRunView } from "@/widgets/research/ui/research-run";
import { ru } from "@/shared/i18n/ru";

export const metadata: Metadata = { title: ru.research.title };

export default async function ResearchRunPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const runId = Number(id);
  if (!Number.isFinite(runId)) notFound();

  return <ResearchRunView runId={runId} />;
}
