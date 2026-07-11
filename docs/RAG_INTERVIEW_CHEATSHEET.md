# RAG Interview Cheatsheet

My notes for talking about this project honestly. The goal isn't to oversell it —
it's to show I understand RAG deeply, know where it breaks, and can prove my
claims with evals. Being modest about the failure modes is the point; it's what
separates "I did a tutorial" from "I've actually run this."

---

## The 30-second version

I built a citation-first RAG system over PDFs. A user uploads a document, I chunk
and embed it, and answer questions grounded strictly in that document with page
citations. The interesting engineering is the retrieval pipeline and — more
importantly — the **eval harness I use to decide what actually belongs in it**.

---

## My architecture (the flow I can draw on a whiteboard)

**Ingest:** PDF → PyMuPDF text extraction (+ Tesseract OCR on image/low-text
pages) → `RecursiveCharacterTextSplitter` (900 chars, 180 overlap) → embed with
`multilingual-e5-small` (`passage:` prefix) → store text + vector + metadata in
ChromaDB.

**Query:** question → acronym expansion → **dense (E5) + BM25** retrieval →
**Reciprocal Rank Fusion** → *(optional cross-encoder rerank + neighbor
expansion)* → citations → citation-aware LLM answer with page references.

**Around it:** Supabase auth + storage + Postgres, per-user isolation, a
multi-provider LLM fallback chain, an input security guard (jailbreak/PII), and
per-request + per-LLM-call logging.

---

## Decisions I made and *why* (the part they probe)

- **Hybrid dense + BM25, fused with RRF.** Dense catches meaning; BM25 catches
  exact tokens (clause numbers, IDs). RRF combines the two *rankings* so I never
  compare incompatible raw scores. I can prove this helps: on my gold set RRF
  lifted MRR from 0.76 (dense-only) to 0.81.
- **Reranker *quality* matters more than reranking itself — and I can prove it.**
  Four configs on my gold set: dense (MRR 0.76) < base reranker (0.70) < RRF-only
  (0.81) < `bge-reranker-v2-m3` (0.86). So the *weak* reranker (`bge-reranker-base`)
  *hurt* — it promoted plausible-but-wrong chunks over exact matches; the *strong*
  one (v2-m3) is the best config of all. I keep it behind a flag: v2-m3 on where I
  have the latency budget (it's ~2× slower + 2.3 GB), RRF-only as the CPU-friendly
  default.
- **Citation-first prompting.** The model must answer only from retrieved context
  and cite pages; document text is wrapped as untrusted data so a poisoned PDF
  can't inject instructions.
- **e5-small + 900-char chunks.** Deliberately modest defaults; I treat model/chunk
  upgrades as measured bets, not defaults.

---

## Where it *won't* fall over (honest strengths)

- **Exact-identifier factual lookups.** Hybrid retrieval nails clause/control
  numbers — this is its sweet spot.
- **Grounding, correctness & hallucination.** Answers are constrained to retrieved
  context and cite pages, and the model correctly abstains ("not in this
  document"). My judge scores three axes — faithfulness, relevance, and
  **correctness** (matched against the gold answer, not just the context) — and all
  three come back 5/5. But I say that with a caveat (below): the set is easy and the
  judge is weak, so 5/5 shows it *works*, not that it's rigorously optimal.
- **Provider outages.** Ordered fallback (Opencode → Gemini → OpenRouter) so one
  provider flaking doesn't take answers down.
- **Prompt injection from user input.** A deterministic guard blocks jailbreak
  attempts and flags PII-seeking queries before they reach the model.

## Where it *will* fall over (the failure modes I own)

- **Multi-span / list answers.** When the answer spans several pages, top-5
  retrieval misses some — my eval shows recall dropping to 0.5 and 0.33 on exactly
  those cases. It's a chunking/`top_k` limitation, and I know it because I measured
  it.
- **Paraphrased / conceptual queries.** My gold set is all factual lookups, so I
  *haven't proven* it on questions with no lexical overlap — and that's exactly
  where a strong reranker (v2-m3) would help even more. Every conclusion here is
  scoped to English factual retrieval, not universal.
- **Scanned / OCR-heavy PDFs.** Garbled OCR text degrades both retrieval and the
  answer; I've seen mangled tokens in image-heavy pages.
- **Prompt injection via document content.** I hardened the prompt, but the guard
  is pattern-based and evadable. For a multi-tenant/B2B setup (admin uploads,
  employees ask) this isn't fully solved.
- **Scale & latency.** Rate limiting is in-process (weak across containers),
  ingestion has no page/OCR caps, and reranking (when on) is a real latency cost.
  Fine for a demo; not yet hardened for real multi-user traffic.
- **Retention / privacy.** I log prompts and answers, and deletion doesn't fully
  erase them yet — a GDPR gap I've documented but not closed.

---

## The story I actually lead with

Not "I built a RAG pipeline" — everyone says that. Mine is: **"I built the eval
that caught my own pipeline losing to a naive baseline, and it made me reverse my
own conclusion twice before I trusted it."**

The reranker investigation is the anecdote:
1. I suspected the fancy pipeline was better; my eval said it was *worse* than
   plain dense search.
2. I reasoned that since baseline and pipeline share embeddings and chunks, the
   regression had to be in the added stages — which isolated it fast.
3. I ablated each stage. The `bge-reranker-base` cross-encoder was demoting exact
   matches, so I concluded "reranking hurts, turn it off" — and RRF-only beat the
   baseline (MRR 0.76 → 0.81).
4. Then I tested a *stronger* reranker (`v2-m3`) — expecting it to still lose — and
   it was the **best config of all** (MRR 0.86). So I'd been wrong: it wasn't
   "reranking hurts," it was "a *weak* reranker hurts." I updated the conclusion.
5. I stayed modest: v2-m3 wins on quality but costs ~2× latency + 2.3 GB, so the
   real answer is a deployment trade-off, and it's all scoped to factual English
   retrieval until I build a harder gold set.

That arc — hypothesis → measurement → isolation → a conclusion I then had to
*reverse* when new evidence came in — is the thing I want them to remember. Being
willing to say "I was wrong, here's the better answer" is the signal.

---

## Likely questions & my honest answers

- **"How do you know retrieval got better?"** → I don't eyeball logs; I run a gold
  set with Hit@k/MRR@k/Recall@k and a dense-vs-hybrid ablation. Numbers above.
- **"How do you catch hallucination?"** → citation-first prompting + an LLM-judge
  eval scoring faithfulness, relevance, and **correctness** (the last one against
  the gold answer, so it's not just "grounded" but "actually right"), plus flagged
  unsupported claims. And I'll pre-empt the obvious follow-up: all three currently
  score 5/5, but that's because the set is easy and my judge is a weak free model
  that rubber-stamps — the eval *saturates*, so it can't yet discriminate configs.
  To make it rigorous I'd use a stronger judge and harder cases. I trust the
  retrieval metrics more for now.
- **"Why not just use a bigger reranker / embedder?"** → I did test a bigger
  reranker: `v2-m3` measurably beat everything (MRR 0.86), but at ~2× latency and
  2.3 GB — so it's a real quality-vs-cost trade, not a free win. For *embeddings*
  I haven't upgraded yet because my gold set is too easy to detect the benefit; I'd
  build a harder set before paying the re-ingest + storage cost.
- **"What would you do for production?"** → distributed rate limiting, ingestion
  caps, retention/erasure, finish prompt-injection hardening — I keep these in a
  security audit doc rather than pretending they're done.
- **"What's the weakest part?"** → the gold set is too easy and too English-only,
  so several of my conclusions are scoped narrower than they might sound. I'd fix
  the eval before I trust the next optimization.

---

## One-liner to close on

*"The pipeline is decent, but the thing I'm actually proud of is that I can prove
what's in it earns its place — and I was willing to delete the impressive-sounding
component when the eval said it was hurting."*
