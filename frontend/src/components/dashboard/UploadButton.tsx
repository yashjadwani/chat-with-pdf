import { ChangeEvent, useEffect, useRef, useState } from "react";
import { FileText, Info, Upload } from "lucide-react";
import { uploadDocument } from "../../lib/api";
import { Button } from "../ui/Button";
import { Spinner } from "../ui/Spinner";

type UploadResult = Awaited<ReturnType<typeof uploadDocument>>;

const MAX_FILE_SIZE_MB = 50;
const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024;

export function UploadButton({ onUploaded }: { onUploaded: (document: UploadResult) => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [fileFeedback, setFileFeedback] = useState("");

  useEffect(() => {
    if (!success) return;
    const timeout = window.setTimeout(() => setSuccess(""), 3200);
    return () => window.clearTimeout(timeout);
  }, [success]);

  async function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;

    setError("");
    setSuccess("");
    setFileFeedback("");

    const validationError = validateFile(file);
    if (validationError) {
      setError(validationError);
      event.target.value = "";
      return;
    }

    setFileFeedback(`${file.name} - ${formatFileSize(file.size)}`);
    setLoading(true);
    try {
      const document = await uploadDocument(file);
      setSuccess("Uploaded. Preparing your document.");
      onUploaded(document);
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : "Upload failed.");
    } finally {
      setLoading(false);
      event.target.value = "";
    }
  }

  return (
    <div className="upload-control">
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf,.pdf"
        onChange={onFileChange}
        aria-describedby="upload-guidance"
        hidden
      />
      <Button onClick={() => inputRef.current?.click()} disabled={loading}>
        {loading ? <Spinner /> : <Upload size={17} />}
        {loading ? "Uploading" : "Upload document"}
      </Button>
      <div className="upload-guidance" id="upload-guidance">
        <Info size={14} />
        <span>PDF only, up to {MAX_FILE_SIZE_MB} MB.</span>
      </div>
      {fileFeedback && (
        <span className="upload-file-feedback">
          <FileText size={14} />
          {fileFeedback}
        </span>
      )}
      {error && <span className="inline-error">{error}</span>}
      {success && <span className="inline-success">{success}</span>}
    </div>
  );
}

function validateFile(file: File) {
  const isPdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
  if (!isPdf) return "Please upload a PDF file.";
  if (file.size === 0) return "This file is empty. Choose another PDF.";
  if (file.size > MAX_FILE_SIZE_BYTES) {
    return `This file is ${formatFileSize(file.size)}. The limit is ${MAX_FILE_SIZE_MB} MB.`;
  }
  return "";
}

function formatFileSize(bytes: number) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(bytes < 10 * 1024 * 1024 ? 1 : 0)} MB`;
}
