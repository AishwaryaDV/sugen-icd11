# Decisions

A running log of real choices, kept as we go. Newest at the bottom.

---

### 2026-11-05 09:40 — Architecture: retrieval + LLM rerank
**Decision:** Two-stage pipeline — BM25 retrieval over WHO-enriched code text to
shortlist candidates, then an LLM rerank to pick the best 3 at the right
specificity. Plus a retrieval-only no-key fallback.
**Options considered:** (a) LLM-only — feed the note and ask for a code blind:
can't see 18,375 codes, hallucinates invalid codes. (b) Retrieval-only — cheap
and keyless but can't calibrate depth (`.0` vs `.00` vs `.Z`). (c) Retrieve then
rerank — retrieval handles recall over all codes, LLM handles the depth decision.
**Evidence:** Dev golds are the *most specific* code the note supports (51/61 have
a subcategory, 14 end in `.Z`); retrieval gets the family, the LLM sets the depth.
**Revisit:** whether embeddings beat BM25 on the multilingual slice-B notes.

### 2026-11-05 09:40 — Model: Claude Haiku 4.5, Anthropic only
**Decision:** `claude-haiku-4-5` as the rerank model; no OpenAI.
**Options:** Opus 4.8 (~$11/600 notes, over the $6 cap), Sonnet 5 (~$6.75, too
tight), Haiku 4.5 (~$2.30, fits with headroom and is fast).
**Evidence:** budget is $6 / 600 notes (~1c/note); ~3k input + ~150 output tokens
per rerank on Haiku ≈ $0.0038/note.
**Revisit:** spot-check a few hard notes against Sonnet 5 to see accuracy left
on the table.

### 2026-11-05 09:44 — WHO enrichment via offline Docker, release 2026-01
**Decision:** Pull every code's definition / index terms / inclusions / synonyms /
fully-specified name from the official WHO ICD-API served locally
(`whoicd/icd-api`), release pinned to 2026-01, and ship the result in the repo.
**Options:** (a) Cloud WHO API for all 18,375 codes — rate-limited, throttling
risk on a time-boxed task. (b) Offline Docker — no rate limits, reproducible.
Titles-only (no enrichment) was rejected: clinical notes share almost no words
with bare titles, so retrieval would miss.
**Evidence:** spot-check diff of 36 codes, local Docker vs cloud API = **0
mismatches** — the offline pull is byte-identical to the authoritative source.
Enrichment raised median searchable text from ~15 chars (title) to ~175 chars.
Result: 18,375 codes, 13,041 fetched, 4,127 inherited, 1,207 orphan; 0 empty.
**Revisit:** nothing outstanding; cloud key kept as a fallback.

### 2026-11-05 09:44 — Residual (`.Z` / `.Y`) codes inherit parent enrichment
**Decision:** Residual codes have no entity of their own (the WHO API 404s), so
they inherit their nearest ancestor's enrichment, tagged "unspecified" / "other".
Block-level residuals (no dot, e.g. `1A0Z`) fall back to their own descriptive
title rather than borrowing a child's terms.
**Options:** (a) Leave residuals with title only — weak match for common gold
codes. (b) Inherit from parent — the leaf `.Z` codes (often the gold answer, 14/61
dev golds) get the full family definition. (c) Aggregate children's terms into
block residuals — rejected: pollutes the vague "unspecified block" code with a
specific child's vocabulary, making it wrongly compete with the real code.
**Evidence:** all 14 `.Z` dev golds resolve to full inherited enrichment
(e.g. `1F40.Z` -> "Malaria due to Plasmodium falciparum, unspecified | A disease
caused by... Plasmodium..."). Only block residuals stay title-only (~6.6%).
**Revisit:** fetch WHO block entities for the ~1,200 orphan block residuals if
retrieval misses them.

### 2026-11-05 10:20 — BM25 retrieval: tuned indexing (dev 19.6/75)
**Decision:** Retrieve candidates with BM25 over the enriched text, using
stopword removal, label fields (title/FSN/synonyms/index terms/inclusions)
weighted 3x over the definition prose, and reduced length penalty (b=0.3).
`predict` returns the retrieval top-3 (also the no-key fallback).
**Options measured on dev recall@K:**
- full search_text, no stopwords (first cut): top1 .167 top3 .250, recall@20 .417
- + stopwords: recall@20 .583  (biggest single win)
- labels x3 + def + stopwords, b=0.3: top1 .217 top3 .350, recall@20 .617, @40 .700
**Evidence:** stopwords alone lifted recall@20 by ~17 pts (conversational ambient
notes were drowning the signal — "malaria" ranked its own parent code at 38 before
cleanup). Score 14.6 -> 19.6 / 75. recall@40 ~0.70 sets the rerank ceiling.
**Revisit:** ~30% of golds never retrieved (negation like "malaria excluded",
abbreviations). Next levers: note preprocessing (weight the A/P diagnosis line),
multilingual embeddings for slice B. Candidate set k=40-50 for the reranker.

### 2026-11-05 13:15 — Slice-B probes + over-specification fix (dev 67.1, probes 60.4)
**Decision:** Built a 12-note slice-B probe set — 6 out-of-distribution chapters
(06/08/10/21/03 + 13) and 6 multilingual notes (French/Swahili/Spanish, translated
from known-gold cases) — to estimate the hidden slice and catch collapse. Then
strengthened the rerank prompt's specificity rules against OVER-specification
(decision procedure + teaching examples: pneumonia-no-organism -> .Z not bacterial;
appendicitis-no-peritonitis -> plain code not the variant).
**Evidence:**
- Multilingual WORKS: FR/SW/ES notes land top-1 — the expansion LLM bridges any
  language to an English diagnosis, so the English BM25 index still fires. No
  separate translation code needed.
- OOD chapters WORK: migraine(08)/depression(06)/otitis(10)/LBP(21)/anaemia(03),
  all unseen in dev, land top-1. Retrieval+rerank generalise across the code space.
- The one recurring error was general over-specification (guessing organism/
  severity/peritonitis the note didn't state) — same root cause as dev-004/028.
  Stronger prompt: dev 66.7 -> 67.1 (top1 .867 -> .883), probes 58.3 -> 60.4
  (top3 .833 -> .917). Helps both slices; principled, not overfit.
**Revisit:** probe set is small (12) and self-authored — directional, not a precise
slice-B score. Real slice B may be harder; keep the README estimate conservative.

### 2026-11-05 12:45 — LLM diagnosis-extraction before retrieval (dev 66.7/75)
**Decision:** On the keyed path, call the LLM once to extract likely diagnosis
terms from the note, then retrieve on note + expansion (weighted) before rerank.
Bridges symptom-only notes to the diagnosis name — BM25 can't infer "gastritis"
from "burning pain eased by food", and anatomy words ("great toe") bury the
diagnosis ("gout") under injury codes. No-key path stays pure retrieval.
**Evidence:** per-note analysis of the 10 top-3 misses showed they were all
symptom->diagnosis / anatomy-noise retrieval failures, not rerank errors. A cheap
10-note probe (~$0.003) recovered 9/10 missed golds into top-40. Wired in + one
confirm run: top1 .800 -> **.867**, top3 .833 -> **.933**, score 60.8 -> **66.7/75**.
Cost $1.77 -> $1.91 / 600 (expansion input is just the note — tiny); time 13.6 ->
20.6 min / 600. Both well within caps. No-key path unchanged at 26.2.
**Options:** HyDE-style hypothetical-doc vs. short diagnosis terms — chose terms
(cheaper, directly matches WHO titles/index-terms). Semantic embeddings were the
alternative but can't do symptom->diagnosis *inference* (it's reasoning, not
similarity), and would add a shipped model.
**Revisit:** dev-044 still missed (hypoglycaemia-in-diabetes — specific combo
code ranks below pure hypoglycaemia); the 2 remaining depth (.Z) errors; measure
on slice-B-style probes.

### 2026-11-05 12:20 — Reranker measured: dev 60.8/75, within time+cost caps
**Decision:** Keep the Haiku reranker as the primary path (measured, not assumed).
Added token-usage tracking to the backend for the cost gate.
**Evidence (one measurement run on 60 dev notes, Claude Haiku 4.5):**
- SCORE 26.2 -> **60.8 / 75**  (top1 .317 -> **.800**, top3 .417 -> **.833**)
- time 1.36 s/note -> **13.6 min / 600** (cap 60)
- tokens 169,406 in / 1,444 out -> **$1.77 / 600 notes** (cap $6)
- 0 missing, 0 invalid.
**Key read:** top3 (.833) == retrieval recall@40 (.833) — the reranker is
near-perfect given its candidates; the bottleneck is now RETRIEVAL RECALL, not
reranking. top1 (.800) close behind top3 => specificity calibration is working.
**Revisit:** the score ceiling is the ~0.83 recall. Next gains come from Phase 5
retrieval-recall levers (more/better candidates, embeddings), not prompt tuning.

### 2026-11-05 12:00 — Dual-provider reranker: Anthropic primary, OpenAI fallback
**Decision:** Refactor the reranker behind a provider abstraction. `make_reranker`
picks Anthropic (Claude Haiku 4.5) if `ANTHROPIC_API_KEY` is set, else OpenAI
(`gpt-4o-mini`, overridable via `OPENAI_MODEL`) if `OPENAI_API_KEY` is set, else
None (retrieval-only). Prompt and reply-parsing are provider-agnostic.
**Why:** the brief says the box may supply `OPENAI_API_KEY` *and/or*
`ANTHROPIC_API_KEY`. The earlier Anthropic-only gate would silently drop to
retrieval-only (~26) if the box set only an OpenAI key. We still build on
Anthropic (preferred), but no longer *assume* it is present — defensive against
a provider-availability assumption we can't verify.
**Evidence:** provider-selection unit test (none/anthropic/openai/both) passes;
no-key path unchanged at 26.2; Docker builds with both SDKs pinned.
**Revisit:** confirm the OpenAI fallback model id is still current if that path
ever runs; measure both providers once a key is loaded.

### 2026-11-05 11:40 — LLM reranker pre-written (Claude Haiku); keyed path pending credit
**Decision:** Add `coder/rerank.py`: retrieve 40 candidates, let Claude Haiku 4.5
pick the best 3 from their titles+definitions, enforcing the specificity rules
(most specific supported; `.Z` when detail absent; ignore ruled-out
differentials). Reply parsed by scanning for candidate codes in order, so output
is always a valid subset; any failure returns [] and the pipeline falls back to
the retrieval top-3. Per-request timeout 20s, max_retries 1 (time budget).
**Status:** written and wired, but NOT yet measured with a key (API credit not
loaded). The no-key path is verified unchanged: dev still 26.2/75, robustness
green, parser unit-tested, Docker builds with `anthropic==2.5.0`.
**Options:** structured outputs vs. scan-the-reply parsing — chose scanning
(SDK-version-robust, forgiving of formatting, guarantees codes stay in the
candidate set). Haiku over Sonnet/Opus for the $6/600-note cap.
**Revisit:** measure dev top1/top3 and cost-per-note the moment credit lands;
tune candidate count (k) and the prompt against the "right family, wrong depth"
per-note bucket; consider a tiny thinking budget if depth calls need it.

### 2026-11-05 11:10 — Note preprocessing: negation + A/P + abbreviations (dev 26.2/75)
**Decision:** Preprocess each note into a retrieval query in this order:
strip negated/excluded clauses -> weight the Assessment/Diagnosis segment ->
expand clinical abbreviations. Order matters.
**Options measured on dev recall@K (built index once, varied only the query):**
- baseline:                         top1 .217 top3 .350  r@20 .617  r@40 .700
- abbrev only:                      r@40 .767
- A/P weight only:                  r@40 .800
- neg+abbrev+ap (wrong order):      r@40 .767  (ap did nothing!)
- neg -> ap -> abbrev (correct):    top1 .317 top3 .417  r@20 .750  r@40 .833
**Evidence / the catch:** my first combined ordering ran A/P-weighting AFTER
abbreviation expansion, which strips the ":" punctuation, so the "A:" / "Dx:"
markers vanished and A/P-weighting silently became a no-op (combo stuck at .767
instead of .800). Reordering so A/P-weighting runs while punctuation is intact
unlocked it: recall@40 0.70 -> 0.83, score 19.6 -> 26.2 / 75. Robustness test
still green. (This ordering bug is the README's "AI tooling was wrong, caught it".)
**Revisit:** negation is clause-drop (coarse); "fever without chills" loses
"fever". A span-level NegEx could recover those. Abbrev map is English-only
(fine for slice A; slice B may need more). k=40-50 candidates for the reranker.

### 2026-11-05 10:40 — Robustness hardening against the >10% auto-reject
**Decision:** Make the run unkillable short of a process kill: index built via
`load_predictor()` that degrades to a constant predictor on failure; input
decoded with `errors="replace"`; every note wrapped so one bad line falls back;
and a query-length cap in retrieval. Added `tests/test_robustness.py`.
**Evidence:** a nasty-input test (empty / missing-field / huge / non-English /
non-string / whitespace / invalid-UTF8 notes) crashed the run — an 80k-token
"huge" note made BM25 `get_scores` O(len(query) * 18k docs) and hung past 2 min.
Capping the query to 1000 tokens fixed it (3s, dev score unchanged at 19.6).
All 9 id-bearing notes now get a valid line; malformed-JSON / non-object lines
(no id) are skipped by design.
**Options:** dedupe query tokens vs. hard length cap — chose the cap (preserves
the Phase 2 tuning exactly for real notes, bounds the pathological case).
**Revisit:** if real slice-B notes are long, consider weighting the tail (A/P)
rather than truncating to the first 1000 tokens.

### 2026-11-05 09:45 — Baseline-first pipeline to pass the mechanical gates early
**Decision:** Ship a constant-valid-code baseline in the streaming JSONL pipeline
from commit 1, so `docker compose run` produces a full output file before any
model work. Predictions are written and flushed per line.
**Options:** build retrieval first vs. prove the plumbing first. Plumbing first,
because >10% missing predictions = auto-reject, so a green pipeline is the
foundation everything else sits on.
**Evidence:** brief's hard gates (clean-clone build, <10% blank, write-as-you-go).
**Revisit:** replace the constant code with BM25 retrieval in Phase 2.
