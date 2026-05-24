import chromadb
from chromadb.config import Settings as ChromaSettings
from app.core.config import get_settings
from functools import lru_cache
import logging

logger = logging.getLogger(__name__)
settings = get_settings()


@lru_cache()
def get_chroma_client() -> chromadb.ClientAPI:
    """
    Returns a persistent ChromaDB client.
    In Modal, chroma_persist_path points to a mounted Modal Volume.
    This ensures vectors survive container restarts.
    """
    client = chromadb.PersistentClient(
        path=settings.chroma_persist_path,
        settings=ChromaSettings(
            anonymized_telemetry=False,
            allow_reset=False,
        ),
    )
    return client


def get_collection() -> chromadb.Collection:
    """Get or create the main ChromaDB collection."""
    client = get_chroma_client()
    collection = client.get_or_create_collection(
        name=settings.chroma_collection_name,
        metadata={"hnsw:space": "cosine"},  # cosine similarity for embeddings
    )
    return collection


class ChromaStore:
    def __init__(self):
        self.collection = get_collection()

    def add_chunks(
        self,
        chunk_texts: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
        ids: list[str],
    ) -> None:
        """
        Store embedded chunks in ChromaDB.
        ids must be unique per chunk — use document_id + chunk_index.
        """
        self.collection.add(
            documents=chunk_texts,
            embeddings=embeddings,
            metadatas=metadatas,
            ids=ids,
        )
        logger.info(f"Stored {len(chunk_texts)} chunks in ChromaDB")

    def query(
        self,
        query_embedding: list[float],
        document_id: str,
        top_k: int = 5,
    ) -> dict:
        """
        Query ChromaDB filtered by document_id.
        Returns top_k most similar chunks with their metadata.
        """
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where={"document_id": document_id},
            include=["documents", "metadatas", "distances"],
        )
        return results

    def delete_document_chunks(self, document_id: str) -> None:
        """Delete all chunks belonging to a document."""
        self.collection.delete(where={"document_id": document_id})
        logger.info(f"Deleted all chunks for document {document_id}")

    def document_exists(self, document_id: str) -> bool:
        """Check if a document has any chunks stored."""
        results = self.collection.get(
            where={"document_id": document_id},
            limit=1,
        )
        return len(results["ids"]) > 0
