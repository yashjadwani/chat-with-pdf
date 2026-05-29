from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    # Supabase
    supabase_url: str
    supabase_service_role_key: str
    supabase_jwt_audience: str = "authenticated"
    supabase_jwt_issuer: str = ""
    app_enviorment:str

    # OpenRouter
    openrouter_api_key: str
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_llm_primary: str = "deepseek/deepseek-v4-flash:free"
    openrouter_llm_fallback: str = "meta-llama/llama-3.3-70b-instruct:free"
    
    # OpenCode
    opencode_api_key:str
    opencode_base_url: str ="https://opencode.ai/zen/v1"
    opencode_model: str = "deepseek-v4-flash-free"
    
    # Embedding
    embedding_model: str = "intfloat/multilingual-e5-small"

    # ChromaDB
    chroma_persist_path: str = "./chroma_data"
    chroma_collection_name: str = "chat_with_pdf"

    # Chunking
    chunk_size: int = 900
    chunk_overlap: int = 180
    
    # OCR
    enable_ocr: bool = True
    ocr_min_text_chars: int = 80
    tesseract_cmd: str = ""

    # Retrieval
    retrieval_top_k: int = 5
    retrival_k:int = 50
    reranker_model: str = "BAAI/bge-reranker-base"

    # Memory
    memory_window_size: int = 10
    summary_threshold:int = 20   # summarise when history exceeds this many messages
    keep_recent:int = 2   

    # LangSmith
    langchain_tracing_v2: bool = True
    langchain_api_key: str = ""
    langchain_project: str = "chat-with-pdf"

    # App
    app_env: str = "development"
    run_ingestion_on_modal: bool = False
    modal_app_name: str = "chat-with-pdf"
    modal_ingestion_function_name: str = "run_ingestion"
    modal_chroma_volume_name: str = "chroma-data"
    allowed_origins: str = "http://localhost:5173"
    max_file_size_mb: int = 50

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",")]

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def expected_supabase_jwt_issuer(self) -> str:
        if self.supabase_jwt_issuer:
            return self.supabase_jwt_issuer.rstrip("/")
        return f"{self.supabase_url.rstrip('/')}/auth/v1"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
