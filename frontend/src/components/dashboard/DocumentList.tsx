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
      <div className="empty-state library-empty-state">
        <p>Your library is ready.</p>
        <span>Upload a document and PDF Chat will prepare an overview before your first question.</span>
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
