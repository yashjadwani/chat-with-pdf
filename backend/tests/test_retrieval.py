import pytest

from app.models.chat import Citation
from app.services.retrieval import (
    expand_with_neighbor_candidates,
    filter_by_query_terms,
    get_stopwords,
    merge_candidates,
    tokenize,
)


def make_candidate(chunk_id: str, chunk_index: int = 0, text: str = "text") -> dict:
    return {
        "id": chunk_id,
        "text": text,
        "meta": {"chunk_index": chunk_index, "page_number": 1},
        "dense_distance": None,
        "dense_score": 0.0,
        "bm25_score": 0.0,
        "source": "dense",
    }


class TestMergeCandidates:
    def test_rrf_scores_follow_rank_formula(self):
        dense = [make_candidate("a"), make_candidate("b")]
        bm25 = [make_candidate("b"), make_candidate("c")]

        merged = merge_candidates(dense, bm25, rrf_k=60)
        scores = {candidate["id"]: candidate["rrf_score"] for candidate in merged}

        assert scores["a"] == pytest.approx(1 / 61)
        assert scores["b"] == pytest.approx(1 / 62 + 1 / 61)
        assert scores["c"] == pytest.approx(1 / 62)

    def test_chunk_in_both_sources_ranks_first(self):
        dense = [make_candidate("a"), make_candidate("b")]
        bm25 = [make_candidate("b"), make_candidate("c")]

        merged = merge_candidates(dense, bm25, rrf_k=60)

        assert [candidate["id"] for candidate in merged] == ["b", "a", "c"]
        assert merged[0]["source"] == "dense+bm25"

    def test_deduplicates_shared_ids(self):
        dense = [make_candidate("a")]
        bm25 = [make_candidate("a")]

        merged = merge_candidates(dense, bm25, rrf_k=60)

        assert len(merged) == 1

    def test_keeps_max_score_per_source(self):
        dense_candidate = make_candidate("a")
        dense_candidate["dense_score"] = 0.9
        bm25_candidate = make_candidate("a")
        bm25_candidate["bm25_score"] = 7.5

        merged = merge_candidates([dense_candidate], [bm25_candidate], rrf_k=60)

        assert merged[0]["dense_score"] == 0.9
        assert merged[0]["bm25_score"] == 7.5


class TestNeighborExpansion:
    def test_adds_adjacent_chunks_within_window(self):
        all_chunks = tuple(make_candidate(f"c{i}", chunk_index=i) for i in range(6))
        seed = [make_candidate("c3", chunk_index=3)]
        seed[0]["rrf_score"] = 0.5

        expanded = expand_with_neighbor_candidates(seed, all_chunks, window=1)
        ids = {candidate["id"] for candidate in expanded}

        assert ids == {"c2", "c3", "c4"}

    def test_neighbors_get_half_the_seed_rrf_score(self):
        all_chunks = tuple(make_candidate(f"c{i}", chunk_index=i) for i in range(4))
        seed = [make_candidate("c1", chunk_index=1)]
        seed[0]["rrf_score"] = 0.4

        expanded = expand_with_neighbor_candidates(seed, all_chunks, window=1)
        neighbors = [candidate for candidate in expanded if candidate["source"] == "neighbor"]

        assert neighbors
        assert all(candidate["rrf_score"] == pytest.approx(0.2) for candidate in neighbors)

    def test_zero_window_is_a_no_op(self):
        all_chunks = tuple(make_candidate(f"c{i}", chunk_index=i) for i in range(4))
        seed = [make_candidate("c1", chunk_index=1)]

        assert expand_with_neighbor_candidates(seed, all_chunks, window=0) == seed


class TestFilterByQueryTerms:
    def _citation(self, text: str) -> Citation:
        return Citation(page_number=1, chunk_text=text, chunk_index=0)

    def test_keeps_citations_containing_query_terms(self):
        citations = [
            self._citation("The termination clause requires notice."),
            self._citation("Completely unrelated content."),
        ]

        filtered = filter_by_query_terms("What about termination?", citations)

        assert len(filtered) == 1
        assert "termination" in filtered[0].chunk_text

    def test_falls_back_to_top_five_when_nothing_matches(self):
        citations = [self._citation(f"chunk {i}") for i in range(8)]

        filtered = filter_by_query_terms("zzzz-no-match-term", citations)

        assert filtered == citations[:5]


class TestRerankerToggle:
    def _wire(self, monkeypatch, enabled: bool):
        import app.services.retrieval as r

        monkeypatch.setattr(r.settings, "retrieval_reranker_enabled", enabled)
        monkeypatch.setattr(r, "_get_bm25_payload", lambda document_id: (None, ()))
        monkeypatch.setattr(r, "embed_query", lambda q: [0.0, 0.0])
        monkeypatch.setattr(r, "get_semantic_cache_entry", lambda **kw: None)
        monkeypatch.setattr(r, "set_semantic_cache_entry", lambda **kw: None)
        monkeypatch.setattr(
            r,
            "dense_retrieve",
            lambda **kw: [make_candidate(f"c{i}", chunk_index=i) | {"meta": {"page_number": i, "chunk_index": i}} for i in (1, 2, 3)],
        )
        monkeypatch.setattr(r, "bm25_retrieve", lambda **kw: [])
        calls = {"rerank": 0}

        def spy_rerank(query, candidates):
            calls["rerank"] += 1
            return candidates

        monkeypatch.setattr(r, "rerank_candidates", spy_rerank)
        return r, calls

    def test_disabled_skips_reranker_and_keeps_rrf_order(self, monkeypatch):
        r, calls = self._wire(monkeypatch, enabled=False)
        citations = r.retrieve_chunks(question="q", document_id="d", top_k=2)
        assert calls["rerank"] == 0
        assert [c.page_number for c in citations] == [1, 2]

    def test_enabled_calls_reranker(self, monkeypatch):
        r, calls = self._wire(monkeypatch, enabled=True)
        r.retrieve_chunks(question="q", document_id="d", top_k=2)
        assert calls["rerank"] > 0


class TestTokenize:
    @pytest.fixture(autouse=True)
    def _require_stopwords(self):
        try:
            get_stopwords()
        except RuntimeError:
            pytest.skip("NLTK stopwords corpus not downloaded")

    def test_drops_stopwords_and_short_terms(self):
        tokens = tokenize("What is the notice period of it?")
        assert "the" not in tokens
        assert "is" not in tokens
        assert "notice" in tokens
        assert "period" in tokens

    def test_lowercases_terms(self):
        assert "termination" in tokenize("TERMINATION Clause")
