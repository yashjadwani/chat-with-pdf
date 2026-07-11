from supabase import create_client, Client
from app.core.config import get_settings
from app.models.document import DocumentStatus
from typing import Optional
from functools import lru_cache
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)
settings = get_settings()


@lru_cache()
def get_supabase_client() -> Client:
    return create_client(
        settings.supabase_url,
        settings.supabase_service_role_key,  # service role bypasses RLS for backend ops
    )

class DocumentDB:
    def __init__(self):
        self.client = get_supabase_client()
        self.table = "documents"

    def create_document(
        self,
        document_id: str,
        user_id: str,
        filename: str,
        storage_path: str,
    ) -> dict:
        """Insert a new document record with processing status."""
        data = {
            "document_id": document_id,
            "user_id": user_id,
            "filename": filename,
            "storage_path": storage_path,
            "status": DocumentStatus.processing.value,
        }
        response = self.client.table(self.table).insert(data).execute()
        return response.data[0]

    def update_document(
        self,
        document_id: str,
        updates: dict,
        user_id: str | None = None,
    ) -> dict:
        """Update fields on a document record. Pass user_id to scope the write
        to its owner (defense-in-depth against the service role bypassing RLS)."""
        query = self.client.table(self.table).update(updates).eq("document_id", document_id)
        if user_id is not None:
            query = query.eq("user_id", user_id)
        response = query.execute()
        return response.data[0] if response.data else {}

    def set_ready(
        self,
        document_id: str,
        language: str,
        total_pages: int,
        user_id: str | None = None,
    ) -> dict:
        return self.update_document(
            document_id,
            {
                "status": DocumentStatus.ready.value,
                "language": language,
                "total_pages": total_pages,
            },
            user_id=user_id,
        )

    def set_failed(self, document_id: str, error_message: str, user_id: str | None = None) -> dict:
        return self.update_document(
            document_id,
            {
                "status": DocumentStatus.failed.value,
                "error_message": error_message,
            },
            user_id=user_id,
        )

    def get_document(self, document_id: str, user_id: str) -> Optional[dict]:
        """Fetch a single document, scoped to the user."""
        response = (
            self.client.table(self.table)
            .select("*")
            .eq("document_id", document_id)
            .eq("user_id", user_id)
            .single()
            .execute()
        )
        return response.data

    def list_documents(self, user_id: str) -> list[dict]:
        """List all documents for a user, newest first."""
        response = (
            self.client.table(self.table)
            .select("*")
            .eq("user_id", user_id)
            .order("uploaded_at", desc=True)
            .execute()
        )
        return response.data or []

    def delete_document(self, document_id: str, user_id: str) -> bool:
        """Delete a document record. Returns True if deleted."""
        response = (
            self.client.table(self.table)
            .delete()
            .eq("document_id", document_id)
            .eq("user_id", user_id)
            .execute()
        )
        return len(response.data) > 0


class StorageDB:
    def __init__(self):
        self.client = get_supabase_client()
        self.bucket = "chat-with-pdf"

    def upload_file(self, storage_path: str, file_bytes: bytes, content_type: str) -> str:
        """Upload a file to Supabase Storage. Returns the storage path."""
        self.client.storage.from_(self.bucket).upload(
            path=storage_path,
            file=file_bytes,
            file_options={"content-type": content_type},
        )
        return storage_path

    def download_file(self, storage_path: str) -> bytes:
        """Download a file from Supabase Storage."""
        response = self.client.storage.from_(self.bucket).download(storage_path)
        return response

    def delete_file(self, storage_path: str) -> bool:
        """Delete a file from Supabase Storage."""
        self.client.storage.from_(self.bucket).remove([storage_path])
        return True


class ChatDB:
    def __init__(self):
        self.client = get_supabase_client()

    def get_or_create_default_session(self, user_id: str, document_id: str) -> dict:
        """Return the default chat session for a user/document, creating it if needed."""
        existing = (
            self.client.table("chat_sessions")
            .select("*")
            .eq("user_id", user_id)
            .eq("document_id", document_id)
            .eq("is_default", True)
            .limit(1)
            .execute()
        )
        if existing.data:
            return existing.data[0]

        try:
            created = (
                self.client.table("chat_sessions")
                .insert(
                    {
                        "user_id": user_id,
                        "document_id": document_id,
                        "is_default": True,
                    }
                )
                .execute()
            )
            return created.data[0]
        except Exception:
            # A concurrent request won the race and inserted the default session
            # (the partial unique index rejects the second insert). Re-select it.
            retry = (
                self.client.table("chat_sessions")
                .select("*")
                .eq("user_id", user_id)
                .eq("document_id", document_id)
                .eq("is_default", True)
                .limit(1)
                .execute()
            )
            if retry.data:
                return retry.data[0]
            raise

    def update_summary(
        self,
        session_id: str,
        summary: str,
        user_id: str,
        document_id: str,
    ) -> None:
        self.client.table("chat_sessions").update(
            {"summary": summary, "updated_at": datetime.now(timezone.utc).isoformat()}
        ).eq("session_id", session_id).eq("user_id", user_id).eq("document_id", document_id).execute()

    def get_recent_messages(
        self,
        session_id: str,
        limit: int,
        user_id: str,
        document_id: str,
    ) -> list[dict]:
        response = (
            self.client.table("chat_messages")
            .select("*")
            .eq("session_id", session_id)
            .eq("user_id", user_id)
            .eq("document_id", document_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return list(reversed(response.data or []))

    def insert_message(
        self,
        session_id: str,
        user_id: str,
        document_id: str,
        role: str,
        content: str,
        citations: list | None = None,
        metadata: dict | None = None,
    ) -> dict:
        response = (
            self.client.table("chat_messages")
            .insert(
                {
                    "session_id": session_id,
                    "user_id": user_id,
                    "document_id": document_id,
                    "role": role,
                    "content": content,
                    "citations": citations or [],
                    "metadata": metadata or {},
                }
            )
            .execute()
        )
        return response.data[0]

    def clear_session_messages(self, session_id: str, user_id: str, document_id: str) -> None:
        self.client.table("chat_messages").delete().eq("session_id", session_id).eq(
            "user_id", user_id
        ).eq("document_id", document_id).execute()
        self.client.table("chat_sessions").update(
            {"summary": None, "updated_at": datetime.now(timezone.utc).isoformat()}
        ).eq("session_id", session_id).eq("user_id", user_id).eq("document_id", document_id).execute()


class ApiLogDB:
    def __init__(self):
        self.client = get_supabase_client()

    def insert_log(
        self,
        purpose: str,
        model: str,
        status: str,
        provider: str = "opencode",
        user_id: str | None = None,
        document_id: str | None = None,
        session_id: str | None = None,
        user_prompt: str | None = None,
        latency_ms: int | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
        request_metadata: dict | None = None,
        response_metadata: dict | None = None,
        response_content: str | None = None,
        raw_response: dict | list | None = None,
        error_message: str | None = None,
    ) -> None:
        try:
            self.client.table("api_logs").insert(
                {
                    "user_id": user_id,
                    "document_id": document_id,
                    "session_id": session_id,
                    "purpose": purpose,
                    "provider": provider,
                    "model": model,
                    "status": status,
                    "user_prompt": user_prompt,
                    "latency_ms": latency_ms,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                    "request_metadata": request_metadata or {},
                    "response_metadata": response_metadata or {},
                    "response_content": response_content,
                    "raw_response": raw_response,
                    "error_message": error_message,
                }
            ).execute()
        except Exception as exc:
            logger.warning(f"Failed to write API log: {str(exc)}")


class RequestLogDB:
    def __init__(self):
        self.client = get_supabase_client()

    def insert_log(
        self,
        request_id: str,
        method: str,
        path: str,
        status_code: int | None = None,
        client_to_backend_ms: int | None = None,
        server_duration_ms: int | None = None,
        user_agent: str | None = None,
        origin: str | None = None,
    ) -> None:
        try:
            self.client.table("request_logs").insert(
                {
                    "request_id": request_id,
                    "method": method,
                    "path": path,
                    "status_code": status_code,
                    "client_to_backend_ms": client_to_backend_ms,
                    "server_duration_ms": server_duration_ms,
                    "user_agent": user_agent,
                    "origin": origin,
                }
            ).execute()
        except Exception as exc:
            logger.warning(f"Failed to write request log: {str(exc)}")
