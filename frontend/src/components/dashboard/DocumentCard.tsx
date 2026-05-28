import { FileText, Trash2 } from "lucide-react";
import type { PdfDocument } from "../../types";
import { Button } from "../ui/Button";

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
  const displayName = document.filename.replace(/\.pdf$/i, "");
  const uploadedAt = new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(document.uploaded_at));
  const canOpen = document.status === "ready";

  function openIfReady() {
    if (canOpen) onOpen();
  }

  return (
    <article
      className={`document-card ${selected ? "selected" : ""} ${canOpen ? "is-openable" : ""}`}
      role={canOpen ? "button" : undefined}
      tabIndex={canOpen ? 0 : undefined}
      onClick={openIfReady}
      onKeyDown={(event) => {
        if (!canOpen) return;
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpen();
        }
      }}
      aria-label={canOpen ? `Open ${displayName}` : undefined}
    >
      <div className="doc-icon">
        <FileText size={21} />
      </div>
      <div className="doc-main">
        <div className="doc-title-row">
          <h3>{displayName}</h3>
          <span
            className={`doc-status-dot doc-status-${document.status}`}
            title={document.status}
            aria-label={`Document status: ${document.status}`}
          />
        </div>
        <div className="doc-meta">
          <span>{document.total_pages ?? "-"} pages</span>
          <span>{uploadedAt}</span>
        </div>
        {document.error_message && <p className="doc-error">{document.error_message}</p>}
      </div>
      <div className="doc-actions">
        <Button
          variant="quiet"
          onClick={(event) => {
            event.stopPropagation();
            onDelete();
          }}
          title="Delete document"
          aria-label={`Delete ${displayName}`}
        >
          <Trash2 size={17} />
        </Button>
      </div>
    </article>
  );
}
