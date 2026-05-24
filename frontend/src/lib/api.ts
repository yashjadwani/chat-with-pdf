import { getAccessToken } from "./supabase";
import type { ChatMessage, PdfDocument, Citation } from "../types";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

async function authHeaders() {
  const token = await getAccessToken();
  if (!token) {
    throw new Error("You need to sign in first.");
  }
  return { Authorization: `Bearer ${token}` };
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = await authHeaders();
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      ...headers,
      ...(init.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...init.headers
    }
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || "Request failed.");
  }

  return response.json() as Promise<T>;
}

export async function listDocuments() {
  return request<{ documents: PdfDocument[]; total: number }>("/documents");
}

export async function uploadDocument(file: File) {
  const body = new FormData();
  body.append("file", file);
  return request<{ document_id: string; filename: string; status: string; message: string }>(
    "/documents/upload",
    { method: "POST", body }
  );
}

export async function deleteDocument(documentId: string) {
  return request<{ document_id: string; message: string }>(`/documents/${documentId}`, {
    method: "DELETE"
  });
}

export async function askDocument(documentId: string, question: string) {
  return request<{
    answer: string;
    citations: Citation[];
    model_used: string;
    document_id: string;
    question: string;
  }>("/chat/query", {
    method: "POST",
    body: JSON.stringify({ document_id: documentId, question })
  });
}

export async function streamDocumentAnswer(
  documentId: string,
  question: string,
  handlers: {
    onCitations?: (citations: Citation[]) => void;
    onToken: (token: string) => void;
    onDone?: () => void;
  }
) {
  const headers = await authHeaders();
  const response = await fetch(`${API_URL}/chat/stream`, {
    method: "POST",
    headers: {
      ...headers,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ document_id: documentId, question })
  });

  if (!response.ok || !response.body) {
    throw new Error(await response.text());
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";

    for (const event of events) {
      const eventName = event.match(/^event: (.+)$/m)?.[1];
      const data = event.match(/^data: (.+)$/m)?.[1];
      if (!eventName || !data) continue;

      const parsed = JSON.parse(data);
      if (eventName === "citations") handlers.onCitations?.(parsed);
      if (eventName === "token") handlers.onToken(parsed);
      if (eventName === "done") handlers.onDone?.();
      if (eventName === "error") throw new Error(parsed);
    }
  }
}

export function makeMessage(role: ChatMessage["role"], content: string): ChatMessage {
  return {
    id: crypto.randomUUID(),
    role,
    content
  };
}
