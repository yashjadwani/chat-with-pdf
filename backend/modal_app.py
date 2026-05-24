import modal
import os

# --- Modal app definition ---
app = modal.App("chat-with-pdf")

# Persistent volume for ChromaDB — survives container restarts
chroma_volume = modal.Volume.from_name("chroma-data", create_if_missing=True)
CHROMA_MOUNT_PATH = "/chroma_data"

# Container image with all dependencies
image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install_from_requirements("requirements.txt")
    # Pre-download the embedding model during image build
    .run_python(
        [
            "from sentence_transformers import SentenceTransformer",
            "SentenceTransformer('intfloat/multilingual-e5-small')",
        ],
        secrets=[],
    )
)

# Secrets from Modal dashboard — set these before deploying
secrets = [
    modal.Secret.from_name("chat-with-pdf-secrets"),
]


@app.function(
    image=image,
    secrets=secrets,
    volumes={CHROMA_MOUNT_PATH: chroma_volume},
    # Keep one container warm at all times — avoids cold start on first request
    min_concurrency=1,
    max_concurrency=10,
    # Timeout for individual requests (seconds)
    timeout=120,
    # Memory allocation — embedding model needs ~500MB
    memory=2048,
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
    secrets=secrets,
    volumes={CHROMA_MOUNT_PATH: chroma_volume},
    timeout=300,  # 5 min for large PDFs
    memory=4096,  # More memory for embedding large documents
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
