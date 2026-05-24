# Chat with PDF — Backend

FastAPI backend deployed on Modal with ChromaDB, Supabase, and OpenRouter.

## Stack

| Layer | Choice |
|---|---|
| API Server | FastAPI on Modal |
| Vector DB | ChromaDB (Modal Volume) |
| Database | Supabase Postgres |
| File Storage | Supabase Storage |
| Embedding | intfloat/multilingual-e5-small |
| LLM Primary | DeepSeek V4 Flash (OpenRouter) |
| LLM Fallback | Llama 3.3 70B (OpenRouter) |
| Observability | LangSmith |

---

## Local Development Setup

### 1. Clone and install

```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Fill in all values in .env
```

### 3. Set up Supabase

- Create a new project at supabase.com
- Run `schema.sql` in the Supabase SQL Editor
- Create a storage bucket named `chat-with-pdf` (set to private)
- Copy your project URL and service role key into `.env`

### 4. Run locally

```bash
uvicorn app.main:app --reload --port 8000
```

API docs available at: http://localhost:8000/docs

---

## Modal Deployment

### 1. Install and authenticate Modal

```bash
pip install modal
modal setup
```

### 2. Create Modal secrets

In the Modal dashboard, create a secret named `chat-with-pdf-secrets` with these keys:

```
SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY
SUPABASE_JWT_SECRET
OPENROUTER_API_KEY
LANGCHAIN_API_KEY
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT=chat-with-pdf
ALLOWED_ORIGINS=https://your-vercel-domain.vercel.app
APP_ENV=production
```

### 3. Deploy

```bash
modal deploy modal_app.py
```

Modal will output your endpoint URL. Add this to your frontend `.env.local` as `NEXT_PUBLIC_API_URL`.

### 4. Verify deployment

```bash
curl https://your-modal-endpoint.modal.run/health
```

---

## API Endpoints

### Documents

| Method | Path | Description |
|---|---|---|
| POST | /documents/upload | Upload a PDF |
| GET | /documents | List all user documents |
| GET | /documents/{id} | Get a single document |
| DELETE | /documents/{id} | Delete document and all data |

### Chat

| Method | Path | Description |
|---|---|---|
| POST | /chat/query | Ask a question about a document |
| GET | /chat/history/{document_id} | Get conversation history |
| DELETE | /chat/history/{document_id} | Clear conversation history |

### System

| Method | Path | Description |
|---|---|---|
| GET | /health | Health check |
| GET | /docs | Swagger UI |

---

## Auth

All document and chat endpoints require a Bearer token from Supabase Auth.

```
Authorization: Bearer <supabase_jwt_token>
```

The JWT is verified against your `SUPABASE_JWT_SECRET` on every request.

---

## Project Structure

```
backend/
├── app/
│   ├── main.py              # FastAPI app, CORS, routers
│   ├── api/
│   │   ├── deps.py          # Auth dependency injection
│   │   └── routes/
│   │       ├── documents.py # Upload, list, delete
│   │       └── chat.py      # Query, history
│   ├── core/
│   │   ├── config.py        # Settings from env vars
│   │   └── security.py      # JWT verification
│   ├── services/
│   │   ├── ingestion.py     # PDF → chunks → embeddings
│   │   ├── retrieval.py     # ChromaDB query
│   │   ├── llm.py           # OpenRouter calls + fallback
│   │   └── memory.py        # Conversation memory
│   ├── models/
│   │   ├── document.py      # Pydantic schemas
│   │   └── chat.py
│   └── db/
│       ├── supabase.py      # Supabase client + CRUD
│       └── chroma.py        # ChromaDB client
├── modal_app.py             # Modal deployment config
├── schema.sql               # Supabase table + RLS setup
├── requirements.txt
└── .env.example
```
