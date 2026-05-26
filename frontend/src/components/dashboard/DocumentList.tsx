import type { PdfDocument } from "../../types";
import { DocumentCard } from "./DocumentCard";

export function DocumentList({
  documents,
  selectedId,
  onOpen,
  onDelete
}: {
  documents: PdfDocument[];
  selectedId: string | null;
  onOpen: (document: PdfDocument) => void;
  onDelete: (document: PdfDocument) => void;
}) {
  if (documents.length === 0) {
    return (
      <div className="empty-state">
        <p>No documents yet.</p>
        <span>Upload a document to start asking questions.</span>
      </div>
    );
  }

  return (
    <div className="document-list">
      {documents.map((document) => (
        <DocumentCard
          key={document.document_id}
          document={document}
          selected={document.document_id === selectedId}
          onOpen={() => onOpen(document)}
          onDelete={() => onDelete(document)}
        />
      ))}
    </div>
  );
}
