from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Supabase
    supabase_url: str
    supabase_service_role_key: str
    supabase_jwt_secret: str

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
    chroma_persist_path: str = "/chroma_data"
    chroma_collection_name: str = "chat_with_pdf"

    # Chunking
    chunk_size: int = 512
    chunk_overlap: int = 50

    # Retrieval
    retrieval_top_k: int = 5

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
    allowed_origins: str = "http://localhost:3000"
    max_file_size_mb: int = 50

    class Config:
        env_file = ".env"
        case_sensitive = False

    @property
    def allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",")]

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024


@lru_cache()
def get_settings() -> Settings:
    return Settings()
