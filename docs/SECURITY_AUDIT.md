# PDF Chat — Security, Reliability & Accessibility Review

I ran a full-stack review of my app and then fixed the issues I could scope safely. This is my record of what I found, what I changed, and how I'm thinking about the parts I haven't fixed yet.

**Scope:** Full-stack — FastAPI/Modal/Supabase/Chroma backend + React/Vite/Supabase-JS frontend. I traced flows end-to-end (auth, upload→ingest, RAG query/stream, provider fallback, DB layer, frontend rendering & concurrency) rather than reviewing files in isolation.
**Status:** I finished a remediation pass on the subset I prioritized. I verified it with 73 backend unit tests (green) and a passing frontend type-check + build.
**Legend:** ✅ Resolved · 🟡 Partially resolved · ⛔ Open

---

## 1. Status summary

| Severity | Total | ✅ Resolved | 🟡 Partial | ⛔ Open |
| --- | --- | --- | --- | --- |
| High | 3 | 1 | 0 | 2 |
| Medium | 9 | 5 | 2 | 2 |
| Low | 8 | 8 | 0 | 0 |
| Informational | 5 | 3 (noted) | 0 | 2 |
| **Pre-review blockers** | 3 | 3 | 0 | 0 |

I've closed the exploitable and quick-win surface. What's left is resource/cost hardening, data retention, and one accessibility item — all things I consider pre-B2B, and none of them a confirmed data-exposure or auth flaw.

---

## 2. Pre-review production blockers I fixed first

| # | Problem | What I did | Verified |
| --- | --- | --- | --- |
| B-1 | Single LLM provider on a free tier; no fallback → hard outage if it flaps | Added an ordered fallback **Opencode → Gemini → OpenRouter** (`providers.py`); keyless providers are skipped; the real provider is recorded in logs | Live-tested Gemini end-to-end (grounded, cited answers) |
| B-2 | No rate limiting on expensive endpoints | Added a per-user sliding-window limiter (`rate_limit.py`) on `/chat/query`, `/chat/stream`, `/documents/upload` | Unit tests; see **H-3** for the distributed caveat |
| B-3 | Duplicated/misspelled env var (`app_enviorment`) could leave `is_production` false in prod → docs exposed | Consolidated to a single `app_env`; fixed `/health` | App boots; cleaned the config test env |

---

## 3. Findings I resolved

| ID | Sev | Category | Problem | What I did | Verified |
| --- | --- | --- | --- | --- | --- |
| H-2 | High | Security | Upload trusted the spoofable `content-type`; nothing proved the bytes were a PDF → arbitrary files fed to PyMuPDF/Tesseract | Added `looks_like_pdf()` to check the `%PDF-` magic bytes before I store/process anything (`documents.py`) | 6 unit tests |
| M-1 | Med | Security | CORS `allow_origin_regex=".*\.vercel\.app"` + credentials trusted every Vercel site | Removed the wildcard; kept an explicit allowlist + an optional narrow `CORS_ALLOW_ORIGIN_REGEX` (off by default) | App boots; config |
| M-2 | Med | Prompt Injection | I was injecting document text into the prompt un-delimited, with no defense against embedded instructions or PII-seeking queries | Hardened `SYSTEM_PROMPT`; wrapped context in `<document_context>` untrusted markers; added a deterministic input guard (`security_guard.py`) that blocks jailbreak/injection and flags PII asks | 14 unit tests · **partial**, see §5 |
| M-4 | Med | Race | Concurrent first message → duplicate default-session insert → unhandled 500 | Made `get_or_create_default_session` catch the unique-index race and re-select | Code review + import |
| M-8 | Med | Accessibility | Muted/small text ≈3.6:1 — below WCAG AA 4.5:1 | Darkened `--muted` (light + dark) | ⚠ Still need to verify with a contrast tool |
| M-9 | Med | Security | Tokens in `localStorage` with no CSP → one XSS = account takeover | Added a CSP + `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options: DENY`, `Permissions-Policy` via `vercel.json` | Build; CSP is a baseline (`connect-src 'self' https:`) I still want to pin |
| L-1 | Low | Security | Unsanitized `file.filename` used in the storage key & DB | Added `sanitize_filename()` — strips path parts, control/unsafe chars, length-caps | 7 unit tests |
| L-2 | Low | Reliability | Streaming path had no provider fallback; hardcoded `model_used` | Routed streaming through the same fallback chain; report the real provider/model; removed the dead `stream_opencode` | Import + tests |
| L-3 | Low | Reliability/Data | `api_logs.provider` was hardcoded `'opencode'` even when Gemini served | Added `insert_log(provider=...)`; answer + stream paths pass the real provider | Code review |
| L-4 | Low | Accessibility | Rotating loading messages were re-announced by screen readers every 2.2s | Announce the stable label once (`aria-live`); mark the flavor text `aria-hidden` | Build |
| L-5 | Low | Accessibility | `<th>` missing `scope`; two `<h1>` per view; no skip link | Added `scope="col"`; demoted the sidebar to `<h2>`; added a skip-to-content link | Build |
| L-6 | Low | Performance | `renderMessageContent` re-parsed on every render; no memo | Wrapped `MessageBubble` in `React.memo` + `useMemo` on the parsed content | Build |
| L-7 | Low | Reliability | In-flight answer wasn't cancelled on document switch/unmount | Added an `AbortController` that cancels on document change; stays silent on abort | Build |
| L-8 | Low | Visual | Long unbreakable strings overflowed the message bubble | Added `overflow-wrap: anywhere` to the message content | Build |

---

## 4. Partially resolved

| ID | Sev | Problem | What I did | What's left |
| --- | --- | --- | --- | --- |
| M-2 | Med | Prompt injection / PII extraction | Hardened the main `generate_answer` prompt; the input guard covers all modes at the route layer | The **summary** (`summary.py`) & **comparison** (`analysis.py`) prompts still inject context un-delimited; the guard is pattern-based (evadable) — an LLM-based classifier would raise assurance |
| M-5 | Med | Non-idempotent chat writes → duplicate messages | Added a client re-entrancy guard to block rapid double-submit; M-4 fixed the server race | No cross-retry / cross-tab idempotency key; true dedup across retries is still open |
| M-6 | Med | Tenant isolation rests solely on my app-level `user_id` filters (service role bypasses RLS) | Added `user_id` scoping to the document-update path (defense-in-depth) | Structural: reads still use the service role; ideally I'd move to per-request-JWT reads or add automated isolation tests as a backstop |

---

## 5. Still open

| ID | Sev | Category | Problem | Impact | How I'd fix it |
| --- | --- | --- | --- | --- | --- |
| H-1 | High | Reliability / DoS | No cap on page count / OCR work per document; 200-DPI raster + Tesseract per image page | A few large image-heavy PDFs exhaust Modal CPU/memory & drive cost | Enforce max pages / max OCR pages / total-time budget; per-user concurrent-ingest limit; reject over-limit at upload |
| H-3 | High | Security / Reliability | My rate limiter is in-process; Modal runs N containers → effective limit ≈ limit×N and resets on cold start | The main guard against H-1/abuse is weaker than configured | Back it with a shared store (Redis/Upstash) keyed by user, or enforce at the edge (Vercel/Cloudflare) |
| M-3 | Med | Privacy / GDPR | `api_logs` stores prompts/answers/raw responses indefinitely; document delete only nulls FKs, retaining the content | "Right to erasure" not satisfied; growing PII store | Retention TTL purge; delete/scrub associated logs & messages on document/account deletion |
| M-7 | Med | Accessibility | Modals lack focus trap, focus move on open, Escape-to-close, focus restoration | Keyboard/screen-reader users can't operate my dialogs (WCAG 2.2 2.4.3/2.1.2) | Move focus in on open, trap Tab, handle Escape, restore focus to the trigger on close (delete + clear-chat dialogs) |
| I-8 | Info | Visual Consistency | Hardcoded border-radii instead of tokens; brand/terminology drift ("PDF Chat" vs "Chat with PDF") | Cosmetic; polish/brand coherence | Route radii through `--radius*`; standardize the product name & `X-Title` header |

---

## 6. How I'm thinking about the open items

**I treat H-1 (ingestion DoS) and H-3 (distributed rate limiting) as one problem wearing two hats.** H-3 is the guard; H-1 is what it guards against. Fixing either alone is a half-measure — my per-container limiter can't really cap the expensive ingestion path when Modal load-balances across containers. So the order I'll follow is: (1) put hard caps inside ingestion so a single job can't run away, then (2) move the limiter to a shared/edge store so the *number* of jobs is bounded globally. Both are genuinely pre-launch for real multi-user traffic; for my single-user demo I'm treating them as acceptable risk. Neither is a data-exposure issue — it's availability and cost.

**M-3 (retention/erasure) is the one with legal teeth, not just engineering.** Everything else here degrades UX or cost; this one is a UK/EU compliance gap the moment I have real users. It's unglamorous — a purge job plus a delete-cascade for the logged content — but I don't want to ship it to real users unresolved, and I'll pair it with a short, honest privacy policy.

**M-7 (modal focus) is the highest-value thing I have left.** It's a bounded, well-understood accessibility fix — a focus-trap applied to my two dialogs — with no architectural risk. It only stayed open because it wasn't in the batch I just did. I'll do it next; it's an afternoon, not a project.

**I want to be precise about calling M-2 "mitigated."** The prompt hardening is my real defense against the core threat — a poisoned document trying to give the model instructions. The input guard catches user-typed attacks and audits PII requests, but it's pattern-based, so it's evadable, and I still haven't hardened two secondary prompt paths (summary and comparison). So I've cut the risk a lot, but I won't call it closed before any multi-tenant/B2B use — that's exactly the setup where a poisoned onboarding doc could affect other users. My next steps are to harden the remaining prompts and, if I want higher assurance, add an LLM-judge layer (accepting the latency/cost trade-off).

**I'd describe the M-5 and M-6 remainders as "correct today, fragile structurally."** In practice I prevent the M-5 duplicates (re-entrancy guard + the server race fix); what I'm missing is a formal idempotency key that would make retries provably safe. M-6 has no exploit today — every user-facing read *is* scoped — but that safety rests on my own discipline, because the service role bypasses RLS. Both are about turning "correct because I was careful" into "correct because it can't be otherwise." That's a maturity investment, not a bug fix.

**I put I-8 (visual/brand drift) last on purpose.** It's real and worth a cleanup pass, but it changes nothing about security, correctness, or accessibility. I'll do it when I'm polishing for demos.

---
<!-- 
## 7. Release recommendation

| Context | My call | Why |
| --- | --- | --- |
| Portfolio / demo (single trusted user) | **Ship with known risks** | No exploitable cross-tenant/auth/data-exposure flaw; the open items are cost/availability/polish. I'd do M-7 first (cheap a11y win). |
| Real multi-user SaaS (onboarding pitch) | **Don't ship** until H-1, H-3, M-3 are resolved and M-2 is completed | Unvalidated-scale ingestion + weak distributed limiting is a realistic cost/availability incident; indefinite retention is a compliance gap; prompt-injection isn't fully closed for the exact admin-uploads/employees-ask model I'm targeting. |

---

## 8. Verification snapshot

- **Backend:** 73 unit tests passing (retrieval/RRF math, acronyms, eval metrics, judge parsing, upload validation, provider fallback ordering, rate limiter, security guard, results writer).
- **Frontend:** `tsc` type-check + `vite build` passing.
- **Live:** Gemini fallback exercised end-to-end against real ingested documents (grounded, page-cited answers).
- **Not verified here:** contrast ratios (need a checker — M-8), CI on GitHub (runs on push), full end-to-end auth flows (need live secrets). -->
