import { Highlighter } from "lucide-react";
import type { Citation } from "../../types";

export function CitationBadge({ citation }: { citation: Citation }) {
  return (
    <button className="citation-badge" title={citation.chunk_text.slice(0, 220)}>
      <Highlighter size={13} />
      Page {citation.page_number}
    </button>
  );
}
