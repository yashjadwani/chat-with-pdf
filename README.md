# PDF Chat

PDF Chat is a full-stack RAG application for uploading PDFs, asking questions in plain English, and getting answers grounded in the uploaded document with page references.

![PDF Chat architecture](docs/project-architecture.svg)

## What It Does

- Authenticates users with Supabase email/password auth.
- Uploads PDFs to a private Supabase Storage bucket.
- Extracts selectable PDF text with PyMuPDF.
- Runs OCR with Tesseract on low-text or image-heavy pages.
- Chunks pages, embeds chunks with `intfloat/multilingual-e5-small`, and stores raw text + embeddings + metadata in ChromaDB.
- Answers questions with hybrid retrieval, query expansion, reranking, neighbor chunk expansion, memory, and citation-aware LLM prompts.
- Saves chat history per user/document and logs LLM calls, query expansion calls, request timings, and latency metadata.

## Stack

| Layer | Tech |
| --- | --- |
| Frontend | Vite, React, TypeScript, Supabase JS, Lucide icons |
| Backend | FastAPI, Pydantic, Uvicorn |
| Auth | Supabase Auth |
| Database | Supabase Postgres |
| Storage | Supabase Storage |
| Vector store | ChromaDB persistent storage |
| PDF/OCR | PyMuPDF, Tesseract, pytesseract, Pillow |
| Embeddings | `intfloat/multilingual-e5-small` |
| Retrieval | Chroma dense search, BM25, RRF, BGE reranking, neighbor expansion |
| LLM | Opencode API |
| Deployment | Modal backend, Vercel-style frontend |

## Current Pipeline

### Ingestion

```text
PDF upload
-> Supabase Storage
-> documents row: processing
-> PyMuPDF page text extraction
-> OCR fallback when page text is low or image-heavy
-> RecursiveCharacterTextSplitter
-> E5 embeddings with "passage:" prefix
-> Chroma stores raw chunk text, embeddings, metadata, ids
-> documents row: ready
```

Important detail: embeddings are never converted back into text. Chroma stores the original chunk text alongside the vector, then returns the stored text after vector search.

### Chat Query Call Trace

```text
POST /chat/query
-> Supabase JWT validation
-> document ownership/status/embedding checks
-> question validation
-> chat session load/create
-> mode routing
   -> summary
   -> normal Q&A
   -> comparison/ranking
```

Normal and comparison queries:

```text
question
-> acronym expansion
-> recent chat history lookup
-> LLM query expansion
   -> contextual_query
   -> bm25_query
   -> dense_query
-> semantic retrieval cache lookup
-> dense Chroma retrieval using dense_query
-> BM25 lexical retrieval using bm25_query
-> RRF fusion and dedupe
-> BGE rerank #1 using contextual_query
-> neighbor chunk expansion
-> BGE rerank #2
-> final citations
-> optional query-term citation filter
-> LLM answer generation
-> save chat messages
-> write logs
```

Summary queries skip normal retrieval and use representative chunks across the document.

Comparison/ranking queries retrieve more context, extract structured facts, rank in Python, then generate the final grounded answer.

## Query Expansion

The app has two expansion layers:

- Deterministic acronym expansion from a global glossary and document patterns like `Long Form (ABC)`.
- Lightweight LLM query expansion for non-summary chat queries.

The LLM expansion is instructed only to rewrite search intent:

```text
Do not answer the user's question.
Do not invent facts, dates, names, clauses, obligations, amounts, page numbers, or conclusions.
```

It returns JSON:

```json
{
  "contextual_query": "Query with references resolved from recent chat history.",
  "bm25_query": "Keyword-rich query for exact lexical retrieval.",
  "dense_query": "Broader conceptual query for vector retrieval."
}
```

If expansion fails, times out, or returns invalid JSON, retrieval falls back to the acronym-expanded query.

## Retrieval and Caching

- Dense retrieval embeds the `dense_query` with the E5 `query:` prefix and searches Chroma.
- BM25 retrieves lexical matches from Chroma-stored raw chunks.
- BM25 payloads are cached in memory with `lru_cache`.
- RRF combines dense and BM25 rankings without comparing incompatible raw scores.
- BGE reranking scores `(query, chunk_text)` pairs.
- Neighbor expansion adds adjacent chunks around the strongest reranked chunks.
- A second BGE rerank decides whether those neighbor chunks belong in final citations.
- Semantic retrieval cache stores document-scoped query embeddings and final citations in memory.

Semantic cache scope:

```text
document_id + final_top_k + query_embedding similarity
```

It does not cache final LLM answers.

## Memory

Memory is configured in two layers:

- Persistent memory in Supabase `chat_sessions` and `chat_messages`.
- In-process memory through LangChain `InMemoryChatMessageHistory`.

When chat history grows beyond the configured threshold, older turns are summarized and recent turns are kept as the live tail. Query expansion uses the last 3 turns directly so it can resolve follow-up wording before retrieval.

## Observability

- `api_logs` stores LLM/provider calls: chat answers, query expansion, memory summaries, document summaries, comparison extraction, and comparison answers.
- `request_logs` stores HTTP request timings: request id, method, path, status, client-to-backend duration, and backend server duration.
- The frontend also logs request timing in the browser console with the same request id.
- The backend warms the BGE reranker in the background on startup so the first user query is less likely to pay the model load cost.

## Local Development

Backend:

```bash
cd backend
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

URLs:

```text
Backend:  http://localhost:8000
Frontend: http://localhost:5173
```

## Required Services

- Supabase project
- Supabase private storage bucket named `chat-with-pdf`
- Supabase schema from `backend/schema.sql`
- Opencode API key
- Optional LangSmith key
- Tesseract installed locally if OCR is enabled outside Modal

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
  frontend/
    src/
      components/
      lib/
      types/
      App.tsx
      styles.css
  docs/
    project-architecture.svg
```

## Deployment Notes

- Backend deploys with `backend/modal_app.py`.
- Modal installs Python requirements and `tesseract-ocr`.
- Chroma persists on a Modal volume.
- Frontend can deploy to Vercel or similar.
- Configure Supabase email redirects to the deployed frontend `/app` route.
