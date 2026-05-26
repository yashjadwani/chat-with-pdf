import { ChangeEvent, useRef, useState } from "react";
import { Upload } from "lucide-react";
import { uploadDocument } from "../../lib/api";
import { Button } from "../ui/Button";
import { Spinner } from "../ui/Spinner";

export function UploadButton({ onUploaded }: { onUploaded: () => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  async function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;

    setLoading(true);
    setError("");
    setSuccess("");
    try {
      await uploadDocument(file);
      setSuccess("Uploaded. Preparing your document.");
      onUploaded();
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : "Upload failed.");
    } finally {
      setLoading(false);
      event.target.value = "";
    }
  }

  return (
    <div className="upload-control">
      <input ref={inputRef} type="file" accept="application/pdf" onChange={onFileChange} hidden />
      <Button onClick={() => inputRef.current?.click()} disabled={loading}>
        {loading ? <Spinner /> : <Upload size={17} />}
        {loading ? "Uploading" : "Upload document"}
      </Button>
      {error && <span className="inline-error">{error}</span>}
      {success && <span className="inline-success">{success}</span>}
    </div>
  );
}
