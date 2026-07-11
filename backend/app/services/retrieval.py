import logging
import time
import re
from functools import lru_cache
from threading import Lock

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
_semantic_cache_lock = Lock()
_semantic_retrieval_cache: list[dict] = []


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


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right))


def _semantic_cache_key(document_id: str, final_k: int) -> tuple[str, int]:
    return document_id, final_k


def get_semantic_cache_entry(
    document_id: str,
    final_k: int,
    query_embedding: list[float],
) -> list[Citation] | None:
    if not settings.retrieval_semantic_cache_enabled:
        return None

    cache_key = _semantic_cache_key(document_id, final_k)
    threshold = settings.retrieval_semantic_cache_threshold
    with _semantic_cache_lock:
        best_entry = None
        best_similarity = threshold
        for entry in _semantic_retrieval_cache:
            if entry["key"] != cache_key:
                continue
            similarity = _cosine_similarity(query_embedding, entry["query_embedding"])
            if similarity >= best_similarity:
                best_entry = entry
                best_similarity = similarity

        if best_entry is None:
            return None

        best_entry["last_used_at"] = time.monotonic()
        logger.info(
            "Semantic retrieval cache hit for document %s (similarity=%.3f)",
            document_id,
            best_similarity,
        )
        return best_entry["citations"]


def set_semantic_cache_entry(
    document_id: str,
    final_k: int,
    query_embedding: list[float],
    citations: list[Citation],
) -> None:
    if not settings.retrieval_semantic_cache_enabled or not citations:
        return

    cache_key = _semantic_cache_key(document_id, final_k)
    now = time.monotonic()
    with _semantic_cache_lock:
        _semantic_retrieval_cache.append({
            "key": cache_key,
            "query_embedding": query_embedding,
            "citations": citations,
            "created_at": now,
            "last_used_at": now,
        })

        overflow = len(_semantic_retrieval_cache) - settings.retrieval_semantic_cache_max_entries
        if overflow > 0:
            _semantic_retrieval_cache.sort(key=lambda entry: entry["last_used_at"])
            del _semantic_retrieval_cache[:overflow]


def clear_semantic_retrieval_cache(document_id: str | None = None) -> None:
    with _semantic_cache_lock:
        if document_id is None:
            _semantic_retrieval_cache.clear()
            return

        _semantic_retrieval_cache[:] = [
            entry for entry in _semantic_retrieval_cache if entry["key"][0] != document_id
        ]


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
    clear_semantic_retrieval_cache(document_id)
    if document_id:
        logger.info(f"Cleared retrieval caches after document change: {document_id}")


def build_acronym_expanded_query(question: str, document_id: str) -> str:
    _, document_chunks = _get_bm25_payload(document_id)
    return expand_query_with_acronyms(
        query=question,
        document_texts=[chunk["text"] for chunk in document_chunks],
    )


def dense_retrieve(
    question: str,
    document_id: str,
    top_k: int = 50,
    query_embedding: list[float] | None = None,
) -> list[dict]:
    chroma_store = ChromaStore()
    embedding = query_embedding or embed_query(question)

    results = chroma_store.query(
        query_embedding=embedding,
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


def merge_candidates(
    dense_candidates: list[dict],
    bm25_candidates: list[dict],
    rrf_k: int | None = None,
) -> list[dict]:
    merged = {}
    fusion_k = rrf_k or settings.retrieval_rrf_k

    for source_candidates in (dense_candidates, bm25_candidates):
        for rank, candidate in enumerate(source_candidates, start=1):
            candidate["rrf_score"] = 1 / (fusion_k + rank)

    for candidate in dense_candidates + bm25_candidates:
        chunk_id = candidate["id"]
        if chunk_id not in merged:
            merged[chunk_id] = {**candidate}
            continue

        existing = merged[chunk_id]
        existing["dense_score"] = max(existing.get("dense_score", 0.0), candidate.get("dense_score", 0.0))
        existing["bm25_score"] = max(existing.get("bm25_score", 0.0), candidate.get("bm25_score", 0.0))
        existing["rrf_score"] = existing.get("rrf_score", 0.0) + candidate.get("rrf_score", 0.0)
        existing["source"] = "dense+bm25"

    return sorted(merged.values(), key=lambda item: item.get("rrf_score", 0.0), reverse=True)


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


def _chunk_index(candidate: dict) -> int:
    return int(_metadata_value(candidate["meta"], "chunk_index", "chunk", default=-1))


def expand_with_neighbor_candidates(
    candidates: list[dict],
    all_chunks: tuple[dict, ...],
    window: int | None = None,
) -> list[dict]:
    neighbor_window = settings.retrieval_neighbor_window if window is None else window
    if neighbor_window <= 0 or not candidates or not all_chunks:
        return candidates

    chunks_by_index = {
        int(_metadata_value(chunk["meta"], "chunk_index", "chunk", default=-1)): chunk
        for chunk in all_chunks
    }

    expanded = {candidate["id"]: candidate for candidate in candidates}
    for candidate in candidates:
        base_index = _chunk_index(candidate)
        if base_index < 0:
            continue

        for offset in range(-neighbor_window, neighbor_window + 1):
            if offset == 0:
                continue
            neighbor = chunks_by_index.get(base_index + offset)
            if not neighbor or neighbor["id"] in expanded:
                continue

            expanded[neighbor["id"]] = {
                "id": neighbor["id"],
                "text": neighbor["text"],
                "meta": neighbor["meta"],
                "dense_distance": None,
                "dense_score": 0.0,
                "bm25_score": 0.0,
                "rrf_score": candidate.get("rrf_score", 0.0) * 0.5,
                "source": "neighbor",
            }

    return list(expanded.values())

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
    bm25_query: str | None = None,
    dense_query: str | None = None,
    rerank_query: str | None = None,
) -> list[Citation]:
    """
    Hybrid retrieval:
    dense vector top 50 + BM25 top 50 -> merge/dedupe -> rerank -> final citations.
    """
    k = settings.retrival_k
    final_k = top_k or settings.retrieval_top_k
    _, document_chunks = _get_bm25_payload(document_id)
    expanded_question = build_acronym_expanded_query(question=question, document_id=document_id)
    dense_search_query = dense_query or expanded_question
    bm25_search_query = bm25_query or expanded_question
    ranking_query = rerank_query or expanded_question
    query_embedding = embed_query(dense_search_query)
    cached_citations = get_semantic_cache_entry(
        document_id=document_id,
        final_k=final_k,
        query_embedding=query_embedding,
    )
    if cached_citations is not None:
        return cached_citations[:final_k]

    dense_candidates = dense_retrieve(
        question=dense_search_query,
        document_id=document_id,
        top_k=k,
        query_embedding=query_embedding,
    )
    dense_candidates = filter_candidates_by_query_terms(question=ranking_query, candidates=dense_candidates)
    bm25_candidates = bm25_retrieve(question=bm25_search_query, document_id=document_id, top_k=k)
    merged = merge_candidates(dense_candidates, bm25_candidates)

    if settings.retrieval_reranker_enabled:
        rerank_pool = merged[:settings.retrieval_rerank_k]
        reranked_seed = rerank_candidates(ranking_query, rerank_pool)
        expanded_candidates = expand_with_neighbor_candidates(
            candidates=reranked_seed[:final_k],
            all_chunks=document_chunks,
        )
        final_candidates = rerank_candidates(ranking_query, expanded_candidates)
        neighbors_added = len(expanded_candidates) - len(reranked_seed[:final_k])
    else:
        # Reranker off: serve the RRF-fused order directly (no rerank, no neighbor).
        final_candidates = merged
        neighbors_added = 0

    citations = [_candidate_to_citation(candidate) for candidate in final_candidates[:final_k]]
    set_semantic_cache_entry(
        document_id=document_id,
        final_k=final_k,
        query_embedding=query_embedding,
        citations=citations,
    )

    if not citations:
        logger.warning(f"No chunks found for document {document_id}")
    else:
        logger.info(
            "Hybrid retrieved %s chunks for document %s (dense=%s, bm25=%s, merged=%s, rerank=%s, neighbors=%s)",
            len(citations),
            document_id,
            len(dense_candidates),
            len(bm25_candidates),
            len(merged),
            settings.retrieval_reranker_enabled,
            neighbors_added,
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
