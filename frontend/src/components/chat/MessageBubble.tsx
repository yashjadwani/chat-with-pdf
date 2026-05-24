import type { ChatMessage } from "../../types";
import { CitationBadge } from "./CitationBadge";

export function MessageBubble({ message }: { message: ChatMessage }) {
  return (
    <div className={`message-row ${message.role}`}>
      <div className="message-bubble">
        <p>{message.content}</p>
        {message.citations && message.citations.length > 0 && (
          <div className="citation-row">
            {message.citations.slice(0, 5).map((citation) => (
              <CitationBadge key={`${citation.page_number}-${citation.chunk_index}`} citation={citation} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
