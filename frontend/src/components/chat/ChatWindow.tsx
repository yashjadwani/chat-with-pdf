import { useEffect, useState } from "react";
import { AlertTriangle, MessageCircle, PanelRightClose, Trash2 } from "lucide-react";
import type { ChatMessage, PdfDocument } from "../../types";
import { askDocument, clearChatHistory, getChatHistory, makeMessage } from "../../lib/api";
import { Button } from "../ui/Button";
import { MessageBubble } from "./MessageBubble";
import { QueryInput } from "./QueryInput";

export function ChatWindow({
  document,
  onClose
}: {
  document: PdfDocument;
  onClose: () => void;
}) {
  const displayName = document.filename.replace(/\.pdf$/i, "");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loadingAnswer, setLoadingAnswer] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [confirmingClear, setConfirmingClear] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;

    async function loadHistory() {
      if (document.status !== "ready") {
        setMessages([]);
        return;
      }

      setLoadingHistory(true);
      setError("");
      try {
        const history = await getChatHistory(document.document_id);
        if (cancelled) return;
        setMessages(
          history.messages
            .filter(
              (message): message is typeof message & { role: "user" | "assistant" } =>
                message.role === "user" || message.role === "assistant"
            )
            .map((message) => ({
              id: crypto.randomUUID(),
              role: message.role,
              content: message.content,
              citations: message.citations
            }))
        );
      } catch (historyError) {
        if (!cancelled) {
          setMessages([]);
          setError(historyError instanceof Error ? historyError.message : "Could not load chat history.");
        }
      } finally {
        if (!cancelled) setLoadingHistory(false);
      }
    }

    loadHistory();
    return () => {
      cancelled = true;
    };
  }, [document?.document_id, document?.status]);

  async function clearHistory() {
    setError("");
    try {
      await clearChatHistory(document.document_id);
      setMessages([]);
      setConfirmingClear(false);
    } catch (clearError) {
      setError(clearError instanceof Error ? clearError.message : "Could not clear chat history.");
    }
  }

  async function send(question: string) {
    const userMessage = makeMessage("user", question);
    const assistantId = crypto.randomUUID();
    setMessages((current) => [
      ...current,
      userMessage,
      { id: assistantId, role: "assistant", content: "" }
    ]);
    setLoadingAnswer(true);
    setError("");

    try {
      const response = await askDocument(document.document_id, question);
      setMessages((current) =>
        current.map((message) =>
          message.id === assistantId
            ? { ...message, content: response.answer, citations: response.citations }
            : message
        )
      );
    } catch (chatError) {
      setMessages((current) => current.filter((message) => message.id !== assistantId));
      setError(chatError instanceof Error ? chatError.message : "Chat failed.");
    } finally {
      setLoadingAnswer(false);
    }
  }

  return (
    <section className="chat-panel">
      <header className="chat-header">
        <div>
          <span className="eyebrow">Active document</span>
          <h2>{displayName}</h2>
        </div>
        <div className="chat-actions">
          <span className="stream-pill">
            <MessageCircle size={14} />
            Questions
          </span>
          <Button
            variant="quiet"
            onClick={() => setConfirmingClear(true)}
            disabled={loadingAnswer || loadingHistory || messages.length === 0}
            title="Clear conversation"
            aria-label="Clear conversation"
          >
            <Trash2 size={16} />
          </Button>
          <Button variant="quiet" onClick={onClose} title="Hide chat panel" aria-label="Hide chat panel">
            <PanelRightClose size={16} />
          </Button>
        </div>
      </header>

      <div className="messages">
        {loadingHistory ? (
          <div className="empty-state">
            <p>Loading conversation...</p>
            <span>Opening your saved conversation.</span>
          </div>
        ) : messages.length === 0 ? (
          <div className="prompt-suggestions">
            <button disabled={loadingAnswer} onClick={() => send("Summarize this document with page references")}>
              Summarize with page references
            </button>
            <button disabled={loadingAnswer} onClick={() => send("What are the key limitations mentioned?")}>
              Find limitations
            </button>
            <button disabled={loadingAnswer} onClick={() => send("Give me practical examples from this document")}>
              Extract examples
            </button>
          </div>
        ) : (
          messages.map((message) => <MessageBubble key={message.id} message={message} />)
        )}
      </div>

      {error && <p className="chat-error">{error}</p>}
      <QueryInput disabled={loadingAnswer || document.status !== "ready"} onSend={send} />

      {confirmingClear && (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setConfirmingClear(false)}>
          <section
            className="confirm-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="clear-chat-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <span className="danger-mark">
              <AlertTriangle size={22} />
            </span>
            <div>
              <span className="eyebrow">Confirm clear</span>
              <h2 id="clear-chat-title">Clear this chat?</h2>
              <p>
                This removes the saved conversation for
                <strong> {displayName}</strong>. The document stays in your library.
              </p>
            </div>
            <div className="dialog-actions">
              <Button variant="quiet" onClick={() => setConfirmingClear(false)} disabled={loadingAnswer}>
                Cancel
              </Button>
              <Button variant="danger" onClick={clearHistory} disabled={loadingAnswer}>
                Clear chat
              </Button>
            </div>
          </section>
        </div>
      )}
    </section>
  );
}
