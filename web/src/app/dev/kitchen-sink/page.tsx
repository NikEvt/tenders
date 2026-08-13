import type { Metadata } from "next";
import { KitchenSink } from "./kitchen-sink";

export const metadata: Metadata = {
  title: "Витрина примитивов",
  robots: { index: false, follow: false },
};

/** Витрина дизайн-системы: каждый примитив во всех состояниях, обе темы. */
export default function KitchenSinkPage() {
  return <KitchenSink />;
}
