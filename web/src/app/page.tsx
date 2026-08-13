import type { Metadata } from "next";
import { ru } from "@/shared/i18n/ru";
import { DigestReader } from "@/widgets/digest-reader/ui/digest-reader";

export const metadata: Metadata = { title: ru.digest.title };

/** Точка входа в рабочий день: сводка за сегодня. */
export default function HomePage() {
  const today = new Date().toISOString().slice(0, 10);
  return <DigestReader date={today} />;
}
