"use client";

import Link from "next/link";
import { FileText } from "lucide-react";
import { Button } from "@/shared/ui/button";
import { EmptyState } from "@/shared/ui/empty-state";
import { Pill } from "@/shared/ui/pill";
import { Table, TBody, TD, TH, THead, TR } from "@/shared/ui/table";
import { ru } from "@/shared/i18n/ru";
import { fileSize, formatCount } from "@/shared/lib/format";
import type { TenderDocument } from "@/shared/api/types";
import { documentStatus } from "@/entities/tender/model/document-status";

export function DocumentsTab({
  regNum,
  documents,
}: {
  regNum: string;
  documents: TenderDocument[];
}) {
  if (documents.length === 0) {
    return (
      <EmptyState
        icon={<FileText strokeWidth={1.5} />}
        title={ru.documents.notTouchedYet}
        body="Как только docs-worker скачает вложения, здесь появится таблица со статусом распознавания."
        action={
          <Button asChild variant="secondary">
            <Link href="/monitoring/documents">{ru.monitoring.documentsPipeline}</Link>
          </Button>
        }
      />
    );
  }

  return (
    <Table>
      <THead>
        <tr>
          <TH>{ru.documents.name}</TH>
          <TH>{ru.documents.kind}</TH>
          <TH numeric>{ru.documents.size}</TH>
          <TH>{ru.documents.ocrStatus}</TH>
          <TH numeric>Символов</TH>
          <TH />
        </tr>
      </THead>
      <TBody>
        {documents.map((document) => {
          const status = documentStatus(document.extraction_status);
          return (
            <TR key={document.document_id}>
              <TD>
                <span className="clamp-1 max-w-96" title={document.file_name ?? undefined}>
                  {document.file_name ?? `#${document.document_id}`}
                </span>
              </TD>
              <TD className="text-text-muted">{document.doc_kind_name ?? "—"}</TD>
              <TD numeric>{fileSize(document.file_size)}</TD>
              <TD>
                <span className="flex items-center gap-2">
                  <Pill tone={status.tone}>{status.label}</Pill>
                  {document.ocr_used ? (
                    <span className="text-body-sm text-text-subtle">OCR</span>
                  ) : null}
                </span>
              </TD>
              <TD numeric>
                {document.char_count === null ? "—" : formatCount(document.char_count)}
              </TD>
              <TD className="text-right">
                {document.has_text ? (
                  <Button asChild size="sm" variant="ghost">
                    <Link href={`/tenders/${regNum}/documents/${document.document_id}`}>
                      {ru.common.open}
                    </Link>
                  </Button>
                ) : (
                  <span className="text-body-sm text-text-subtle">
                    {ru.documents.notExtracted}
                  </span>
                )}
              </TD>
            </TR>
          );
        })}
      </TBody>
    </Table>
  );
}
