import logging
import os
import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import get_settings
from app.api.routes import documents, chat
from app.db.supabase import RequestLogDB
from app.services.retrieval import get_reranker_model

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)
settings = get_settings()
is_production = settings.app_env.lower() == "production"


async def warm_reranker_model() -> None:
    try:
        logger.info(f"Warming reranker model: {settings.reranker_model}")
        await asyncio.to_thread(get_reranker_model)
        logger.info("Reranker model warmed.")
    except Exception as exc:
        logger.warning(f"Reranker warmup failed; it will load on first query: {str(exc)}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info("Starting Chat with PDF backend...")
    logger.info(f"Environment: {settings.app_env}")
    logger.info(f"Opencode model: {settings.opencode_model}")
    logger.info(f"Embedding model: {settings.embedding_model}")
    logger.info(f"ChromaDB path: {settings.chroma_persist_path}")
    warmup_task = asyncio.create_task(warm_reranker_model())

    # Set LangSmith env vars
    if settings.langchain_api_key:
        os.environ["LANGCHAIN_TRACING_V2"] = str(settings.langchain_tracing_v2).lower()
        os.environ["LANGCHAIN_API_KEY"] = settings.langchain_api_key
        os.environ["LANGCHAIN_PROJECT"] = settings.langchain_project
        logger.info(f"LangSmith tracing enabled — project: {settings.langchain_project}")

    yield

    if not warmup_task.done():
        warmup_task.cancel()
    logger.info("Shutting down Chat with PDF backend...")


app = FastAPI(
    title="PDF Chat",
    description="RAG-powered document Q&A API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None if is_production else "/docs",
    redoc_url=None if is_production else "/redoc",
    openapi_url=None if is_production else "/openapi.json",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-Id", "X-Server-Duration-Ms", "X-Client-To-Backend-Ms"],
)

@app.middleware("http")
async def log_request_timing(request: Request, call_next):
    request_id = request.headers.get("x-client-request-id") or str(uuid.uuid4())
    client_sent_at = request.headers.get("x-client-sent-at-ms")
    started_at = time.perf_counter()
    received_at_ms = int(time.time() * 1000)

    try:
        response = await call_next(request)
    except Exception:
        server_duration_ms = int((time.perf_counter() - started_at) * 1000)
        RequestLogDB().insert_log(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=500,
            client_to_backend_ms=None,
            server_duration_ms=server_duration_ms,
            user_agent=request.headers.get("user-agent"),
            origin=request.headers.get("origin"),
        )
        logger.exception(
            "API request failed request_id=%s method=%s path=%s server_duration_ms=%s",
            request_id,
            request.method,
            request.url.path,
            server_duration_ms,
        )
        raise

    server_duration_ms = int((time.perf_counter() - started_at) * 1000)
    client_to_backend_ms = None
    if client_sent_at:
        try:
            client_to_backend_ms = max(0, received_at_ms - int(float(client_sent_at)))
        except ValueError:
            client_to_backend_ms = None

    response.headers["X-Request-Id"] = request_id
    response.headers["X-Server-Duration-Ms"] = str(server_duration_ms)
    if client_to_backend_ms is not None:
        response.headers["X-Client-To-Backend-Ms"] = str(client_to_backend_ms)

    logger.info(
        "API timing request_id=%s method=%s path=%s status=%s client_to_backend_ms=%s server_duration_ms=%s",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        client_to_backend_ms,
        server_duration_ms,
    )
    RequestLogDB().insert_log(
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        client_to_backend_ms=client_to_backend_ms,
        server_duration_ms=server_duration_ms,
        user_agent=request.headers.get("user-agent"),
        origin=request.headers.get("origin"),
    )
    return response


# Routers
app.include_router(documents.router)
app.include_router(chat.router)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "env": settings.app_enviorment,
        "version": "1.0.0",
    }


@app.get("/")
async def root():
    return {
        "message": "Chat with PDF API",
        "docs": None if is_production else "/docs",
    }
