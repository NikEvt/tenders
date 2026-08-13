import type { Metadata } from "next";
import { ru } from "@/shared/i18n/ru";
import { TenderCard } from "@/widgets/tender-card/ui/tender-card";

type Params = { params: Promise<{ id: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { id } = await params;
  return { title: `${id} · ${ru.catalog.title}` };
}

export default async function TenderPage({ params }: Params) {
  const { id } = await params;
  return <TenderCard regNum={id} />;
}
