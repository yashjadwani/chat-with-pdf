from datetime import UTC, datetime
import io
import fitz  # PyMuPDF
import uuid
import logging
from langdetect import detect, LangDetectException
from langchain_text_splitters import RecursiveCharacterTextSplitter
from PIL import Image
import pytesseract
from sentence_transformers import SentenceTransformer
from app.core.config import get_settings
from app.db.chroma import ChromaStore
from app.db.supabase import DocumentDB, StorageDB

logger = logging.getLogger(__name__)
settings = get_settings()
if settings.tesseract_cmd:
    pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd

# Load embedding model once at module level — Modal keeps this warm
_embedding_model: SentenceTransformer | None = None


def get_embedding_model() -> SentenceTransformer:
    global _embedding_model
    if _embedding_model is None:
        logger.info(f"Loading embedding model: {settings.embedding_model}")
        _embedding_model = SentenceTransformer(settings.embedding_model)
    return _embedding_model


def detect_language(text: str) -> str:
    """Detect language from the first 500 characters of text."""
    try:
        sample = text[:500].strip()
        if not sample:
            return "unknown"
        return detect(sample)
    except LangDetectException:
        return "unknown"


def page_has_images(page: fitz.Page) -> bool:
    return len(page.get_images(full=True)) > 0


def ocr_page(page: fitz.Page) -> str:
    pix = page.get_pixmap(dpi=200)
    image = Image.open(io.BytesIO(pix.tobytes("png")))
    return pytesseract.image_to_string(image)


def extract_text_by_page(pdf_bytes: bytes) -> list[dict]:
    """
    Extract text from PDF page by page using PyMuPDF.
    Runs OCR for scanned/low-text pages or pages containing images.
    """
    pages = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text("text").strip()
        has_images = page_has_images(page)
        needs_ocr = settings.enable_ocr and (
            len(text) < settings.ocr_min_text_chars or has_images
        )

        ocr_text = ""
        if needs_ocr:
            try:
                ocr_text = ocr_page(page).strip()
            except Exception as exc:
                logger.warning(f"OCR failed on page {page_num + 1}: {str(exc)}")

        combined_text = text
        if ocr_text:
            combined_text += "\n\n[OCR text]\n" + ocr_text

        if combined_text.strip():
            pages.append({
                "page_number": page_num + 1,  # 1-indexed
                "text": combined_text.strip(),
                "has_images": has_images,
                "used_ocr": bool(ocr_text),
                "text_chars": len(text),
                "ocr_chars": len(ocr_text),
                "source_type": "mixed" if text and ocr_text else "ocr" if ocr_text else "text",
            })

    doc.close()
    return pages


def chunk_pages(
    pages: list[dict],
    document_id: str,
    user_id: str,
    language: str,
    source_file: str,
) -> tuple[list[str], list[dict], list[str]]:
    """
    Chunk page texts using RecursiveCharacterTextSplitter.
    Returns (texts, metadatas, ids) — parallel lists ready for ChromaDB.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        length_function=len,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    all_texts = []
    all_metadatas = []
    all_ids = []
    global_chunk_index = 0

    for page in pages:
        chunks = splitter.split_text(page["text"])
        for chunk_text in chunks:
            if not chunk_text.strip():
                continue

            chunk_id = f"{document_id}_{global_chunk_index}"
            metadata = {
                "document_id": document_id,
                "user_id": user_id,
                "page_number": page["page_number"],
                "chunk_index": global_chunk_index,
                "language": language,
                "source_file": source_file,
                "is_active": True,
                "created_at": datetime.now(UTC).isoformat(),
                "word_count": len(chunk_text.split()),
                "text_chars": len(chunk_text),
                "source_type": page.get("source_type", "text"),
                "has_images": bool(page.get("has_images", False)),
                "used_ocr": bool(page.get("used_ocr", False)),
                "page_text_chars": int(page.get("text_chars", 0)),
                "page_ocr_chars": int(page.get("ocr_chars", 0)),
            }

            all_texts.append(chunk_text)
            all_metadatas.append(metadata)
            all_ids.append(chunk_id)
            global_chunk_index += 1

    return all_texts, all_metadatas, all_ids


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts using multilingual-e5-small."""
    model = get_embedding_model()
    # multilingual-e5 expects "passage: " prefix for document chunks
    prefixed = [f"passage: {t}" for t in texts]
    embeddings = model.encode(prefixed, normalize_embeddings=True)
    return embeddings.tolist()


def embed_query(query: str) -> list[float]:
    """Embed a single query string. Uses 'query: ' prefix for e5 models."""
    model = get_embedding_model()
    embedding = model.encode(f"query: {query}", normalize_embeddings=True)
    return embedding.tolist()


def ingest_document(document_id: str, user_id: str, filename: str) -> None:
    """
    Full ingestion pipeline for one document.
    Called as a background Modal job after upload.

    Steps:
    1. Download PDF from Supabase Storage
    2. Extract text by page with PyMuPDF
    3. Detect language
    4. Chunk with RecursiveCharacterTextSplitter
    5. Embed with multilingual-e5-small
    6. Store in ChromaDB
    7. Update Postgres status to ready
    """
    doc_db = DocumentDB()
    storage_db = StorageDB()
    chroma_store = ChromaStore()

    try:
        logger.info(f"Starting ingestion for document {document_id}")
        document = doc_db.get_document(document_id=document_id, user_id=user_id)
        storage_path = (
            document["storage_path"]
            if document and document.get("storage_path")
            else f"{user_id}/{document_id}/{filename}"
        )
        logger.info(f"Using storage path for ingestion: {storage_path}")

        # Step 1 — Download PDF
        pdf_bytes = storage_db.download_file(storage_path)
        logger.info(f"Downloaded {len(pdf_bytes)} bytes")

        # Step 2 — Extract text by page
        pages = extract_text_by_page(pdf_bytes)
        total_pages = pages[-1]["page_number"] if pages else 0
        logger.info(f"Extracted {len(pages)} pages with text")

        if not pages:
            raise ValueError("PDF contains no extractable text. It may be scanned or image-only.")

        # Step 3 — Detect language from first page
        full_text_sample = " ".join([p["text"] for p in pages[:3]])
        language = detect_language(full_text_sample)
        logger.info(f"Detected language: {language}")

        # Step 4 — Chunk
        texts, metadatas, ids = chunk_pages(
            pages=pages,
            document_id=document_id,
            user_id=user_id,
            language=language,
            source_file=filename,
        )
        logger.info(f"Created {len(texts)} chunks")

        # Step 5 — Embed
        embeddings = embed_texts(texts)
        logger.info(f"Embedded {len(embeddings)} chunks")

        # Step 6 — Store in ChromaDB
        chroma_store.add_chunks(
            chunk_texts=texts,
            embeddings=embeddings,
            metadatas=metadatas,
            ids=ids,
        )
        logger.info(f"Chroma collection count after ingest: {chroma_store.collection.count()}")
        from app.services.retrieval import clear_bm25_cache
        clear_bm25_cache(document_id)

        # Step 7 — Update Postgres to ready
        doc_db.set_ready(
            document_id=document_id,
            language=language,
            total_pages=total_pages,
            user_id=user_id,
        )
        logger.info(f"Ingestion complete for document {document_id}")

    except Exception as e:
        logger.error(f"Ingestion failed for {document_id}: {str(e)}")
        doc_db.set_failed(document_id=document_id, error_message=str(e), user_id=user_id)
        raise
