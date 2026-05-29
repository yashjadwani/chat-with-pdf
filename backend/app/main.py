import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import get_settings
from app.api.routes import documents, chat

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)
settings = get_settings()
is_production = settings.app_env.lower() == "production"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info("Starting Chat with PDF backend...")
    logger.info(f"Environment: {settings.app_env}")
    logger.info(f"Opencode model: {settings.opencode_model}")
    logger.info(f"Embedding model: {settings.embedding_model}")
    logger.info(f"ChromaDB path: {settings.chroma_persist_path}")

    # Set LangSmith env vars
    if settings.langchain_api_key:
        os.environ["LANGCHAIN_TRACING_V2"] = str(settings.langchain_tracing_v2).lower()
        os.environ["LANGCHAIN_API_KEY"] = settings.langchain_api_key
        os.environ["LANGCHAIN_PROJECT"] = settings.langchain_project
        logger.info(f"LangSmith tracing enabled — project: {settings.langchain_project}")

    yield

    logger.info("Shutting down Chat with PDF backend...")


app = FastAPI(
    title="Chat with PDF",
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
)

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
