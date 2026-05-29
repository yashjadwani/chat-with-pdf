import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  FileText,
  Gauge,
  Library,
  LogOut,
  MailCheck,
  MessageSquareText,
  Moon,
  RefreshCw,
  SearchCheck,
  Sun,
  UploadCloud
} from "lucide-react";
import type { Session } from "@supabase/supabase-js";
import type { PdfDocument } from "./types";
import { supabase } from "./lib/supabase";
import { deleteDocument, listDocuments } from "./lib/api";
import { LoginForm } from "./components/auth/LoginForm";
import { SignupForm } from "./components/auth/SignupForm";
import { UploadButton } from "./components/dashboard/UploadButton";
import { DocumentList } from "./components/dashboard/DocumentList";
import { ChatWindow } from "./components/chat/ChatWindow";
import { Button } from "./components/ui/Button";
import { Spinner } from "./components/ui/Spinner";

type Theme = "light" | "dark";
const currentYear = new Date().getFullYear();

function BrandLogo({ compact = false }: { compact?: boolean }) {
  return (
    <div className={`brand-mark ${compact ? "compact" : ""}`}>
      <span className="logo-mark" aria-hidden="true">
        <svg viewBox="0 0 40 40" role="img" focusable="false">
          <path className="logo-sheet" d="M11 7h13.5L31 13.5V31H11V7Z" />
          <path className="logo-fold" d="M24.5 7v7H31" />
          <path className="logo-line" d="M15 18h10M15 23h8" />
          <path className="logo-bubble" d="M23 24.5h9.5c1.4 0 2.5 1.1 2.5 2.5v4.5c0 1.4-1.1 2.5-2.5 2.5h-4.8L24 37v-3h-1c-1.4 0-2.5-1.1-2.5-2.5V27c0-1.4 1.1-2.5 2.5-2.5Z" />
          <path className="logo-spark" d="M25 29.2l2 2 4.2-4.4" />
        </svg>
      </span>
      {compact ? "PDF Chat" : "PDF Chat"}
    </div>
  );
}

export function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [authMode, setAuthMode] = useState<"login" | "signup">("login");
  const [pendingVerificationEmail, setPendingVerificationEmail] = useState("");
  const [theme, setTheme] = useState<Theme>(() => {
    return (localStorage.getItem("chat-pdf-theme") as Theme | null) ?? "light";
  });
  const [documents, setDocuments] = useState<PdfDocument[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [chatOpen, setChatOpen] = useState(true);
  const [pendingDelete, setPendingDelete] = useState<PdfDocument | null>(null);
  const [loadingDocs, setLoadingDocs] = useState(false);
  const [documentsDrawerOpen, setDocumentsDrawerOpen] = useState(false);
  const [docsLoaded, setDocsLoaded] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [pendingAutoSummaryId, setPendingAutoSummaryId] = useState<string | null>(null);
  const tokenRetryCount = useRef(0);
  const [documentPollStartedAt, setDocumentPollStartedAt] = useState<number | null>(null);
  const themeToggleLabel = theme === "light" ? "Switch to dark mode" : "Switch to light mode";
  const themeToggleText = theme === "light" ? "Dark mode" : "Light mode";

  const selectedDocument = useMemo(
    () => documents.find((document) => document.document_id === selectedId) ?? null,
    [documents, selectedId]
  );
  const displayName =
    getDisplayName(session) ??
    session?.user.email?.split("@")[0] ??
    "there";

  async function refreshDocuments(showSpinner = true) {
    if (!session) return;
    if (showSpinner) setLoadingDocs(true);
    setError("");
    try {
      const result = await listDocuments();
      tokenRetryCount.current = 0;
      setDocuments(result.documents);
      setDocsLoaded(true);
      if (!result.documents.some((document) => document.status === "processing")) {
        setDocumentPollStartedAt(null);
      }
      if (!selectedId) {
        setSelectedId(result.documents.find((document) => document.status === "ready")?.document_id ?? null);
      }
    } catch (docsError) {
      const message = docsError instanceof Error ? docsError.message : "Could not load documents.";
      if (isTokenWarmupError(message) && tokenRetryCount.current < 2) {
        tokenRetryCount.current += 1;
        window.setTimeout(() => refreshDocuments(false), 1200);
        return;
      }
      setError(isTokenWarmupError(message) ? "Your sign-in session is still starting. Try refresh in a moment." : message);
      setDocsLoaded(true);
    } finally {
      if (showSpinner) setLoadingDocs(false);
    }
  }

  async function confirmDeleteDocument() {
    if (!pendingDelete) return;

    setDeleting(true);
    setError("");
    try {
      await deleteDocument(pendingDelete.document_id);
      setDocuments((current) =>
        current.filter((document) => document.document_id !== pendingDelete.document_id)
      );
      if (selectedId === pendingDelete.document_id) {
        setSelectedId(null);
        setChatOpen(false);
      }
      setToast("Document deleted.");
      setPendingDelete(null);
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "Could not delete document.");
    } finally {
      setDeleting(false);
    }
  }

  function toggleTheme() {
    setTheme((current) => {
      const next = current === "light" ? "dark" : "light";
      localStorage.setItem("chat-pdf-theme", next);
      return next;
    });
  }

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => setSession(data.session));
    const { data } = supabase.auth.onAuthStateChange((_event, newSession) => {
      setSession(newSession);
      if (!newSession) {
        setDocuments([]);
        setSelectedId(null);
        setDocsLoaded(false);
        setPendingAutoSummaryId(null);
      }
    });

    return () => data.subscription.unsubscribe();
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timeout = window.setTimeout(() => setToast(""), 3200);
    return () => window.clearTimeout(timeout);
  }, [toast]);

  useEffect(() => {
    refreshDocuments(false);
    if (!session) setDocumentPollStartedAt(null);
  }, [session]);

  useEffect(() => {
    if (!session) return;

    const hasProcessingDocument = documents.some((document) => document.status === "processing");
    const pollWindowActive =
      documentPollStartedAt !== null && Date.now() - documentPollStartedAt < 5 * 60 * 1000;

    if (!hasProcessingDocument && !pollWindowActive) return;

    const interval = window.setInterval(() => {
      const pollWindowExpired =
        documentPollStartedAt !== null && Date.now() - documentPollStartedAt >= 5 * 60 * 1000;

      if (!hasProcessingDocument && pollWindowExpired) {
        setDocumentPollStartedAt(null);
        return;
      }

      refreshDocuments(false);
    }, 3000);

    return () => window.clearInterval(interval);
  }, [documents, documentPollStartedAt, session]);

  useEffect(() => {
    if (!pendingAutoSummaryId) return;

    const uploadedDocument = documents.find((document) => document.document_id === pendingAutoSummaryId);
    if (!uploadedDocument) return;

    if (uploadedDocument.status === "ready") {
      setSelectedId(uploadedDocument.document_id);
      setChatOpen(true);
      setDocumentsDrawerOpen(false);
    }

    if (uploadedDocument.status === "failed") {
      setPendingAutoSummaryId(null);
    }
  }, [documents, pendingAutoSummaryId]);

  if (!session) {
    return (
      <main className="auth-page" data-theme={theme}>
        <section className="auth-art">
          <div className="auth-topbar">
            <BrandLogo />
            <div className="theme-toggle">
              <Button variant="quiet" onClick={toggleTheme} title={themeToggleLabel} aria-label={themeToggleLabel}>
                {theme === "light" ? <Moon size={17} /> : <Sun size={17} />}
              </Button>
              <span className="theme-toggle-text">{themeToggleText}</span>
            </div>
          </div>
          <div className="auth-story-grid">
            <div className="auth-copy">
              <span className="eyebrow">Private document assistant</span>
              <h1>Ask your documents simple questions.</h1>
              <p>
                Upload a document, ask in plain English, and get answers that point back
                to the right pages.
              </p>
              <div className="auth-workflow" aria-label="How it works">
                <span>Upload</span>
                <span>Ask</span>
                <span>Review</span>
                <span>Check pages</span>
              </div>
            </div>
            <TrustPanel />
          </div>
          <PrivacyPreview />
          <CopyrightNotice variant="auth" />
        </section>

        <section className="auth-card">
          {pendingVerificationEmail ? (
            <CheckEmailPanel
              email={pendingVerificationEmail}
              onBackToLogin={() => {
                setPendingVerificationEmail("");
                setAuthMode("login");
              }}
            />
          ) : authMode === "login" ? (
            <LoginForm onModeChange={() => setAuthMode("signup")} />
          ) : (
            <SignupForm
              onModeChange={() => setAuthMode("login")}
              onVerificationNeeded={(email) => setPendingVerificationEmail(email)}
            />
          )}
        </section>
      </main>
    );
  }

  return (
    <main className="workspace" data-theme={theme}>
      <button
        className="mobile-drawer-toggle"
        type="button"
        onClick={() => setDocumentsDrawerOpen(true)}
        aria-label="Open document library"
      >
        <Library size={18} />
        Documents
      </button>
      {documentsDrawerOpen && (
        <button
          className="mobile-drawer-backdrop"
          type="button"
          onClick={() => setDocumentsDrawerOpen(false)}
          aria-label="Close document library"
        />
      )}
      <aside className={`sidebar ${documentsDrawerOpen ? "is-open" : ""}`}>
        <div className="sidebar-top">
          <BrandLogo compact />
          <div className="top-actions">
            <Button variant="quiet" onClick={toggleTheme} title={themeToggleLabel} aria-label={themeToggleLabel}>
              {theme === "light" ? <Moon size={17} /> : <Sun size={17} />}
            </Button>
            <Button variant="quiet" onClick={() => supabase.auth.signOut()} title="Sign out" aria-label="Sign out">
              <LogOut size={17} />
            </Button>
          </div>
        </div>

        <div className="user-welcome" aria-label="Signed in user">
          <span>Welcome</span>
          <strong>{displayName}</strong>
        </div>

        <div className="side-heading">
          <div>
            <span className="eyebrow">Library</span>
            <h1>Documents</h1>
          </div>
          <Button
            variant="quiet"
            onClick={() => refreshDocuments(true)}
            disabled={loadingDocs}
            title="Refresh documents"
            aria-label="Refresh documents"
          >
            {loadingDocs ? <Spinner /> : <RefreshCw size={17} />}
          </Button>
        </div>

        <UploadButton
          onUploaded={(document) => {
            setToast("Document uploaded. Preparing it now.");
            setPendingAutoSummaryId(document.document_id);
            setSelectedId(document.document_id);
            setChatOpen(true);
            setDocumentPollStartedAt(Date.now());
            refreshDocuments(false);
          }}
        />
        {error && <p className="inline-error">{error}</p>}

        {!docsLoaded ? (
          <DocumentSkeletonList />
        ) : (
          <DocumentList
            documents={documents}
            selectedId={selectedId}
            onOpen={(document) => {
              setSelectedId(document.document_id);
              setChatOpen(true);
              setDocumentsDrawerOpen(false);
            }}
            onDelete={setPendingDelete}
          />
        )}
        <CopyrightNotice variant="sidebar" />
      </aside>

      <section className="main-stage">
        <header className="stage-header">
          <div>
            <span className="eyebrow">Document answers</span>
            <h1>Ask and verify.</h1>
          </div>
          <div className="quality-chip">
            <SearchCheck size={16} />
            Uses your document only
          </div>
        </header>

        {chatOpen && selectedDocument ? (
          <ChatWindow
            document={selectedDocument}
            onClose={() => setChatOpen(false)}
            autoStartSummary={selectedDocument.document_id === pendingAutoSummaryId}
            onAutoSummaryStarted={() => setPendingAutoSummaryId(null)}
          />
        ) : (
          <ProjectOverview
            documents={documents}
            onOpenDocument={(document) => {
              setSelectedId(document.document_id);
              setChatOpen(true);
            }}
          />
        )}
      </section>

      {pendingDelete && (
        <DeleteConfirmationDialog
          document={pendingDelete}
          deleting={deleting}
          onCancel={() => setPendingDelete(null)}
          onConfirm={confirmDeleteDocument}
        />
      )}
      {toast && (
        <div className="toast" role="status" aria-live="polite">
          <CheckCircle2 size={17} />
          {toast}
        </div>
      )}
    </main>
  );
}

function CopyrightNotice({ variant }: { variant: "auth" | "sidebar" }) {
  return (
    <p className={`copyright-notice copyright-${variant}`}>
      &copy; {currentYear} PDF Chat. All rights reserved.
    </p>
  );
}

function isTokenWarmupError(message: string) {
  return message.toLowerCase().includes("token is not yet valid");
}

function getDisplayName(session: Session | null) {
  const value = session?.user.user_metadata?.display_name;
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function PrivacyPreview() {
  return (
    <aside className="privacy-preview" aria-label="Private document assistant preview">
      <div className="privacy-preview-header">
        <div>
          <span className="eyebrow eyebrow-sentence">Private by design</span>
          <h2>Your documents stay out of the preview.</h2>
        </div>
        <span className="status-badge status-ready">Private space</span>
      </div>

      <div className="privacy-flow">
        <div>
          <UploadCloud size={18} />
          <strong>Upload</strong>
          <span>Add your document</span>
        </div>
        <div>
          <FileText size={18} />
          <strong>Read</strong>
          <span>We prepare it for questions</span>
        </div>
        <div>
          <SearchCheck size={18} />
          <strong>Answer</strong>
          <span>Get page-backed replies</span>
        </div>
      </div>

      <div className="privacy-skeleton" aria-hidden="true">
        <span />
        <span />
        <span />
      </div>
    </aside>
  );
}

function TrustPanel() {
  return (
    <aside className="trust-panel" aria-label="Why teams use PDF Chat">
      <div className="trust-card trust-card-proof">
        <span className="eyebrow eyebrow-sentence">Built for focused review</span>
        <h2>Keep answers tied to the page instead of guessing from memory.</h2>
        <p>
          Designed for contracts, reports, handbooks, and research notes that need quick,
          traceable answers.
        </p>
      </div>

      <div className="trust-metrics" aria-label="Product benefits">
        <div className="trust-card">
          <strong>Page-backed</strong>
          <span>Every answer stays grounded in the uploaded file.</span>
        </div>
        <div className="trust-card">
          <strong>Private workspace</strong>
          <span>Your library stays organized in a calm, dedicated space.</span>
        </div>
      </div>
    </aside>
  );
}

function DocumentSkeletonList() {
  return (
    <div className="document-list" aria-label="Loading documents">
      {[0, 1, 2].map((item) => (
        <div className="document-skeleton" key={item}>
          <span />
          <div>
            <i />
            <i />
          </div>
        </div>
      ))}
    </div>
  );
}

function CheckEmailPanel({
  email,
  onBackToLogin
}: {
  email: string;
  onBackToLogin: () => void;
}) {
  const [message, setMessage] = useState("");
  const [resending, setResending] = useState(false);

  async function resendConfirmation() {
    setResending(true);
    setMessage("");
    const { error } = await supabase.auth.resend({
      type: "signup",
      email
    });
    setMessage(error ? error.message : "Verification email sent again.");
    setResending(false);
  }

  return (
    <section className="auth-form check-email-panel" aria-labelledby="check-email-title">
      <div className="mail-hero">
        <MailCheck size={30} />
      </div>
      <div className="form-heading centered">
        <div>
          <h1 id="check-email-title">Check your email</h1>
          <p>
            We sent a verification link to <strong>{email}</strong>. Verify your account,
            then come back and sign in.
          </p>
        </div>
      </div>

      {message && <p className={message.includes("sent") ? "form-note form-success" : "form-error"}>{message}</p>}

      <Button onClick={resendConfirmation} disabled={resending} type="button">
        {resending ? "Sending" : "Resend email"}
      </Button>
      <button className="text-button" type="button" onClick={onBackToLogin}>
        Back to login
      </button>
    </section>
  );
}

function ProjectOverview({
  documents,
  onOpenDocument
}: {
  documents: PdfDocument[];
  onOpenDocument: (document: PdfDocument) => void;
}) {
  const readyCount = documents.filter((document) => document.status === "ready").length;
  const processingCount = documents.filter((document) => document.status === "processing").length;
  const failedCount = documents.filter((document) => document.status === "failed").length;
  const recentDocuments = [...documents]
    .sort((a, b) => new Date(b.uploaded_at).getTime() - new Date(a.uploaded_at).getTime())
    .slice(0, 5);

  return (
    <section className="overview-panel">
      <div className="overview-hero">
        <span className="overview-icon">
          <Gauge size={24} />
        </span>
        <div>
          <span className="eyebrow">Workspace overview</span>
          <h2>Your document library is ready.</h2>
          <p>
            Keep your documents in one place, ask questions when you need them, and check
            answers against the original pages.
          </p>
        </div>
      </div>

      <div className="overview-grid">
        <div className="metric-card">
          <span>Total documents</span>
          <strong>{documents.length}</strong>
        </div>
        <div className="metric-card">
          <span>Ready to ask</span>
          <strong>{readyCount}</strong>
        </div>
        <div className="metric-card">
          <span>Processing</span>
          <strong>{processingCount}</strong>
        </div>
        <div className="metric-card">
          <span>Failed</span>
          <strong>{failedCount}</strong>
        </div>
      </div>

      <section className="overview-library" aria-label="Uploaded documents">
        <div className="overview-section-head">
          <div>
            <span className="eyebrow">Uploaded documents</span>
            <h3>Latest 5 documents</h3>
          </div>
        </div>

        {recentDocuments.length > 0 ? (
          <div className="overview-doc-grid">
            {recentDocuments.map((document) => {
              const displayName = document.filename.replace(/\.pdf$/i, "");
              return (
                <article
                  className={`overview-doc-card ${document.status === "ready" ? "is-openable" : ""}`}
                  key={document.document_id}
                  role={document.status === "ready" ? "button" : undefined}
                  tabIndex={document.status === "ready" ? 0 : undefined}
                  onClick={() => {
                    if (document.status === "ready") onOpenDocument(document);
                  }}
                  onKeyDown={(event) => {
                    if (document.status !== "ready") return;
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      onOpenDocument(document);
                    }
                  }}
                  aria-label={document.status === "ready" ? `Open ${displayName}` : undefined}
                >
                  <div className="overview-doc-card-top">
                    <span className="overview-doc-file-icon" aria-hidden="true">
                      <FileText size={20} />
                    </span>
                    <span className={`doc-status-label doc-status-label-${document.status}`}>
                      {formatStatus(document.status)}
                    </span>
                  </div>
                  <h4 title={displayName}>{displayName}</h4>
                  <div className="overview-doc-card-meta">
                    <span>{document.total_pages ?? "-"} pages</span>
                    <span>{document.language ?? "Detecting"}</span>
                  </div>
                </article>
              );
            })}
          </div>
        ) : (
          <div className="overview-empty-library">
            <FileText size={22} />
            <strong>No documents yet</strong>
            <span>Upload a document from the left panel to begin.</span>
          </div>
        )}
      </section>

      <div className="workflow-strip">
        <div>
          <UploadCloud size={18} />
          <span>Upload</span>
        </div>
        <div>
          <FileText size={18} />
          <span>Prepare</span>
        </div>
        <div>
          <SearchCheck size={18} />
          <span>Find pages</span>
        </div>
        <div>
          <MessageSquareText size={18} />
          <span>Answer</span>
        </div>
      </div>
    </section>
  );
}

function formatStatus(status: PdfDocument["status"]) {
  return status.charAt(0).toUpperCase() + status.slice(1);
}

function DeleteConfirmationDialog({
  document,
  deleting,
  onCancel,
  onConfirm
}: {
  document: PdfDocument;
  deleting: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onCancel}>
      <section
        className="confirm-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="delete-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <span className="danger-mark">
          <AlertTriangle size={22} />
        </span>
        <div>
          <span className="eyebrow">Confirm deletion</span>
          <h2 id="delete-title">Delete this document?</h2>
          <p>
            This removes <strong>{document.filename}</strong>, the uploaded document,
            its saved page search data, and related chats. This action cannot be undone.
          </p>
        </div>
        <div className="dialog-actions">
          <Button variant="quiet" onClick={onCancel} disabled={deleting}>
            Cancel
          </Button>
          <Button variant="danger" onClick={onConfirm} disabled={deleting}>
            {deleting ? "Deleting" : "Delete document"}
          </Button>
        </div>
      </section>
    </div>
  );
}
