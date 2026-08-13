import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ru } from "@/shared/i18n/ru";
import { DocumentViewerRoute } from "./viewer-route";

export const metadata: Metadata = { title: ru.documents.title };

type Params = { params: Promise<{ id: string; docId: string }> };

export default async function DocumentPage({ params }: Params) {
  const { id, docId } = await params;
  const documentId = Number(docId);
  if (!Number.isInteger(documentId)) notFound();

  return <DocumentViewerRoute regNum={id} documentId={documentId} />;
}
