export type DocumentStatus = "processing" | "ready" | "failed";

export type PdfDocument = {
  document_id: string;
  user_id: string;
  filename: string;
  storage_path: string;
  language: string | null;
  total_pages: number | null;
  status: DocumentStatus;
  uploaded_at: string;
  error_message?: string | null;
};

export type Citation = {
  page_number: number;
  chunk_text: string;
  chunk_index: number;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
};

export type PersistedChatMessage = {
  role: "user" | "assistant" | "system";
  content: string;
  citations?: Citation[];
};
