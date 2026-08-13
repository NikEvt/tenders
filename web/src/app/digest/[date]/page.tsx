import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ru } from "@/shared/i18n/ru";
import { DigestReader } from "@/widgets/digest-reader/ui/digest-reader";

type Params = { params: Promise<{ date: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { date } = await params;
  return { title: ru.digest.titleFor(date) };
}

export default async function ArchivedDigestPage({ params }: Params) {
  const { date } = await params;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) notFound();
  return <DigestReader date={date} />;
}
