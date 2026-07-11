"""
Answer-quality eval: faithfulness and relevance, scored by an LLM judge.

The retrieval eval (eval/run.py) answers "did we fetch the right chunks?".
This answers the follow-up an interviewer always asks: "how do you know the
LLM didn't hallucinate beyond them?".

For each case in the gold set it runs the real answer path
(retrieve_chunks -> generate_answer), then asks a judge model to score the
answer against ONLY the retrieved context:

  - faithfulness (1-5): every claim in the answer is supported by the context.
    5 = fully grounded, 1 = mostly fabricated.
  - relevance (1-5): the answer actually addresses the question.
  - unsupported_claims: verbatim claims the judge could not find support for.

Run from the backend/ directory with the same environment as the API:

    python -m eval.judge
    python -m eval.judge --k 5 --dataset eval/dataset.json

Caveats, stated honestly: LLM-as-judge is a noisy instrument. Scores are most
useful as a relative signal (before/after a prompt or retrieval change) and
for surfacing unsupported claims to read yourself, not as absolute truth.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

import httpx

from app.core.config import get_settings
from app.services.llm import generate_answer
from app.services.retrieval import format_context, retrieve_chunks
from eval.metrics import mean
from eval.results import save_run

JUDGE_SYSTEM_PROMPT = (
    "You are a strict evaluator of retrieval-augmented answers. "
    "You will receive a QUESTION, the CONTEXT that was retrieved from a document, "
    "and the ANSWER a model gave. Judge the answer using ONLY the context - "
    "outside knowledge must not rescue an unsupported claim.\n\n"
    "Return ONLY a JSON object, no prose, with exactly these keys:\n"
    '{"faithfulness": <1-5>, "relevance": <1-5>, "unsupported_claims": ["..."]}\n\n'
    "faithfulness: 5 = every claim is directly supported by the context; "
    "3 = minor unsupported details; 1 = the answer is mostly fabricated.\n"
    "relevance: 5 = fully answers the question; 1 = does not address it.\n"
    "unsupported_claims: quote each claim from the answer that the context "
    "does not support (empty list if none). "
    "If the answer correctly says the information is not in the document, "
    "that is faithful: score faithfulness 5."
)


def parse_judge_json(raw: str) -> dict | None:
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        brace = re.search(r"\{.*\}", text, re.DOTALL)
        if brace:
            text = brace.group(0)
    try:
        verdict = json.loads(text)
    except json.JSONDecodeError:
        return None

    try:
        faithfulness = int(verdict["faithfulness"])
        relevance = int(verdict["relevance"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (1 <= faithfulness <= 5 and 1 <= relevance <= 5):
        return None

    claims = verdict.get("unsupported_claims")
    return {
        "faithfulness": faithfulness,
        "relevance": relevance,
        "unsupported_claims": claims if isinstance(claims, list) else [],
    }


async def call_judge(question: str, context: str, answer: str) -> dict | None:
    settings = get_settings()
    user_content = (
        f"QUESTION:\n{question}\n\n"
        f"CONTEXT:\n{context}\n\n"
        f"ANSWER:\n{answer}"
    )
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{settings.opencode_base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.opencode_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.opencode_model,
                "messages": [
                    {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                "max_tokens": 600,
                "temperature": 0.0,
            },
        )
        response.raise_for_status()
        data = response.json()
    return parse_judge_json(data["choices"][0]["message"]["content"])


async def evaluate_case(case: dict, k: int) -> dict:
    citations = retrieve_chunks(
        question=case["question"],
        document_id=case["document_id"],
        top_k=k,
    )
    answer, model_used = await generate_answer(
        question=case["question"],
        citations=citations,
        conversation_history="",
    )
    verdict = await call_judge(
        question=case["question"],
        context=format_context(citations),
        answer=answer,
    )
    return {
        "id": case.get("id", case["question"][:24]),
        "document_id": case["document_id"],
        "question": case["question"],
        "answer": answer,
        "model": model_used,
        "verdict": verdict,
    }


async def main_async(args: argparse.Namespace) -> int:
    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        print(f"Dataset not found: {dataset_path}", file=sys.stderr)
        return 1

    cases = json.loads(dataset_path.read_text(encoding="utf-8")).get("cases", [])
    cases = [case for case in cases if not str(case.get("document_id", "")).startswith("REPLACE")]
    if not cases:
        print(
            "No runnable cases. Edit eval/dataset.json first - see eval/README.md.",
            file=sys.stderr,
        )
        return 1

    settings = get_settings()
    settings.retrieval_semantic_cache_enabled = False

    results = []
    for case in cases:
        try:
            results.append(await evaluate_case(case, args.k))
        except Exception as exc:  # keep going: one bad case shouldn't kill the run
            print(f"  ! {case.get('id', '?')}: {exc}", file=sys.stderr)

    scored = [result for result in results if result["verdict"] is not None]
    unparsed = len(results) - len(scored)

    header = f"{'case':<26} {'faith':>5} {'relev':>5}  unsupported claims"
    print(f"\nAnswer-quality eval  (k={args.k}, cases={len(results)}, judge={settings.opencode_model})\n")
    print(header)
    print("-" * len(header))
    for result in results:
        verdict = result["verdict"]
        if verdict is None:
            print(f"{result['id']:<26} {'?':>5} {'?':>5}  (judge output unparseable)")
            continue
        claims = "; ".join(verdict["unsupported_claims"]) or "-"
        print(f"{result['id']:<26} {verdict['faithfulness']:>5} {verdict['relevance']:>5}  {claims}")
    print("-" * len(header))

    summary_metrics = {}
    if scored:
        faithfulness = mean([r["verdict"]["faithfulness"] for r in scored])
        relevance = mean([r["verdict"]["relevance"] for r in scored])
        flagged = sum(1 for r in scored if r["verdict"]["unsupported_claims"])
        summary_metrics = {
            "faithfulness": faithfulness,
            "relevance": relevance,
            "answers_with_unsupported_claims": flagged,
            "scored_cases": len(scored),
            "unparseable": unparsed,
        }
        print(f"{'MEAN':<26} {faithfulness:>5.2f} {relevance:>5.2f}")
        print(
            f"\nFaithfulness {faithfulness:.2f}/5, "
            f"relevance {relevance:.2f}/5, "
            f"{flagged}/{len(scored)} answers had unsupported claims"
            + (f", {unparsed} judge outputs unparseable" if unparsed else "")
            + "\n"
        )

    if results:
        path = save_run(
            kind="judge",
            k=args.k,
            dataset=str(dataset_path),
            document_ids=[result["document_id"] for result in results],
            summary_metrics=summary_metrics,
            case_records=results,
        )
        print(f"Results written to {path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path}\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Answer faithfulness/relevance eval (LLM-as-judge)")
    parser.add_argument("--dataset", default="eval/dataset.json", help="Path to the gold set JSON")
    parser.add_argument("--k", type=int, default=5, help="Retrieval top-k used for answering")
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
