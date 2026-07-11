"""
Retrieval eval harness.

Runs each question in the gold set through two retrievers and reports
Hit@k, MRR@k, and page Recall@k for both:

  - baseline: naive dense-only vector search (top k)
  - pipeline: the full hybrid retriever (acronym expansion -> dense + BM25 ->
    RRF fusion -> BGE rerank -> neighbor expansion -> BGE rerank)

The point is the ablation: it shows whether the extra machinery in the
pipeline actually earns its latency by moving the numbers vs plain dense search.

Run from the backend/ directory so `app` is importable:

    python -m eval.run
    python -m eval.run --k 5 --dataset eval/dataset.json

Requires the same environment as the API (populated Chroma store, embedding +
reranker models, .env). The `document_id`s in the dataset must exist in Chroma.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.core.config import get_settings
from app.models.chat import Citation
from app.services.retrieval import dense_retrieve, retrieve_chunks
from eval.metrics import Result, hit_at_k, mean, mrr_at_k, page_recall_at_k
from eval.results import save_run


def _page_of(meta: dict) -> int:
    for key in ("page_number", "page"):
        if meta.get(key) is not None:
            return int(meta[key])
    return 0


def as_results(items: list) -> list[Result]:
    results: list[Result] = []
    for item in items:
        if isinstance(item, Citation):
            results.append((item.page_number, item.chunk_text))
        else:
            results.append((_page_of(item["meta"]), item["text"]))
    return results


def baseline_dense(question: str, document_id: str, k: int) -> list[Result]:
    candidates = dense_retrieve(question=question, document_id=document_id, top_k=k)
    return as_results(candidates[:k])


def full_pipeline(question: str, document_id: str, k: int) -> list[Result]:
    citations = retrieve_chunks(question=question, document_id=document_id, top_k=k)
    return as_results(citations)


def score(results: list[Result], case: dict, k: int) -> dict:
    return {
        "hit": hit_at_k(results, case, k),
        "mrr": mrr_at_k(results, case, k),
        "recall": page_recall_at_k(results, case, k),
    }


def _fmt(value: float | None) -> str:
    return " -  " if value is None else f"{value:.2f}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Retrieval eval harness")
    parser.add_argument("--dataset", default="eval/dataset.json", help="Path to the gold set JSON")
    parser.add_argument("--k", type=int, default=5, help="Cutoff k for the metrics")
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        print(f"Dataset not found: {dataset_path}", file=sys.stderr)
        return 1

    cases = json.loads(dataset_path.read_text(encoding="utf-8")).get("cases", [])
    cases = [case for case in cases if not str(case.get("document_id", "")).startswith("REPLACE")]
    if not cases:
        print(
            "No runnable cases. Edit eval/dataset.json: set real document_id values "
            "and gold pages/substrings. See eval/README.md.",
            file=sys.stderr,
        )
        return 1

    # Cache would hide per-question retrieval behind earlier answers; measure cold.
    settings = get_settings()
    settings.retrieval_semantic_cache_enabled = False

    k = args.k
    rows = []
    case_records = []
    agg = {"baseline": {"hit": [], "mrr": [], "recall": []},
           "pipeline": {"hit": [], "mrr": [], "recall": []}}

    for case in cases:
        document_id = case["document_id"]
        question = case["question"]
        base = score(baseline_dense(question, document_id, k), case, k)
        pipe = score(full_pipeline(question, document_id, k), case, k)
        for name, scored in (("baseline", base), ("pipeline", pipe)):
            for metric in ("hit", "mrr", "recall"):
                agg[name][metric].append(scored[metric])
        case_id = case.get("id", question[:24])
        rows.append((case_id, base, pipe))
        case_records.append({
            "id": case_id,
            "document_id": document_id,
            "question": question,
            "baseline": base,
            "pipeline": pipe,
        })

    header = f"{'case':<26} {'base hit':>8} {'pipe hit':>8} {'base mrr':>8} {'pipe mrr':>8} {'base rec':>8} {'pipe rec':>8}"
    print(f"\nRetrieval eval  (k={k}, cases={len(cases)})\n")
    print(header)
    print("-" * len(header))
    for case_id, base, pipe in rows:
        print(
            f"{case_id:<26} {_fmt(base['hit']):>8} {_fmt(pipe['hit']):>8} "
            f"{_fmt(base['mrr']):>8} {_fmt(pipe['mrr']):>8} "
            f"{_fmt(base['recall']):>8} {_fmt(pipe['recall']):>8}"
        )
    print("-" * len(header))
    print(
        f"{'MEAN':<26} "
        f"{mean(agg['baseline']['hit']):>8.2f} {mean(agg['pipeline']['hit']):>8.2f} "
        f"{mean(agg['baseline']['mrr']):>8.2f} {mean(agg['pipeline']['mrr']):>8.2f} "
        f"{mean(agg['baseline']['recall']):>8.2f} {mean(agg['pipeline']['recall']):>8.2f}"
    )
    summary_metrics = {
        "baseline": {metric: mean(agg["baseline"][metric]) for metric in ("hit", "mrr", "recall")},
        "pipeline": {metric: mean(agg["pipeline"][metric]) for metric in ("hit", "mrr", "recall")},
    }
    print(
        f"\nHit@{k}    dense {summary_metrics['baseline']['hit']:.2f} -> hybrid {summary_metrics['pipeline']['hit']:.2f}"
        f"\nMRR@{k}    dense {summary_metrics['baseline']['mrr']:.2f} -> hybrid {summary_metrics['pipeline']['mrr']:.2f}"
        f"\nRecall@{k} dense {summary_metrics['baseline']['recall']:.2f} -> hybrid {summary_metrics['pipeline']['recall']:.2f}\n"
    )

    path = save_run(
        kind="retrieval",
        k=k,
        dataset=str(dataset_path),
        document_ids=[case["document_id"] for case in cases],
        summary_metrics=summary_metrics,
        case_records=case_records,
    )
    print(f"Results written to {path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
