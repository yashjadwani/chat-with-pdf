# Retrieval eval harness

This is how I answer *"did retrieval actually get better?"* — with a gold set,
instead of eyeballing latency logs.

It runs a gold set of questions through two retrievers and compares them:

- **baseline** — naive dense-only vector search (top `k`).
- **pipeline** — the full hybrid retriever in `app/services/retrieval.py`
  (acronym expansion → dense + BM25 → RRF fusion → BGE rerank → neighbor
  expansion → BGE rerank).

Reported per retriever, at cutoff `k`:

| Metric | Meaning |
| --- | --- |
| `Hit@k` | Fraction of questions where ≥1 relevant chunk is in the top `k`. |
| `MRR@k` | Mean reciprocal rank of the first relevant chunk. |
| `Recall@k` | Fraction of gold pages retrieved (only for cases with `relevant_pages`). |

The value is the **ablation**: it shows whether the extra machinery (BM25, RRF,
reranking, neighbor expansion) actually moves the numbers versus plain dense
search, or just adds latency.

## Building a gold set

Edit `dataset.json`. Each case:

```json
{
  "id": "short-label",
  "document_id": "the id from your documents table / Chroma metadata",
  "question": "a real question a user would ask",
  "relevant_pages": [7],
  "answer_substrings": ["thirty (30) days", "written notice"]
}
```

- A retrieved chunk counts as **relevant** if its page is in `relevant_pages`
  **or** any string in `answer_substrings` appears in the chunk text.
- `answer_substrings` alone is enough — no need to know chunk boundaries,
  just a phrase that must appear in the correct chunk.
- Leave `relevant_pages` empty (`[]`) to skip page-recall for that case.
- Cases whose `document_id` still starts with `REPLACE` are ignored, so the
  shipped template runs to a clean "no runnable cases" message.

I aim for ~15–25 questions across one or two documents I've already ingested:
a few factual lookups, a few that need exact keywords (good for BM25), a few
conceptual/paraphrased ones (good for dense).

## Running

From the `backend/` directory, with the same environment as the API (populated
Chroma store, embedding + reranker models available, `.env` present):

```bash
python -m eval.run
python -m eval.run --k 5 --dataset eval/dataset.json
```

The semantic retrieval cache is disabled during a run so each question is
measured cold.

## Output

```
Retrieval eval  (k=5, cases=20)

case                       base hit pipe hit base mrr pipe mrr base rec pipe rec
...
MEAN                           0.xx     0.xx     0.xx     0.xx     0.xx     0.xx

Hit@5    dense 0.xx -> hybrid 0.xx
MRR@5    dense 0.xx -> hybrid 0.xx
Recall@5 dense 0.xx -> hybrid 0.xx
```

Paste the MEAN line into the project README's Evaluation section.

## Result files

Every run writes its own JSONL file so results accumulate instead of
overwriting:

```
eval/results_<kind>_<document_id>_<YYYYMMDD_HHMMSS>.jsonl
```

- `kind` is `retrieval` or `judge` (so the two harnesses never collide).
- `document_id` is the shared id, or `multi` when a run spans several docs.
- A same-second re-run gets a `_2`, `_3`, … suffix, so nothing is ever
  overwritten.

The first line is a `run` summary record (timestamp, git SHA, `k`, aggregate
metrics); each following line is one `case` record. Load a run with any JSONL
reader to track quality across changes:

```python
import json
rows = [json.loads(line) for line in open("eval/results_retrieval_....jsonl", encoding="utf-8")]
summary, cases = rows[0], rows[1:]
```

These files are git-ignored (`eval/results_*.jsonl`) — I commit one by hand when
I want a sample in the repo.

## Answer quality (LLM-as-judge)

`judge.py` evaluates the *answer* layer: it runs each case through the real
answer path (`retrieve_chunks` → `generate_answer`) and asks a judge model to
score it:

- **faithfulness (1–5)** — every claim is supported by the retrieved context; a
  correct "that isn't in this document" counts as faithful.
- **relevance (1–5)** — the answer actually addresses the question.
- **correctness (1–5)** — the answer matches the **reference** (the case's gold
  `answer_substrings`), or correctly abstains when there's no answer. This is the
  only score judged against ground truth, not just the retrieved context.
- **unsupported_claims** — verbatim claims the judge couldn't find support
  for; I read these by hand, they're the most actionable output.

```bash
python -m eval.judge
python -m eval.judge --k 5 --dataset eval/dataset.json
```

My honest caveat: LLM-as-judge is noisy, and on an easy factual set it
**saturates** — every answer scores 5/5, so it can't discriminate between
configs. That's made worse by using a weak free judge model, which tends to
rubber-stamp. So a 5/5 here means "the answers are good on easy questions," not
"this config is rigorously better." To make it discriminate I'd need a stronger
judge model and harder cases (multi-hop, ambiguous, adversarial). I treat these
scores as a relative signal and spot-check flagged claims by hand. Each case
makes two extra LLM calls (answer + judge), so a 20-case run costs ~40 calls.
