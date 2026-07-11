"""
Retrieval metrics for the eval harness.

A retrieved result is a (page_number, chunk_text) pair. A result counts as
relevant to a case if its page is in the case's `relevant_pages`, or if any of
the case's `answer_substrings` appears in the chunk text (case-insensitive).
Using substrings as well as pages means a gold set can be written without
knowing the exact chunk boundaries the ingester produced.
"""

from __future__ import annotations

Result = tuple[int, str]


def is_relevant(page: int, text: str, case: dict) -> bool:
    if page and page in (case.get("relevant_pages") or []):
        return True
    lowered = text.lower()
    return any(sub.lower() in lowered for sub in case.get("answer_substrings") or [])


def hit_at_k(results: list[Result], case: dict, k: int) -> float:
    """1.0 if at least one relevant chunk is in the top k, else 0.0."""
    return 1.0 if any(is_relevant(page, text, case) for page, text in results[:k]) else 0.0


def mrr_at_k(results: list[Result], case: dict, k: int) -> float:
    """Reciprocal rank of the first relevant chunk in the top k (0.0 if none)."""
    for rank, (page, text) in enumerate(results[:k], start=1):
        if is_relevant(page, text, case):
            return 1.0 / rank
    return 0.0


def page_recall_at_k(results: list[Result], case: dict, k: int) -> float | None:
    """
    Fraction of the case's gold pages present in the top k.
    Returns None when the case has no `relevant_pages` (recall is undefined).
    """
    gold = set(case.get("relevant_pages") or [])
    if not gold:
        return None
    retrieved = {page for page, _ in results[:k] if page in gold}
    return len(retrieved) / len(gold)


def mean(values: list[float]) -> float:
    usable = [value for value in values if value is not None]
    return sum(usable) / len(usable) if usable else 0.0
