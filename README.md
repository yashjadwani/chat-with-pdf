# PDF Chat

PDF Chat is a full-stack RAG application for uploading PDFs, asking questions in plain English, and getting answers grounded in the uploaded document.

The app is built as a learning-focused MVP with a modern Vite frontend, FastAPI backend, Supabase Auth/Storage/Postgres, ChromaDB, OCR support, hybrid retrieval, chat memory, and LLM logging.

## Features

- Supabase email/password auth
- Portfolio-ready email verification screen
- Document upload and processing status
- Private Supabase Storage bucket
- PDF text extraction with PyMuPDF
- OCR fallback for scanned or image-heavy pages
- ChromaDB vector storage with raw chunks and embeddings
- Hybrid retrieval:
  - dense semantic search
  - BM25 keyword search
  - merge and dedupe
  - exact term boosting
  - metadata quality scoring
  - final reranking
- Chat answers with page references
- Saved chat history per user and document
- Conversation summary memory for long chats
- API logs for LLM calls, summary calls, response content, raw responses, and latency
- Modern light/dark frontend UI

## Project Structure

```text
chat-with-pdf/
  backend/
    app/
      api/
      core/
      db/
      models/
      services/
    modal_app.py
    requirements.txt
    schema.sql
    README.md
  frontend/
    src/
      components/
      lib/
      types/
      App.tsx
      styles.css
    package.json
    README.md
```

## Stack

| Layer | Tech |
| --- | --- |
| Frontend | Vite, React, TypeScript, Supabase JS, Lucide icons |
| Backend | Python, FastAPI, Pydantic, Uvicorn |
| Auth | Supabase Auth |
| Database | Supabase Postgres |
| Storage | Supabase Storage |
| Vector DB | ChromaDB |
| OCR | Tesseract, pytesseract, Pillow |
| Embeddings | `intfloat/multilingual-e5-small` |
| Retrieval | Dense vector search + BM25 + reranking |
| LLM | Opencode API |
| Deployment | Modal backend, Vercel-style frontend |

## Local Development

### Backend

```bash
cd backend
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Backend docs:

```text
http://localhost:8000/docs
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend dev server:

```text
http://localhost:5173
```

## Required Services

You need:

- Supabase project
- Supabase private storage bucket named `chat-with-pdf`
- Supabase schema from `backend/schema.sql`
- Opencode API key
- Optional LangSmith key
- Tesseract installed locally if OCR is enabled outside Modal

## Environment Overview

Backend `.env` includes Supabase service credentials, Opencode config, Chroma path, CORS origins, OCR settings, and LangSmith config.

Frontend `.env` includes:

```env
VITE_SUPABASE_URL=
VITE_SUPABASE_ANON_KEY=
VITE_API_URL=http://localhost:8000
```

## RAG Architecture

```text
Upload PDF
  -> Supabase Storage
  -> document row: processing
  -> PyMuPDF text extraction
  -> OCR when needed
  -> chunking
  -> embeddings
  -> Chroma stores raw chunks + metadata + embeddings
  -> document row: ready

Question
  -> Supabase JWT verification
  -> dense Chroma retrieval
  -> BM25 keyword retrieval
  -> merge/dedupe
  -> rerank
  -> LLM with final context
  -> answer + page references
  -> saved chat history + API log
```

## Deployment Notes

- Backend deploys with `backend/modal_app.py`.
- Modal installs Python requirements and the `tesseract-ocr` system package.
- Chroma persists on a Modal volume.
- Frontend can be deployed to Vercel or similar.
- Add the deployed backend URL to `VITE_API_URL`.

## Current MVP Status

Implemented:

- Auth
- Document upload/list/delete
- Ingestion with OCR
- Hybrid retrieval
- Chat and saved history
- LLM call logging
- Modern frontend with dark mode

Planned or optional:

- Persistent BM25 index or Postgres full-text search
- More advanced OCR/image captioning for diagrams
- Cross-encoder reranker
- Admin analytics dashboard
