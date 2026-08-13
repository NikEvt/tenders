"use client";

import dynamic from "next/dynamic";
import { parseAsString, useQueryState } from "nuqs";

// Панель нужна не при загрузке списка, а при открытии строки: её код и запросы
// приезжают вместе с первым `?preview=`.
const Inspector = dynamic(() => import("./inspector").then((m) => m.Inspector));

/**
 * Инспектор монтируется маршрутом рядом со списком, а не внутри него.
 *
 * Связь между ними — параметр `?preview=` в адресе, и только он. Поэтому
 * список не перерисовывается, когда панель открывается или листается `j`/`k`,
 * а вставленная ссылка воспроизводит экран вместе с открытой карточкой.
 */
export function InspectorSlot() {
  const [preview, setPreview] = useQueryState(
    "preview",
    parseAsString.withDefault("").withOptions({ history: "push", clearOnDefault: true }),
  );

  if (!preview) return null;
  return <Inspector regNum={preview} onClose={() => setPreview("")} />;
}
