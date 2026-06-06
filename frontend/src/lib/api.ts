import { getAccessToken } from "./supabase";
import type { ChatMessage, PdfDocument, Citation, PersistedChatMessage } from "../types";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

function createRequestTiming() {
  return {
    requestId: crypto.randomUUID(),
    clientSentAtMs: Date.now(),
    startedAt: performance.now()
  };
}

function timingHeaders(timing: ReturnType<typeof createRequestTiming>) {
  return {
    "X-Client-Request-Id": timing.requestId,
    "X-Client-Sent-At-Ms": String(timing.clientSentAtMs)
  };
}

function logApiTiming(path: string, timing: ReturnType<typeof createRequestTiming>, response: Response) {
  const clientDurationMs = Math.round(performance.now() - timing.startedAt);
  const serverDurationMs = response.headers.get("X-Server-Duration-Ms");
  const clientToBackendMs = response.headers.get("X-Client-To-Backend-Ms");
  const requestId = response.headers.get("X-Request-Id") ?? timing.requestId;

  console.info("[api timing]", {
    path,
    requestId,
    status: response.status,
    clientDurationMs,
    clientToBackendMs: clientToBackendMs ? Number(clientToBackendMs) : null,
    serverDurationMs: serverDurationMs ? Number(serverDurationMs) : null
  });
}

async function authHeaders() {
  const token = await getAccessToken();
  if (!token) {
    throw new Error("You need to sign in first.");
  }
  return { Authorization: `Bearer ${token}` };
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = await authHeaders();
  const timing = createRequestTiming();
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      ...headers,
      ...timingHeaders(timing),
      ...(init.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...init.headers
    }
  });
  logApiTiming(path, timing, response);

  if (!response.ok) {
    const message = await response.text();
    throw new Error(parseApiError(message) || "Request failed.");
  }

  return response.json() as Promise<T>;
}

function parseApiError(message: string) {
  if (!message) return "";

  try {
    const parsed = JSON.parse(message);
    return typeof parsed.detail === "string" ? parsed.detail : message;
  } catch {
    return message;
  }
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

export async function getChatHistory(documentId: string) {
  return request<{ session_id: string; messages: PersistedChatMessage[] }>(
    `/chat/history/${documentId}`
  );
}

export async function clearChatHistory(documentId: string) {
  return request<{ message: string; session_id: string }>(`/chat/history/${documentId}`, {
    method: "DELETE"
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
  const timing = createRequestTiming();
  const response = await fetch(`${API_URL}/chat/stream`, {
    method: "POST",
    headers: {
      ...headers,
      ...timingHeaders(timing),
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ document_id: documentId, question })
  });

  if (!response.ok || !response.body) {
    logApiTiming("/chat/stream", timing, response);
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
  logApiTiming("/chat/stream", timing, response);
}

export function makeMessage(role: ChatMessage["role"], content: string): ChatMessage {
  return {
    id: crypto.randomUUID(),
    role,
    content
  };
}
