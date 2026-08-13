import type { Metadata } from "next";
import { ContrastBoard } from "./contrast-board";

export const metadata: Metadata = {
  title: "Контраст",
  robots: { index: false, follow: false },
};

/** Все пары «текст на фоне» в обеих темах, с отношением, посчитанным на месте. */
export default function ContrastPage() {
  return <ContrastBoard />;
}
