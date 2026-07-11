"""
Retrieval ablation harness — isolate which pipeline stage causes the regression
vs the dense-only baseline.

`run.py` shows *that* the full pipeline underperforms dense-only. This lets you
find *why* by toggling one stage at a time and re-scoring the same gold set.
Each run prints the dense-only baseline next to the (ablated) pipeline, so you
can see which toggle closes the gap.

Run from the backend/ directory:

    py -m eval.ablation                  # full pipeline (matches run.py's "pipeline")
    py -m eval.ablation --no-acronym     # use the raw question (no acronym expansion)
    py -m eval.ablation --no-filter      # skip the query-term filter
    py -m eval.ablation --no-bm25        # dense only into the reranker
    py -m eval.ablation --no-rerank      # keep RRF order, no cross-encoder
    py -m eval.ablation --no-neighbor    # skip neighbor expansion

Combine flags to bisect (e.g. --no-acronym --no-rerank). Whichever flag makes
the pipeline match/beat the baseline is your culprit.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.core.config import get_settings
from app.services.retrieval import (
    _get_bm25_payload,
    bm25_retrieve,
    build_acronym_expanded_query,
    dense_retrieve,
    expand_with_neighbor_candidates,
    filter_candidates_by_query_terms,
    merge_candidates,
    rerank_candidates,
)
from eval.metrics import hit_at_k, mean, mrr_at_k, page_recall_at_k


def _page(meta: dict) -> int:
    for key in ("page_number", "page"):
        if meta.get(key) is not None:
            return int(meta[key])
    return 0


def _results(cands: list[dict]) -> list[tuple[int, str]]:
    return [(_page(c["meta"]), c["text"]) for c in cands]


def dense_only(question: str, document_id: str, final_k: int) -> list[tuple[int, str]]:
    return _results(dense_retrieve(question=question, document_id=document_id, top_k=final_k)[:final_k])


def pipeline(question: str, document_id: str, final_k: int, flags: argparse.Namespace) -> list[tuple[int, str]]:
    settings = get_settings()
    k = settings.retrival_k
    _, document_chunks = _get_bm25_payload(document_id)

    query = question if flags.no_acronym else build_acronym_expanded_query(question=question, document_id=document_id)

    dense = dense_retrieve(question=query, document_id=document_id, top_k=k)
    if not flags.no_filter:
        dense = filter_candidates_by_query_terms(question=query, candidates=dense)
    bm25 = [] if flags.no_bm25 else bm25_retrieve(question=query, document_id=document_id, top_k=k)
    merged = merge_candidates(dense, bm25)

    if flags.no_rerank:
        final = merged[:final_k]
    else:
        seed = rerank_candidates(query, merged[: settings.retrieval_rerank_k])
        if flags.no_neighbor:
            final = seed[:final_k]
        else:
            expanded = expand_with_neighbor_candidates(candidates=seed[:final_k], all_chunks=document_chunks)
            final = rerank_candidates(query, expanded)[:final_k]

    return _results(final[:final_k])


def _score(results: list[tuple[int, str]], case: dict, k: int) -> dict:
    return {
        "hit": hit_at_k(results, case, k),
        "mrr": mrr_at_k(results, case, k),
        "recall": page_recall_at_k(results, case, k),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Retrieval ablation harness")
    parser.add_argument("--dataset", default="eval/dataset.json")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--no-acronym", action="store_true")
    parser.add_argument("--no-filter", action="store_true")
    parser.add_argument("--no-bm25", action="store_true")
    parser.add_argument("--no-rerank", action="store_true")
    parser.add_argument("--no-neighbor", action="store_true")
    args = parser.parse_args()

    path = Path(args.dataset)
    if not path.exists():
        print(f"Dataset not found: {path}", file=sys.stderr)
        return 1
    cases = json.loads(path.read_text(encoding="utf-8")).get("cases", [])
    cases = [c for c in cases if not str(c.get("document_id", "")).startswith("REPLACE")]

    get_settings().retrieval_semantic_cache_enabled = False

    enabled = [name for name in ("no_acronym", "no_filter", "no_bm25", "no_rerank", "no_neighbor") if getattr(args, name)]
    print(f"\nAblation (k={args.k}, cases={len(cases)}) - disabled: {', '.join(enabled) or 'none (full pipeline)'}\n")

    agg = {"base": {"hit": [], "mrr": [], "recall": []}, "pipe": {"hit": [], "mrr": [], "recall": []}}
    regressions = []
    for case in cases:
        base = _score(dense_only(case["question"], case["document_id"], args.k), case, args.k)
        pipe = _score(pipeline(case["question"], case["document_id"], args.k, args), case, args.k)
        for metric in ("hit", "mrr", "recall"):
            agg["base"][metric].append(base[metric])
            agg["pipe"][metric].append(pipe[metric])
        if pipe["hit"] < base["hit"] or pipe["mrr"] < base["mrr"] - 1e-9:
            regressions.append((case.get("id", "?"), base, pipe))

    for label in ("hit", "mrr", "recall"):
        b, p = mean(agg["base"][label]), mean(agg["pipe"][label])
        arrow = "UP" if p > b + 1e-9 else "DOWN" if p < b - 1e-9 else "=="
        print(f"  {label.upper():<7} baseline {b:.3f}   pipeline {p:.3f}   {arrow}")

    if regressions:
        print(f"\n  Cases where the pipeline still loses to baseline ({len(regressions)}):")
        for cid, base, pipe in regressions:
            print(f"    {cid:<18} hit {base['hit']:.0f}->{pipe['hit']:.0f}  mrr {base['mrr']:.2f}->{pipe['mrr']:.2f}")
    else:
        print("\n  No per-case regressions vs baseline with these flags.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
