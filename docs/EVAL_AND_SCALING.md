# Evaluation & Scaling Notes

This is my working record of how I evaluate the retrieval/answer pipeline, what
I found, and the levers I'd pull if I ever wanted to run this for real paying
users. It's written for me — honest about what worked, what didn't, and what it
would cost.

---

## 1. How I evaluate

I don't trust "it feels better." I built two harnesses in `backend/eval/`:

- **`run.py` — retrieval eval.** For each question it runs two retrievers and
  scores them: a naive **dense-only baseline** vs my **full pipeline**. Metrics:
  `Hit@k` (did a relevant chunk make the top k), `MRR@k` (how high the first
  relevant chunk ranked), `Recall@k` (fraction of gold pages retrieved).
- **`judge.py` — answer-quality eval.** Runs the real answer path
  (`retrieve_chunks → generate_answer`) and has an LLM judge score
  **faithfulness** and **relevance** (1–5) against only the retrieved context,
  and quote any unsupported claims.

Both read the same gold set (`dataset.json`). Every run writes a timestamped
`results_*.jsonl` with a git SHA so I can track quality across changes.

**My gold set:** ISO/IEC 27001:2022, 20 cases — 18 factual lookups (clause
numbers, control IDs) + 2 negative/abstention cases. It's deliberately
identifier-heavy, which turns out to matter a lot (see below).

---

## 2. What I found

### Retrieval: my "fancy" pipeline was *losing* to plain dense search

| Metric | Dense baseline | Full pipeline (reranker ON, base) |
| --- | --- | --- |
| Hit@5 | 0.90 | **0.85** 🔻 |
| MRR@5 | 0.76 | **0.70** 🔻 |
| Recall@5 | 0.94 | **0.87** 🔻 |

The reasoning that cracked it: **baseline and pipeline share the same embeddings
and the same chunks.** So if baseline beats pipeline, the problem *can't* be the
embeddings or chunking — it has to be in the stages the pipeline adds
(BM25/RRF/rerank/neighbor/filter). That isolation narrowed the search fast.

### The culprit was the reranker *model* — and swapping it flipped the result

I ran four configs against the same gold set (all metrics @5):

| Config | Hit | MRR | Recall |
| --- | --- | --- | --- |
| Dense baseline (dense-only) | 0.90 | 0.76 | 0.94 |
| RRF-only (reranker off) | 0.90 | 0.81 | 0.94 |
| RRF + `bge-reranker-base` | 0.85 | 0.70 | 0.87 |
| **RRF + `bge-reranker-v2-m3`** | **0.90** | **0.86** | **0.96** |

Three things fell out of this, and the third one reversed my earlier conclusion:

1. **RRF fusion of dense + BM25 genuinely beats dense alone** (MRR 0.76 → 0.81),
   because BM25 nails exact identifiers ("6.1.2", "8.5", "5.23") that pure vector
   search ranks lower.
2. **The weak reranker (`bge-reranker-base`) actively *degraded* ranking** — it
   promoted plausible-but-wrong chunks over exact matches (case `014` dropped
   entirely; `003`/`005`/`011` demoted rank 1 → 2). It scored *worst* of all four.
3. **The strong reranker (`bge-reranker-v2-m3`) is the best config of all** — MRR
   0.86, Recall 0.96, both above RRF-only. It even recovered a multi-page recall
   case (`005`: 0.50 → 1.00) I'd been blaming on chunking.

So the corrected headline — and I want to be precise because I got this wrong at
first: **it's not "reranking hurts." It's "reranker *quality* matters
enormously."** Base was too weak and made things worse; v2-m3 clearly helps. My
earlier "turn the reranker off" was right *for base*, wrong as a general rule. I'd
rather record the reversal than pretend I nailed it first time.

The catch is cost (see §3): v2-m3's +0.05 MRR / +0.02 Recall over RRF-only comes
with ~2× rerank latency, a 2.3 GB resident model, and slow CPU load. So "which
config" is a **deployment-dependent** decision, not a pure quality one:

| Deployment | Call |
| --- | --- |
| GPU / warm pool | v2-m3 on — quality worth it, latency absorbed |
| CPU / scale-to-zero | lean RRF-only — +0.05 MRR probably isn't worth 2.3 GB + 2× latency + cold starts |

### Answer quality (judge eval) — and why I don't over-read it

The judge scores three things: **faithfulness** (grounded in the retrieved
context), **relevance** (addresses the question), and **correctness** (matches
the case's gold answer — the only one judged against ground truth, not just the
context). On this set all three come back **5.0/5**, with 0 unsupported claims,
for *every* config — including the negative/abstention cases (the model correctly
refuses, and the judge counts that as faithful and correct). So grounding,
abstention, *and* factual correctness genuinely work here.

**But I read those 5/5s with heavy skepticism, and so should anyone else:**

- **The eval saturates on this gold set — even correctness.** The questions are
  easy factual lookups where the answer chunk is clearly present, so the LLM nails
  all of them. When *every* answer scores 5 on all three axes, the judge **can't
  discriminate** between configs — it told me nothing about reranker-on vs
  reranker-off, because both produce perfect answers here. Notably, adding
  correctness (judged against the gold answer, not just the context) *didn't*
  break the tie — the answers really are right, they just don't separate.
- **The judge itself is weak.** I'm using a free model (`deepseek-v4-flash-free`),
  and weak LLM judges tend to **rubber-stamp 5/5**. Some runs also emitted messy
  output — I hardened the parser with a regex fallback, but the underlying judge
  reliability is still low.

So **"5/5" here means "the answers are good on easy questions," not "this config
is rigorously better."** To make the judge eval actually discriminate I'd need
(a) a **stronger judge model** (not the free tier) and (b) **harder cases**
(multi-hop, ambiguous, adversarial) so scores spread out instead of pinning at 5.
Until then I trust the *retrieval* metrics (MRR/Recall) far more than these
answer scores, and I'd never present a 5/5 as proof that one config beats another.

### Everything I tried and ruled out

| Experiment | Result | Kept? |
| --- | --- | --- |
| Reranker → `bge-reranker-v2-m3` | ✅ **best overall** (MRR 0.86, Recall 0.96) | Yes, if latency budget allows |
| Reranker off (RRF only) | strong 2nd (MRR 0.81); best latency | the CPU-friendly default |
| Reranker `bge-reranker-base` | ❌ worst (MRR 0.70) — hurt ranking | dropped |
| Neighbor seed-width tweak | inert, no change | reverted |
| Query-term filter on/off | no measurable change | reverted |
| Acronym expansion on/off | no measurable change | reverted |
| Rerank with raw question | made it worse | reverted |

The investigation reversed itself once (base said "reranking hurts"; v2-m3 said
"a good reranker helps"), which is exactly why I ran the ablations instead of
guessing. The real decision is a quality-vs-latency trade, not a bug fix.

### The big caveat I keep front-of-mind

My gold set is **100% factual/identifier lookups** and **English-only** — the
best case for BM25. Even here a *strong* reranker (v2-m3) helped, so if anything
it would help *more* on paraphrased/conceptual/multilingual questions I don't yet
test. Every number here is scoped to English factual retrieval; before I
generalize (or trust an embedding/chunk upgrade) I need a harder gold set
(paraphrased, no-lexical-overlap, multi-page, a non-English doc).

---

## 3. If I wanted to monetize: the levers, the cost, and how I'd solve them

Two cost buckets matter: **query-time latency** (paid every question) and
**ingest-time + resident memory/load** (paid per document and continuously).

### Reranker

- **The model matters more than the on/off decision.** `base` hurt even on
  factual lookups; `v2-m3` helped. A weak reranker is worse than none.
- **When it earns its keep:** with a strong model (v2-m3), and especially on
  conceptual/paraphrased queries where lexical overlap is low.
- **Cost:** it's my biggest query-time line item — ~75 cross-encoder passes per
  query (60 in pass 1 + ~15 in pass 2). `v2-m3` is ~2× base and 2.3 GB resident.
- **How I'd solve the cost:**
  - On CPU / scale-to-zero, default it **off** (RRF-only still beats dense) and
    only turn v2-m3 on where the +0.05 MRR is worth ~2× latency.
  - Route by a cheap classifier (lexical vs conceptual) so only queries that
    benefit pay the rerank cost.
  - Run it on GPU / a warm pool if it's on for everything.
  - Consider **collapsing the two rerank passes into one** — same model and query,
    so the second pass mostly re-scores; it's near-redundant.

### Latency (where it comes from, how I'd cut it)

| Source | Rough weight | How I'd reduce it |
| --- | --- | --- |
| Reranking (when on) | Largest | disable / lighter model / smaller pool |
| LLM answer call | Large | streaming (perceived), smaller/faster model, cap max_tokens |
| LLM query expansion | Medium | it already has a circuit-breaker + timeout; cache; or drop it (the retrieval eval shows the pipeline works without it) |
| Query embedding | Small | already cheap with e5-small; warm model |
| Vector + BM25 search | Small | in-memory BM25 cache (have it), HNSW is fast |

I already have: a **semantic retrieval cache**, in-memory **BM25 payload cache**,
and **background reranker warm-up** on startup. The single biggest latency win I
found was **turning the reranker off** — which also *improved* quality here.

### Load / scale (what breaks with real users)

- **Resident memory:** each container holds the embedder + (if on) the reranker.
  `bge-m3`/`v2-m3` are ~2.3 GB each — that inflates memory and **cold-start** time
  on Modal's scale-to-zero. Solution: keep models small unless a harder eval
  justifies the upgrade; keep a warm pool if traffic is steady.
- **Rate limiting:** mine is in-process, so across N Modal containers the real
  limit is ~limit×N. Solution: a shared store (Redis/Upstash) or edge limiting.
- **Ingestion cost/DoS:** no cap on pages/OCR per doc — a few big image-heavy
  PDFs can exhaust a container. Solution: max-pages/max-OCR caps + per-user
  concurrent-ingest limits. (Tracked in `SECURITY_AUDIT.md` as H-1/H-3.)

### Chunking (a ceiling lever, mostly ingest cost)

- Doesn't explain reranker regressions (shared by both retrievers).
- **Does** cap recall on multi-span answers — my cases `005` (pages 10–11) and
  `017` (pages 17,20,21) sit at 0.5 and 0.33 recall because the answer spans
  boundaries and top-5 can't cover it.
- **Cost:** changing `chunk_size`/`overlap` means **re-ingesting** every doc
  (re-chunk + re-embed) and a bigger index. Query latency barely moves.
- **How I'd solve the multi-span problem** without shrinking chunks everywhere:
  raise `top_k` for list/table questions, or add small overlap — both measured
  against the eval, not guessed.

### Embeddings (a ceiling lever; ingest + storage + a little query cost)

- Not the bottleneck on my current set (baseline dense already ~0.9+).
- Upgrading `e5-small → e5-base/bge-m3` mainly helps **harder/multilingual**
  queries I don't yet test.
- **Cost:** re-ingest everything (2×–5× embed time), index storage/RAM scales with
  dimension (384 → 768 → 1024 = ~2×–2.7×), heavier resident model, longer
  cold-starts.
- **Language note:** the `-m3` models are multilingual heavyweights. My corpus is
  English, so I'd be paying for capacity I don't use — an English-specialized
  model of similar size would likely give better quality-per-compute.

### Cost per query (the money part)

Each normal question can fire **query-expansion LLM call + answer LLM call**, and
each judge eval adds another. For a paying product:
- Cache aggressively (semantic cache already helps).
- Drop query expansion if the eval says it isn't earning its call (mine largely
  doesn't affect retrieval).
- Pick a cost-appropriate answer model; stream to improve perceived latency.
- Watch the provider fallback chain (Opencode → Gemini → OpenRouter) — free tiers
  have hard quotas; real traffic needs a paid tier somewhere.

---

## 4. What I'd do next (in order)

1. Build a **harder gold set** (paraphrased, multi-page, non-English) so the
   ceiling levers (reranker model, embeddings, chunking) become *measurable*
   instead of blind bets.
2. Re-test `v2-m3` and embedding upgrades against that harder set.
3. Only then decide which ceiling levers are worth their latency/load for a paid
   product.

The theme: **measure first, then spend latency.** Everything above came from the
eval telling me the truth, including the uncomfortable truth that my reranker was
making things worse.
