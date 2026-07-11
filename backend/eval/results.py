"""
Persist each eval run to its own JSONL file so runs never overwrite each other.

File name: results_<kind>_<doc>_<timestamp>.jsonl
  kind      "retrieval" or "judge"
  doc       the shared document_id, or "multi" when a run spans several
  timestamp local time, YYYYMMDD_HHMMSS (no colons — safe on Windows)

The `kind` prefix keeps a retrieval run and a judge run in the same second from
colliding. First line is a "run" summary record; the rest are one "case" record
each. JSONL means you can append-diff or load runs with pandas later.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent


def _git_sha() -> str | None:
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=EVAL_DIR,
            stderr=subprocess.DEVNULL,
        )
        return sha.decode().strip()
    except (subprocess.SubprocessError, OSError):
        return None


def _doc_label(document_ids: list[str]) -> str:
    unique = sorted(set(document_ids))
    return unique[0] if len(unique) == 1 else "multi"


def save_run(
    kind: str,
    k: int,
    dataset: str,
    document_ids: list[str],
    summary_metrics: dict,
    case_records: list[dict],
) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = f"results_{kind}_{_doc_label(document_ids)}_{timestamp}"
    results_dir = EVAL_DIR / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / f"{stem}.jsonl"
    # Guarantee we never overwrite an earlier run in the same second.
    suffix = 2
    while path.exists():
        path = results_dir / f"{stem}_{suffix}.jsonl"
        suffix += 1

    run_record = {
        "record": "run",
        "kind": kind,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "git_sha": _git_sha(),
        "k": k,
        "dataset": dataset,
        "document_ids": sorted(set(document_ids)),
        "num_cases": len(case_records),
        "metrics": summary_metrics,
    }

    with path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(run_record, ensure_ascii=False) + "\n")
        for case in case_records:
            handle.write(json.dumps({"record": "case", **case}, ensure_ascii=False) + "\n")

    return path
