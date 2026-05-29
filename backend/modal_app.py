import modal

# --- Modal app definition ---
app = modal.App("chat-with-pdf")

# Persistent volume for ChromaDB — survives container restarts
chroma_volume = modal.Volume.from_name("chroma-data", create_if_missing=True)
CHROMA_MOUNT_PATH = "/chroma_data"

# Container image with all dependencies
image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("tesseract-ocr")
    .pip_install_from_requirements("requirements.txt")
    .add_local_dir("app", remote_path="/root/app", copy=True)
    # Pre-download the embedding model during image build
    .run_commands(
        "python -c \"from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/multilingual-e5-small')\"",
        secrets=[],
    )
    .run_commands(
        "python -c \"from sentence_transformers import CrossEncoder; CrossEncoder('BAAI/bge-reranker-base')\"",
        secrets=[],
    )
    .run_commands("python -m nltk.downloader stopwords")
)

# Secrets from Modal dashboard — set these before deploying
secrets = [
    modal.Secret.from_name("chat-with-pdf-secrets"),
]

modal_env = {
    "APP_ENV": "production",
    "APP_ENVIORMENT": "production",
    "CHROMA_PERSIST_PATH": CHROMA_MOUNT_PATH,
    "RUN_INGESTION_ON_MODAL": "true",
    "MODAL_APP_NAME": "chat-with-pdf",
    "MODAL_INGESTION_FUNCTION_NAME": "run_ingestion",
    "MODAL_CHROMA_VOLUME_NAME": "chroma-data",
    "RERANKER_MODEL": "BAAI/bge-reranker-base",
}


@app.function(
    image=image,
    env=modal_env,
    secrets=secrets,
    volumes={CHROMA_MOUNT_PATH: chroma_volume},
    # Scale to zero when idle. Modal currently caps this at 20 minutes.
    scaledown_window=600,
    max_containers=3,
    # Timeout for individual requests (seconds)
    timeout=300,
    # Memory allocation — embedding model needs ~500MB
    memory=4096,
)
@modal.asgi_app()
def fastapi_app():
    """
    Deploy FastAPI as a Modal ASGI web endpoint.
    The ChromaDB volume is mounted at /chroma_data.
    All secrets are injected as environment variables.
    """
    from app.main import app as fastapi_application
    return fastapi_application


# --- Separate ingestion function for heavy processing ---
# Called by the upload endpoint as a background task
# Can be invoked directly from FastAPI via modal.Function.lookup()

@app.function(
    image=image,
    env=modal_env,
    secrets=secrets,
    volumes={CHROMA_MOUNT_PATH: chroma_volume},
    timeout=900,  # 15 min for OCR-heavy PDFs
    memory=4096,  # More memory for OCR and embedding large documents
    name="run_ingestion",
)
def run_ingestion(document_id: str, user_id: str, filename: str):
    """
    Standalone Modal function for document ingestion.
    Runs in its own container — heavy compute isolated from the API server.
    """
    from app.services.ingestion import ingest_document
    ingest_document(
        document_id=document_id,
        user_id=user_id,
        filename=filename,
    )
    # Commit volume changes so ChromaDB writes persist
    chroma_volume.commit()

@app.function(
    image=image,
    env=modal_env,
    secrets=secrets,
    volumes={CHROMA_MOUNT_PATH: chroma_volume},
    timeout=120,
    memory=2048,
)
def inspect_chroma(document_id: str):
    from app.db.chroma import ChromaStore

    store = ChromaStore()
    print("Collection count:", store.collection.count())

    results = store.collection.get(
        where={"document_id": document_id},
        limit=5,
        include=["documents", "metadatas"],
    )

    print("IDs:", results.get("ids"))
    print("Metadatas:", results.get("metadatas"))
    print("Documents:", results.get("documents"))
