import modal

app = modal.App("chat-with-pdf")

chroma_volume = modal.Volume.from_name("chroma-data", create_if_missing=True)
CHROMA_MOUNT_PATH = "/chroma_data"

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("tesseract-ocr")
    .pip_install_from_requirements("requirements.txt")
    .run_python(
        [
            "from sentence_transformers import SentenceTransformer",
            "SentenceTransformer('intfloat/multilingual-e5-small')",
        ],
        secrets=[],
    )
)

secrets = [
    modal.Secret.from_name("chat-with-pdf-secrets"),
]


@app.function(
    image=image,
    secrets=secrets,
    volumes={CHROMA_MOUNT_PATH: chroma_volume},
    # Scale to zero when idle. Modal currently caps this at 20 minutes.
    scaledown_window=1200,
    max_containers=10,
    timeout=120,
    memory=2048,
)
@modal.asgi_app()
def fastapi_app():
    from app.main import app as fastapi_application

    return fastapi_application


@app.function(
    image=image,
    secrets=secrets,
    volumes={CHROMA_MOUNT_PATH: chroma_volume},
    timeout=300,
    memory=4096,
)
def run_ingestion(document_id: str, user_id: str, filename: str):
    from app.services.ingestion import ingest_document

    ingest_document(
        document_id=document_id,
        user_id=user_id,
        filename=filename,
    )
    chroma_volume.commit()
