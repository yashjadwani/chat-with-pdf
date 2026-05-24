import logging
from app.core.config import get_settings
from app.db.chroma import ChromaStore
from app.services.ingestion import embed_query
from app.models.chat import Citation

logger = logging.getLogger(__name__)
settings = get_settings()


def retrieve_chunks(
    question: str,
    document_id: str,
    top_k: int | None = None,
) -> list[Citation]:
    """
    Embed the query and retrieve top-k relevant chunks from ChromaDB
    filtered by document_id.

    Returns a list of Citation objects with page numbers and chunk text.
    """
    if top_k is None:
        top_k = settings.retrieval_top_k

    chroma_store = ChromaStore()

    # Embed the query with the 'query: ' prefix (e5 model requirement)
    query_embedding = embed_query(question)

    # Query ChromaDB
    results = chroma_store.query(
        query_embedding=query_embedding,
        document_id=document_id,
        top_k=top_k,
    )

    citations = []

    if not results["ids"] or not results["ids"][0]:
        logger.warning(f"No chunks found for document {document_id}")
        return citations

    documents = results["documents"][0]
    metadatas = results["metadatas"][0]
    distances = results["distances"][0]

    for doc_text, metadata, distance in zip(documents, metadatas, distances):
        # ChromaDB cosine distance: 0 = identical, 2 = opposite
        # Filter out low-relevance chunks (distance > 1.0 means poor match)
        if distance > 1.0:
            logger.debug(f"Skipping low-relevance chunk (distance={distance:.3f})")
            continue

        citation = Citation(
            page_number=metadata.get("page_number", 0),
            chunk_text=doc_text,
            chunk_index=metadata.get("chunk_index", 0),
        )
        citations.append(citation)

    logger.info(f"Retrieved {len(citations)} relevant chunks for document {document_id}")
    return citations


def filter_by_query_terms(
    question: str,
    citations: list[Citation],
) -> list[Citation]:
    terms = [
        term.lower().strip(".,?!'\"")
        for term in question.split()
        if len(term) > 3
    ]

    filtered = []
    for citation in citations:
        text = citation.chunk_text.lower()
        if any(term in text for term in terms):
            filtered.append(citation)

    return filtered or citations[:3]


def format_context(citations: list[Citation]) -> str:
    """
    Format retrieved chunks into a context string for the LLM prompt.
    Includes page numbers so the model can cite them in its answer.
    """
    if not citations:
        return "No relevant content found in the document."

    context_parts = []
    for citation in citations:
        context_parts.append(
            f"[Page {citation.page_number}]\n{citation.chunk_text}"
        )

    return "\n\n---\n\n".join(context_parts)
