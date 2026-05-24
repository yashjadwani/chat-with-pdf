import { FileText, MessageSquareText, Trash2 } from "lucide-react";
import type { PdfDocument } from "../../types";
import { Button } from "../ui/Button";
import { StatusBadge } from "../ui/StatusBadge";

export function DocumentCard({
  document,
  selected,
  onOpen,
  onDelete
}: {
  document: PdfDocument;
  selected: boolean;
  onOpen: () => void;
  onDelete: () => void;
}) {
  const uploadedAt = new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(document.uploaded_at));

  return (
    <article className={`document-card ${selected ? "selected" : ""}`}>
      <div className="doc-icon">
        <FileText size={21} />
      </div>
      <div className="doc-main">
        <div className="doc-title-row">
          <h3>{document.filename}</h3>
          <StatusBadge status={document.status} />
        </div>
        <div className="doc-meta">
          <span>{document.total_pages ?? "-"} pages</span>
          <span>{document.language ?? "detecting"}</span>
          <span>{uploadedAt}</span>
        </div>
        {document.error_message && <p className="doc-error">{document.error_message}</p>}
      </div>
      <div className="doc-actions">
        <Button variant="quiet" disabled={document.status !== "ready"} onClick={onOpen} title="Open chat">
          <MessageSquareText size={17} />
        </Button>
        <Button variant="quiet" onClick={onDelete} title="Delete document">
          <Trash2 size={17} />
        </Button>
      </div>
    </article>
  );
}
