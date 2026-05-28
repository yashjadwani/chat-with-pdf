import uuid
import logging
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks, status
from app.api.deps import get_current_user_id
from app.core.config import get_settings
from app.db.supabase import DocumentDB, StorageDB
from app.db.chroma import ChromaStore
from app.models.document import (
    DocumentUploadResponse,
    DocumentListResponse,
    DocumentDeleteResponse,
    DocumentStatus,
)
from app.services.ingestion import ingest_document
from app.services.retrieval import clear_bm25_cache

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(prefix="/documents", tags=["documents"])

ALLOWED_CONTENT_TYPES = {"application/pdf"}


def queue_ingestion(
    background_tasks: BackgroundTasks,
    document_id: str,
    user_id: str,
    filename: str,
) -> None:
    if settings.app_env.lower() == "production":
        import modal

        modal.Function.from_name("chat-with-pdf", "run_ingestion").spawn(
            document_id,
            user_id,
            filename,
        )
        logger.info(f"Spawned Modal ingestion job for document {document_id}")
        return

    background_tasks.add_task(
        ingest_document,
        document_id=document_id,
        user_id=user_id,
        filename=filename,
    )


@router.post("/upload", response_model=DocumentUploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
):
    """
    Upload a PDF document.
    - Validates file type and size
    - Saves to Supabase Storage
    - Creates Postgres record with status 'processing'
    - Triggers ingestion pipeline as a background task
    - Returns immediately with document_id
    """
    # Validate content type
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Only PDF files are supported. Received: {file.content_type}",
        )

    # Read file and validate size
    file_bytes = await file.read()
    if len(file_bytes) > settings.max_file_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum size is {settings.max_file_size_mb}MB.",
        )

    if len(file_bytes) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    document_id = str(uuid.uuid4())
    filename = file.filename or f"{document_id}.pdf"
    storage_path = f"{user_id}/{document_id}/{filename}"

    doc_db = DocumentDB()
    storage_db = StorageDB()

    # Upload to Supabase Storage
    try:
        storage_db.upload_file(
            storage_path=storage_path,
            file_bytes=file_bytes,
            content_type="application/pdf",
        )
    except Exception as e:
        logger.error(f"Storage upload failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload file to storage.",
        )

    # Create Postgres record
    try:
        doc_db.create_document(
            document_id=document_id,
            user_id=user_id,
            filename=filename,
            storage_path=storage_path,
        )
    except Exception as e:
        logger.error(f"DB record creation failed: {str(e)}")
        # Clean up storage if DB write fails
        try:
            storage_db.delete_file(storage_path)
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create document record.",
        )

    # Trigger ingestion in background
    queue_ingestion(
        background_tasks=background_tasks,
        document_id=document_id,
        user_id=user_id,
        filename=filename,
    )

    logger.info(f"Upload accepted for document {document_id}, ingestion queued")

    return DocumentUploadResponse(
        document_id=document_id,
        filename=filename,
        status=DocumentStatus.processing,
        message="Document uploaded successfully. Processing will complete shortly.",
    )


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    user_id: str = Depends(get_current_user_id),
):
    """List all documents for the authenticated user, newest first."""
    doc_db = DocumentDB()
    documents = doc_db.list_documents(user_id=user_id)

    return DocumentListResponse(
        documents=documents,
        total=len(documents),
    )


@router.get("/{document_id}")
async def get_document(
    document_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Get a single document by ID, scoped to the authenticated user."""
    doc_db = DocumentDB()
    document = doc_db.get_document(document_id=document_id, user_id=user_id)

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    return document


@router.delete("/{document_id}", response_model=DocumentDeleteResponse)
async def delete_document(
    document_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """
    Delete a document and all associated data:
    - Removes chunks from ChromaDB
    - Removes file from Supabase Storage
    - Removes record from Postgres
    """
    doc_db = DocumentDB()
    storage_db = StorageDB()
    chroma_store = ChromaStore()

    # Verify document exists and belongs to user
    document = doc_db.get_document(document_id=document_id, user_id=user_id)
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    errors = []

    # Delete from ChromaDB
    try:
        chroma_store.delete_document_chunks(document_id=document_id)
        clear_bm25_cache(document_id)
    except Exception as e:
        logger.error(f"ChromaDB delete failed for {document_id}: {str(e)}")
        errors.append("vector store")

    # Delete from Supabase Storage
    try:
        storage_db.delete_file(document["storage_path"])
    except Exception as e:
        logger.error(f"Storage delete failed for {document_id}: {str(e)}")
        errors.append("file storage")

    # Delete from Postgres
    try:
        doc_db.delete_document(document_id=document_id, user_id=user_id)
    except Exception as e:
        logger.error(f"DB delete failed for {document_id}: {str(e)}")
        errors.append("database")

    if errors:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Partial deletion — errors in: {', '.join(errors)}",
        )

    return DocumentDeleteResponse(
        document_id=document_id,
        message="Document and all associated data deleted successfully.",
    )
