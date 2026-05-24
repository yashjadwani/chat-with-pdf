import { useState } from "react";
import { BookOpenCheck, Radio } from "lucide-react";
import type { ChatMessage, PdfDocument, Citation } from "../../types";
import { makeMessage, streamDocumentAnswer } from "../../lib/api";
import { MessageBubble } from "./MessageBubble";
import { QueryInput } from "./QueryInput";

export function ChatWindow({ document }: { document: PdfDocument | null }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState("");

  async function send(question: string) {
    if (!document) return;

    const userMessage = makeMessage("user", question);
    const assistantId = crypto.randomUUID();
    setMessages((current) => [
      ...current,
      userMessage,
      { id: assistantId, role: "assistant", content: "" }
    ]);
    setStreaming(true);
    setError("");

    let citations: Citation[] = [];
    try {
      await streamDocumentAnswer(document.document_id, question, {
        onCitations: (items) => {
          citations = items;
          setMessages((current) =>
            current.map((message) => (message.id === assistantId ? { ...message, citations } : message))
          );
        },
        onToken: (token) => {
          setMessages((current) =>
            current.map((message) =>
              message.id === assistantId ? { ...message, content: message.content + token } : message
            )
          );
        }
      });
    } catch (streamError) {
      setError(streamError instanceof Error ? streamError.message : "Chat failed.");
    } finally {
      setStreaming(false);
    }
  }

  if (!document) {
    return (
      <section className="chat-panel empty-chat">
        <BookOpenCheck size={34} />
        <h2>Select a ready document</h2>
        <p>Your cited answer workspace will appear here.</p>
      </section>
    );
  }

  return (
    <section className="chat-panel">
      <header className="chat-header">
        <div>
          <span className="eyebrow">Active document</span>
          <h2>{document.filename}</h2>
        </div>
        <span className="stream-pill">
          <Radio size={14} />
          Streaming
        </span>
      </header>

      <div className="messages">
        {messages.length === 0 ? (
          <div className="prompt-suggestions">
            <button onClick={() => send("Summarize this document with page citations")}>Summarize with citations</button>
            <button onClick={() => send("What are the key limitations mentioned?")}>Find limitations</button>
            <button onClick={() => send("Give me practical examples from this PDF")}>Extract examples</button>
          </div>
        ) : (
          messages.map((message) => <MessageBubble key={message.id} message={message} />)
        )}
      </div>

      {error && <p className="chat-error">{error}</p>}
      <QueryInput disabled={streaming || document.status !== "ready"} onSend={send} />
    </section>
  );
}
