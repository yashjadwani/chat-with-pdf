from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class DocumentStatus(str, Enum):
    processing = "processing"
    ready = "ready"
    failed = "failed"


class DocumentRecord(BaseModel):
    document_id: str
    user_id: str
    filename: str
    storage_path: str
    language: Optional[str] = None
    total_pages: Optional[int] = None
    status: DocumentStatus = DocumentStatus.processing
    uploaded_at: datetime
    error_message: Optional[str] = None


class DocumentUploadResponse(BaseModel):
    document_id: str
    filename: str
    status: DocumentStatus
    message: str


class DocumentListResponse(BaseModel):
    documents: list[DocumentRecord]
    total: int


class DocumentDeleteResponse(BaseModel):
    document_id: str
    message: str


class ChunkMetadata(BaseModel):
    document_id: str
    user_id: str
    page_number: int
    chunk_index: int
    language: str
    source_file: str
    text: str
