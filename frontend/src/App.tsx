import { useEffect, useMemo, useState } from "react";
import { LibraryBig, LogOut, RefreshCw, SearchCheck } from "lucide-react";
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

export function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [authMode, setAuthMode] = useState<"login" | "signup">("login");
  const [documents, setDocuments] = useState<PdfDocument[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loadingDocs, setLoadingDocs] = useState(false);
  const [error, setError] = useState("");

  const selectedDocument = useMemo(
    () => documents.find((document) => document.document_id === selectedId) ?? null,
    [documents, selectedId]
  );

  async function refreshDocuments() {
    if (!session) return;
    setLoadingDocs(true);
    setError("");
    try {
      const result = await listDocuments();
      setDocuments(result.documents);
      if (!selectedId) {
        setSelectedId(result.documents.find((document) => document.status === "ready")?.document_id ?? null);
      }
    } catch (docsError) {
      setError(docsError instanceof Error ? docsError.message : "Could not load documents.");
    } finally {
      setLoadingDocs(false);
    }
  }

  async function removeDocument(documentId: string) {
    await deleteDocument(documentId);
    setDocuments((current) => current.filter((document) => document.document_id !== documentId));
    if (selectedId === documentId) setSelectedId(null);
  }

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => setSession(data.session));
    const { data } = supabase.auth.onAuthStateChange((_event, newSession) => {
      setSession(newSession);
    });

    return () => data.subscription.unsubscribe();
  }, []);

  useEffect(() => {
    refreshDocuments();
  }, [session]);

  useEffect(() => {
    if (!documents.some((document) => document.status === "processing")) return;
    const interval = window.setInterval(refreshDocuments, 3000);
    return () => window.clearInterval(interval);
  }, [documents, session]);

  if (!session) {
    return (
      <main className="auth-page">
        <section className="auth-art">
          <div className="brand-mark">
            <LibraryBig size={26} />
            Chat with PDF
          </div>
          <div className="auth-copy">
            <span className="eyebrow">Document RAG workspace</span>
            <h1>Read less manually. Verify more carefully.</h1>
            <p>
              A soft, focused interface for uploading PDFs, asking grounded questions,
              and checking page-level citations without losing the thread.
            </p>
          </div>
          <div className="paper-stack" aria-hidden="true">
            <div />
            <div />
            <div />
          </div>
        </section>

        <section className="auth-card">
          {authMode === "login" ? (
            <LoginForm onModeChange={() => setAuthMode("signup")} />
          ) : (
            <SignupForm onModeChange={() => setAuthMode("login")} />
          )}
        </section>
      </main>
    );
  }

  return (
    <main className="workspace">
      <aside className="sidebar">
        <div className="sidebar-top">
          <div className="brand-mark compact">
            <LibraryBig size={22} />
            Chat PDF
          </div>
          <Button variant="quiet" onClick={() => supabase.auth.signOut()} title="Sign out">
            <LogOut size={17} />
          </Button>
        </div>

        <div className="side-heading">
          <div>
            <span className="eyebrow">Library</span>
            <h1>Documents</h1>
          </div>
          <Button variant="quiet" onClick={refreshDocuments} disabled={loadingDocs} title="Refresh documents">
            {loadingDocs ? <Spinner /> : <RefreshCw size={17} />}
          </Button>
        </div>

        <UploadButton onUploaded={refreshDocuments} />
        {error && <p className="inline-error">{error}</p>}

        <DocumentList
          documents={documents}
          selectedId={selectedId}
          onOpen={(document) => setSelectedId(document.document_id)}
          onDelete={removeDocument}
        />
      </aside>

      <section className="main-stage">
        <header className="stage-header">
          <div>
            <span className="eyebrow">Grounded answers</span>
            <h1>Ask, retrieve, cite.</h1>
          </div>
          <div className="quality-chip">
            <SearchCheck size={16} />
            PDF context only
          </div>
        </header>

        <ChatWindow document={selectedDocument} />
      </section>
    </main>
  );
}
