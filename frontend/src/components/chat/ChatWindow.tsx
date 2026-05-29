import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, ArrowDown, BarChart3, FileSearch, MessageCircle, PanelRightClose, Sparkles, Trash2 } from "lucide-react";
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
  const [pendingMode, setPendingMode] = useState<AnswerMode>("question");
  const [showJumpButton, setShowJumpButton] = useState(false);
  const [error, setError] = useState("");
  const messagesRef = useRef<HTMLDivElement | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const suggestions = useMemo(() => getPromptSuggestions(document), [document]);

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
    const mode = getAnswerMode(question);
    const userMessage = makeMessage("user", question);
    const assistantId = crypto.randomUUID();
    setPendingMode(mode);
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

  function scrollToBottom(behavior: ScrollBehavior = "smooth") {
    bottomRef.current?.scrollIntoView({ behavior, block: "end" });
  }

  function onMessagesScroll() {
    const element = messagesRef.current;
    if (!element) return;
    const distanceFromBottom = element.scrollHeight - element.scrollTop - element.clientHeight;
    setShowJumpButton(distanceFromBottom > 180);
  }

  useEffect(() => {
    scrollToBottom(messages.length <= 2 ? "auto" : "smooth");
  }, [messages.length, loadingAnswer]);

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

      <div className="messages" ref={messagesRef} onScroll={onMessagesScroll}>
        {loadingHistory ? (
          <div className="empty-state">
            <p>Loading conversation...</p>
            <span>Opening your saved conversation.</span>
          </div>
        ) : messages.length === 0 ? (
          <div className="prompt-suggestions">
            <div className="suggestion-heading">
              <Sparkles size={17} />
              <span>Try asking</span>
            </div>
            {suggestions.map((suggestion) => (
              <button
                disabled={loadingAnswer}
                key={suggestion.text}
                onClick={() => send(suggestion.text)}
              >
                <suggestion.icon size={17} />
                <span>{suggestion.label}</span>
              </button>
            ))}
          </div>
        ) : (
          messages.map((message) => (
            <MessageBubble
              key={message.id}
              message={message}
              loadingLabel={getLoadingLabel(pendingMode)}
            />
          ))
        )}
        <div ref={bottomRef} />
        {showJumpButton && (
          <button className="scroll-bottom-button" type="button" onClick={() => scrollToBottom()} aria-label="Scroll to latest message">
            <ArrowDown size={17} />
          </button>
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

type AnswerMode = "question" | "summary" | "comparison";

const summaryTerms = ["summarize", "summarise", "summary", "overview", "main points", "key takeaways", "takeaways"];
const comparisonTerms = ["best", "highest", "lowest", "most", "least", "compare", "rank", "benefited", "improved", "better", "worse", "cost", "time", "score"];

function getAnswerMode(question: string): AnswerMode {
  const lower = question.toLowerCase();
  if (summaryTerms.some((term) => lower.includes(term))) return "summary";
  if (comparisonTerms.some((term) => lower.includes(term))) return "comparison";
  return "question";
}

function getLoadingLabel(mode: AnswerMode) {
  if (mode === "summary") return "Reading across the document";
  if (mode === "comparison") return "Comparing evidence";
  return "Finding the right pages";
}

function getPromptSuggestions(document: PdfDocument) {
  if (document.status === "processing") {
    return [
      { label: "Check readiness", text: "Is this document ready to ask questions?", icon: FileSearch },
      { label: "What can I ask?", text: "What kinds of questions can I ask once this document is ready?", icon: MessageCircle },
      { label: "Summarize later", text: "Summarize this document when it is ready", icon: Sparkles }
    ];
  }

  if (document.status === "failed") {
    return [
      { label: "Explain issue", text: "Why could this document not be prepared?", icon: AlertTriangle },
      { label: "Next step", text: "What should I try next with this document?", icon: FileSearch },
      { label: "Upload guidance", text: "What kind of PDF works best?", icon: MessageCircle }
    ];
  }

  return [
    { label: "Summarize", text: "Summarize this document with page references", icon: Sparkles },
    { label: "Key points", text: "What are the key points in this document?", icon: FileSearch },
    { label: "Compare", text: "Compare the main options or results in this document", icon: BarChart3 },
    { label: "Limitations", text: "What limitations or risks are mentioned?", icon: MessageCircle }
  ];
}
