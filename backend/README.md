# PDF Chat Backend

FastAPI backend for the PDF Chat RAG application. It handles authenticated document upload, ingestion, OCR, hybrid retrieval, chat memory, LLM calls, and API logging.

## Stack

| Area | Tooling |
| --- | --- |
| API | FastAPI, Uvicorn, Pydantic |
| Auth | Supabase Auth JWT |
| Database | Supabase Postgres |
| Storage | Supabase Storage |
| Vector store | ChromaDB persistent storage |
| PDF processing | PyMuPDF |
| OCR | Tesseract, pytesseract, Pillow |
| Embeddings | `intfloat/multilingual-e5-small` |
| Retrieval | Chroma dense retrieval + BM25 lexical retrieval + BGE reranking |
| LLM gateway | Opencode API |
| Memory | Supabase chat tables + LangChain Core in-memory history helpers |
| Observability | LangSmith, `api_logs` table |
| Deployment | Modal |

## RAG Flow

1. Upload PDF to Supabase Storage.
2. Create a document row in Supabase with `processing` status.
3. Background ingestion downloads the file.
4. PyMuPDF extracts selectable page text.
5. OCR runs on low-text pages or pages with images.
6. Text is chunked with `RecursiveCharacterTextSplitter`.
7. Chunks are embedded with multilingual E5.
8. Chroma stores raw chunk text, embeddings, and metadata.
9. Document status changes to `ready`.
10. Chat queries use hybrid retrieval:
    - dense vector top 50 from Chroma
    - BM25 top 50 from Chroma-stored raw chunks
    - merge and deduplicate
    - acronym expansion from custom glossary and document patterns
    - BGE cross-encoder reranking
    - final top chunks passed to the answer pipeline

## Answer Modes

`POST /chat/query` routes questions into one of three paths:

| Mode | Trigger | Flow |
| --- | --- | --- |
| Normal Q&A | Default | retrieve -> rerank -> generate |
| Document summary | summarize, summary, overview, key takeaways | representative chunks across the document -> generate summary |
| Comparison/ranking | best, highest, lowest, most, compare, rank, better, worse, cost, time, score, etc. | retrieve broader context -> extract structured facts -> compare/rank in Python -> generate final answer |

Streaming currently uses the normal retrieval/generation path.

## Acronym Expansion

`app/services/acronyms.py` expands query terms before retrieval using:

- custom global glossary
- FlashText
- parenthetical document patterns like `Adjusted Rand Index (ARI)`

The current glossary includes ARI, AUC, ROC, GMM, SVM, KNN, EM, and CV. The implementation intentionally avoids required `spacy`/`scispacy` dependencies so local Python 3.13 installs stay stable.

## Local Setup

```bash
cd backend
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

On macOS/Linux:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Environment

Create `backend/.env` from `.env.example` and fill in your values.

Important variables:

```env
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_JWT_AUDIENCE=authenticated
SUPABASE_JWT_ISSUER=
OPENCODE_API_KEY=
OPENCODE_BASE_URL=https://opencode.ai/zen/v1
OPENCODE_MODEL=deepseek-v4-flash-free
CHROMA_PERSIST_PATH=./chroma_data
CHROMA_COLLECTION_NAME=chat_with_pdf
RERANKER_MODEL=BAAI/bge-reranker-base
ALLOWED_ORIGINS=http://localhost:5173
ENABLE_OCR=true
OCR_MIN_TEXT_CHARS=80
TESSERACT_CMD=
```

For local Windows OCR, set `TESSERACT_CMD` if Tesseract is not on PATH:

```env
TESSERACT_CMD=C:\Users\yashj\AppData\Local\Programs\Tesseract-OCR\tesseract.exe
```

For Modal/Linux, `modal_app.py` installs `tesseract-ocr`, so the binary should be available on PATH.

## Supabase Setup

1. Create a Supabase project.
2. Enable email/password auth.
3. Run `backend/schema.sql` in the Supabase SQL Editor.
4. Create a private storage bucket named `chat-with-pdf`.
5. Add storage policies so users can access only their own folder.

Storage path format:

```text
{user_id}/{document_id}/{filename}
```

## Run Locally

From the `backend` folder:

```bash
uvicorn app.main:app --reload --port 8000
```

Open:

```text
http://localhost:8000/docs
```

## API Summary

### Documents

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/documents/upload` | Upload a PDF and queue ingestion |
| `GET` | `/documents` | List documents for the current user |
| `GET` | `/documents/{document_id}` | Get one document |
| `DELETE` | `/documents/{document_id}` | Delete document, file, chunks, and chats |

### Chat

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/chat/query` | Ask a document question |
| `POST` | `/chat/stream` | Stream a document answer |
| `GET` | `/chat/history/{document_id}` | Load saved chat history |
| `DELETE` | `/chat/history/{document_id}` | Clear saved chat history |

### System

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Health check |
| `GET` | `/docs` | Swagger UI |

All protected endpoints require:

```http
Authorization: Bearer <supabase_access_token>
```

## Modal Deployment

`modal_app.py` builds the backend image from `requirements.txt`, installs Tesseract, pre-downloads the embedding and reranker models, downloads NLTK stopwords, and mounts a persistent Chroma volume.

Deploy:

```bash
cd backend
modal deploy modal_app.py
```

Modal secret name expected:

```text
chat-with-pdf-secrets
```

The secret should include your Supabase, Opencode, LangSmith, CORS, and environment variables.

## Notes

- BM25 cache is in memory and rebuilds from Chroma on cache miss.
- Chroma stores both raw chunk text and embeddings.
- OCR increases ingestion time, especially on image-heavy PDFs.
- `api_logs` stores LLM call metadata, response content, raw provider responses, latency, and token usage when available.
- Logged purposes include `chat_answer`, `memory_summary`, `document_summary`, `comparison_extraction`, and `comparison_answer`.
