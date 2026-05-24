from supabase import create_client, Client
from app.core.config import get_settings
from app.models.document import DocumentRecord, DocumentStatus
from typing import Optional
from functools import lru_cache
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
    ) -> dict:
        """Update fields on a document record."""
        response = (
            self.client.table(self.table)
            .update(updates)
            .eq("document_id", document_id)
            .execute()
        )
        return response.data[0] if response.data else {}

    def set_ready(
        self,
        document_id: str,
        language: str,
        total_pages: int,
    ) -> dict:
        return self.update_document(
            document_id,
            {
                "status": DocumentStatus.ready.value,
                "language": language,
                "total_pages": total_pages,
            },
        )

    def set_failed(self, document_id: str, error_message: str) -> dict:
        return self.update_document(
            document_id,
            {
                "status": DocumentStatus.failed.value,
                "error_message": error_message,
            },
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
