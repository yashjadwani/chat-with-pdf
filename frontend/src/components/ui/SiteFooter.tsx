import { useRef, type ReactNode, type RefObject } from "react";
import { BookOpen, Github, MessageSquareText } from "lucide-react";
import { version } from "../../../package.json";

const repoUrl = "https://github.com/yashjadwani/chat-with-pdf";
const shortVersion = `v${version.split(".").slice(0, 2).join(".")}`;

export function SiteFooter() {
  const methodologyRef = useRef<HTMLDialogElement>(null);
  const privacyRef = useRef<HTMLDialogElement>(null);

  return (
    <footer className="site-footer">
      <div className="site-footer-brand">
        <span className="site-footer-logo" aria-hidden="true">
          <MessageSquareText size={15} />
        </span>
        <span className="site-footer-wordmark">
          PDF Ch<span className="site-footer-wordmark-accent">at</span>
        </span>
        <span className="site-footer-version">{shortVersion}</span>
      </div>

      <nav className="site-footer-links" aria-label="Footer">
        <a className="site-footer-box" href={repoUrl} target="_blank" rel="noreferrer">
          <Github size={15} />
          GitHub
        </a>
        <a
          className="site-footer-box"
          href={`${repoUrl}/tree/main/docs`}
          target="_blank"
          rel="noreferrer"
        >
          <BookOpen size={15} />
          Docs
        </a>
        <button
          className="site-footer-text-link"
          type="button"
          onClick={() => methodologyRef.current?.showModal()}
        >
          Methodology
        </button>
        <button
          className="site-footer-text-link"
          type="button"
          onClick={() => privacyRef.current?.showModal()}
        >
          Privacy
        </button>
        <a
          className="site-footer-text-link"
          href={`${repoUrl}/issues/new`}
          target="_blank"
          rel="noreferrer"
        >
          Feedback
        </a>
      </nav>

      <FooterDialog dialogRef={methodologyRef} title="How PDF Chat works">
        <p>
          Every uploaded document is split into passages and indexed for search. When you
          ask a question, we retrieve the passages that match it and answer from those
          passages only, citing the pages they came from so you can check the original.
        </p>
      </FooterDialog>

      <FooterDialog dialogRef={privacyRef} title="Privacy">
        <p>
          PDF Chat is analysis-only. Your documents are used to answer your questions and
          nothing else. No advertising, no third-party tracking.
        </p>
      </FooterDialog>
    </footer>
  );
}

function FooterDialog({
  dialogRef,
  title,
  children
}: {
  dialogRef: RefObject<HTMLDialogElement>;
  title: string;
  children: ReactNode;
}) {
  return (
    <dialog
      className="site-footer-dialog"
      ref={dialogRef}
      onClick={(event) => {
        if (event.target === dialogRef.current) dialogRef.current?.close();
      }}
    >
      <h2>{title}</h2>
      {children}
      <button className="text-button" type="button" onClick={() => dialogRef.current?.close()}>
        Close
      </button>
    </dialog>
  );
}
