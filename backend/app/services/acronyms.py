import re
from functools import lru_cache

from flashtext import KeywordProcessor

GLOBAL_ACRONYM_GLOSSARY: dict[str, list[str]] = {
    "ARI": [
        "Adjusted Rand Index",
        "Adjusted Rand score",
    ],
    "AUC": [
        "Area Under Curve",
    ],
    "ROC": [
        "Receiver Operating Characteristic",
    ],
    "GMM": [
        "Gaussian Mixture Model",
    ],
    "SVM": [
        "Support Vector Machine",
    ],
    "KNN": [
        "K Nearest Neighbors",
        "KNeighbors Classifier",
    ],
    "EM": [
        "Expectation Maximization",
    ],
    "CV": [
        "Cross Validation",
    ],
}


@lru_cache(maxsize=1)
def get_keyword_processor() -> KeywordProcessor:
    processor = KeywordProcessor(case_sensitive=False)
    for acronym, long_forms in GLOBAL_ACRONYM_GLOSSARY.items():
        processor.add_keyword(acronym, " ".join(long_forms))
        for long_form in long_forms:
            processor.add_keyword(long_form, acronym)
    return processor


def extract_parenthetical_pairs(text: str) -> dict[str, str]:
    pairs = {}
    pattern = re.compile(r"\b([A-Za-z][A-Za-z\s-]{4,80})\s+\(([A-Z][A-Z0-9-]{1,12})\)")
    for long_form, short_form in pattern.findall(text[:50000]):
        pairs[short_form.strip()] = " ".join(long_form.split())
    return pairs


@lru_cache(maxsize=64)
def extract_document_pairs(document_text: str) -> tuple[tuple[str, str], ...]:
    pairs = extract_parenthetical_pairs(document_text)
    return tuple(sorted(pairs.items()))


def expand_query_with_acronyms(query: str, document_texts: list[str] | None = None) -> str:
    expansions = set(get_keyword_processor().extract_keywords(query))

    if document_texts:
        document_text = "\n".join(document_texts)
        document_pairs = dict(extract_document_pairs(document_text))
        query_terms = set(re.findall(r"[A-Za-z0-9-]+", query.lower()))

        for short_form, long_form in document_pairs.items():
            if short_form.lower() in query_terms:
                expansions.add(long_form)
            if long_form.lower() in query.lower():
                expansions.add(short_form)

    if not expansions:
        return query

    return f"{query}\n\nExpanded acronym terms: {'; '.join(sorted(expansions))}"
