"use client";

import * as React from "react";
import { DocumentViewer } from "@/widgets/document-viewer/ui/document-viewer";

/**
 * Якорь `#chunk-42` читается на клиенте: сервер о нём не знает — фрагмент
 * приходит из ссылки в ИИ-вердикте.
 */
export function DocumentViewerRoute({
  regNum,
  documentId,
}: {
  regNum: string;
  documentId: number;
}) {
  const [chunkId, setChunkId] = React.useState<number | null>(null);

  React.useEffect(() => {
    const match = /^#chunk-(\d+)$/.exec(window.location.hash);
    setChunkId(match ? Number(match[1]) : null);
  }, []);

  return <DocumentViewer regNum={regNum} documentId={documentId} chunkId={chunkId} />;
}
