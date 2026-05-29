import logging
import re
from functools import lru_cache

from nltk.corpus import stopwords
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder

from app.core.config import get_settings
from app.db.chroma import ChromaStore
from app.models.chat import Citation
from app.services.acronyms import expand_query_with_acronyms
from app.services.ingestion import embed_query

logger = logging.getLogger(__name__)
settings = get_settings()


@lru_cache(maxsize=1)
def get_reranker_model() -> CrossEncoder:
    logger.info(f"Loading reranker model: {settings.reranker_model}")
    return CrossEncoder(settings.reranker_model)


@lru_cache(maxsize=1)
def get_stopwords() -> set[str]:
    try:
        return set(stopwords.words("english"))
    except LookupError as exc:
        raise RuntimeError(
            "NLTK stopwords corpus is missing. Run: py -m nltk.downloader stopwords"
        ) from exc


def tokenize(text: str) -> list[str]:
    terms = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    stop_words = get_stopwords()
    return [term for term in terms if len(term) > 2 and term not in stop_words]


def _metadata_value(metadata: dict, *keys, default=None):
    for key in keys:
        if key in metadata and metadata[key] is not None:
            return metadata[key]
    return default


def _candidate_to_citation(candidate: dict) -> Citation:
    metadata = candidate["meta"]
    return Citation(
        page_number=int(_metadata_value(metadata, "page_number", "page", default=0)),
        chunk_text=candidate["text"],
        chunk_index=int(_metadata_value(metadata, "chunk_index", "chunk", default=0)),
    )


@lru_cache(maxsize=64)
def _get_bm25_payload(document_id: str) -> tuple[BM25Okapi | None, tuple[dict, ...]]:
    chroma_store = ChromaStore()
    chunks = chroma_store.get_document_chunks(document_id=document_id, active_only=True)
    if not chunks:
        return None, tuple()

    tokenized_chunks = [tokenize(chunk["text"]) for chunk in chunks]
    return BM25Okapi(tokenized_chunks), tuple(chunks)


def clear_bm25_cache(document_id: str | None = None) -> None:
    _get_bm25_payload.cache_clear()
    if document_id:
        logger.info(f"Cleared BM25 cache after document change: {document_id}")


def dense_retrieve(question: str, document_id: str, top_k: int = 50) -> list[dict]:
    chroma_store = ChromaStore()
    query_embedding = embed_query(question)

    results = chroma_store.query(
        query_embedding=query_embedding,
        document_id=document_id,
        top_k=top_k,
        active_only=True,
    )

    candidates = []
    if not results.get("ids") or not results["ids"][0]:
        return candidates

    for doc, meta, distance, chunk_id in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
        results["ids"][0],
    ):
        candidates.append({
            "id": chunk_id,
            "text": doc,
            "meta": meta,
            "dense_distance": distance,
            "dense_score": 1 / (1 + distance),
            "bm25_score": 0.0,
            "source": "dense",
        })

    return candidates


def bm25_retrieve(question: str, document_id: str, top_k: int = 50) -> list[dict]:
    bm25, chunks = _get_bm25_payload(document_id)
    if bm25 is None or not chunks:
        return []

    scores = bm25.get_scores(tokenize(question))
    ranked_indexes = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)

    candidates = []
    for index in ranked_indexes[:top_k]:
        score = float(scores[index])
        if score <= 0:
            continue

        chunk = chunks[index]
        candidates.append({
            "id": chunk["id"],
            "text": chunk["text"],
            "meta": chunk["meta"],
            "dense_distance": None,
            "dense_score": 0.0,
            "bm25_score": score,
            "source": "bm25",
        })

    return candidates


def merge_candidates(dense_candidates: list[dict], bm25_candidates: list[dict]) -> list[dict]:
    merged = {}
    for candidate in dense_candidates + bm25_candidates:
        chunk_id = candidate["id"]
        if chunk_id not in merged:
            merged[chunk_id] = candidate
            continue

        existing = merged[chunk_id]
        existing["dense_score"] = max(existing.get("dense_score", 0.0), candidate.get("dense_score", 0.0))
        existing["bm25_score"] = max(existing.get("bm25_score", 0.0), candidate.get("bm25_score", 0.0))
        existing["source"] = "dense+bm25"

    return list(merged.values())


def rerank_candidates(question: str, candidates: list[dict]) -> list[dict]:
    if not candidates:
        return []

    reranker = get_reranker_model()
    pairs = [(question, candidate["text"]) for candidate in candidates]
    scores = reranker.predict(pairs)

    reranked = [
        {
            **candidate,
            "reranker_score": float(score),
            "final_score": float(score),
        }
        for candidate, score in zip(candidates, scores)
    ]

    return sorted(reranked, key=lambda item: item["final_score"], reverse=True)

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

    return filtered or citations[:5]


def filter_candidates_by_query_terms(question: str, candidates: list[dict]) -> list[dict]:
    terms = [
        term.lower().strip(".,?!'\"")
        for term in question.split()
        if len(term) > 3
    ]

    filtered = []
    for candidate in candidates:
        text = candidate["text"].lower()
        if any(term in text for term in terms):
            filtered.append(candidate)

    return filtered or candidates

def retrieve_chunks(
    question: str,
    document_id: str,
    top_k: int | None = None,
) -> list[Citation]:
    """
    Hybrid retrieval:
    dense vector top 50 + BM25 top 50 -> merge/dedupe -> rerank -> final citations.
    """
    k = settings.retrival_k
    final_k = top_k or settings.retrieval_top_k
    _, document_chunks = _get_bm25_payload(document_id)
    expanded_question = expand_query_with_acronyms(
        query=question,
        document_texts=[chunk["text"] for chunk in document_chunks],
    )
    dense_candidates = dense_retrieve(question=expanded_question, document_id=document_id, top_k=k)
    dense_candidates = filter_candidates_by_query_terms(question=expanded_question, candidates=dense_candidates)
    bm25_candidates = bm25_retrieve(question=expanded_question, document_id=document_id, top_k=k)
    merged = merge_candidates(dense_candidates, bm25_candidates)
    reranked = rerank_candidates(expanded_question, merged)
    citations = [_candidate_to_citation(candidate) for candidate in reranked[:final_k]]

    if not citations:
        logger.warning(f"No chunks found for document {document_id}")
    else:
        logger.info(
            "Hybrid retrieved %s chunks for document %s (dense=%s, bm25=%s, merged=%s)",
            len(citations),
            document_id,
            len(dense_candidates),
            len(bm25_candidates),
            len(merged),
        )

    return citations



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
