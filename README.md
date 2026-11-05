# ICD-11 coder

Reads an outpatient consult note and proposes up to 3 ICD-11 MMS (2026-01) codes,
best first.

## Run

```
docker compose run coder /in/notes.jsonl /out/predictions.jsonl
```

Input: JSONL `{"id", "text"}` per line. Output: JSONL `{"id", "codes":[≤3]}` per
line; every input id appears. The box supplies `ANTHROPIC_API_KEY` and/or
`OPENAI_API_KEY`; with no key, the retrieval-only fallback still answers every
note. Predictions stream to disk as we go, and a wall-clock guard degrades to
instant retrieval near the time cap so the run never times out.

## Approach — retrieve then rerank, keyless fallback at every step

1. **Enrich** (build time): each of the 18,375 codes is expanded with its WHO
   definition, synonyms, index terms, and inclusions. Bare titles barely match
   real notes; this enrichment is what makes retrieval work.
2. **Retrieve**: the note is preprocessed (drop ruled-out differentials, up-weight
   the Assessment/Diagnosis line, expand abbreviations), then BM25 over the
   enriched text returns ~40 candidates. With a key, one small LLM call first
   extracts the likely diagnosis — bridging symptom-only notes ("burning pain
   eased by food" → gastritis) and any language → English.
3. **Rerank**: Claude Haiku 4.5 picks the best 3 at the right specificity — most
   specific the note *supports*, the `.Z` unspecified variant when detail is
   absent, never a guessed subtype.

No key / API error / timeout → retrieval top-3. Output is always valid MMS codes.

## Results

- **Dev (`score.py`, 60 notes): ~67/75** (66–69 across runs; top-1 ~0.88, top-3
  ~0.92), verified from a clean clone via the exact command. No-key fallback:
  26.2/75. The few-note wobble is reranker LLM sampling.
- **Estimated hidden: ~82–86/100** — slice A tracks dev (~67/75); slice B
  (different distribution, all chapters, not always English) ~18–20/25, grounded
  in the multilingual test below.
- Within all caps: **~23 min and ~$1.90 per 600 notes** (caps 60 min / $6), 0
  missing, 0 invalid, runtime network = model APIs only.

## Data added

WHO ICD-11 enrichment (definitions, synonyms, index/inclusion terms, FSNs) for
every MMS 2026-01 code, pulled from the **official WHO ICD-API run offline from
its Docker image** (`whoicd/icd-api`, release pinned to 2026-01) — no rate limits,
reproducible, shipped in `data/who_enrichment.json` so grading needs no WHO
access. Verified byte-identical to the WHO cloud API on a 36-code spot-check.
Residual (`.Z`/`.Y`) codes have no entity of their own, so they inherit their
parent's enrichment, tagged unspecified.

## How we evaluated beyond the 60 dev notes

- **Per-note analysis** (`score.py --per-note`) to separate retrieval-recall
  misses from rerank/depth errors and target each.
- **Back-translation of the real dev notes** (`eval_dev_fr/sw.jsonl`): the
  authentic 60 notes (real gold) translated to French (60) and Swahili (20), so
  only language varies — verifying multilingual robustness on real data, not
  invented notes. **French 62.5/75, Swahili 62.5/75** vs English ~67 (~5-pt
  penalty).
- **Out-of-distribution probes** (`sliceB_probes.jsonl`): notes in chapters absent
  from dev (migraine, depression, otitis, back pain, anaemia…) — all land
  top-1/top-3, confirming the retriever generalises across the code space.

## Where AI tooling was wrong and we caught it

Measuring after every change caught two silent AI-introduced failures:

1. **Preprocessing order.** The generated pipeline ran abbreviation-expansion
   *before* A/P-weighting; expansion strips the `A:`/`Dx:` punctuation the latter
   needs, so A/P-weighting became a silent no-op. Tell: the combined config scored
   *worse* than A/P alone. Reordering lifted recall@40 0.70 → 0.83 (dev 19.6 →
   26.2).
2. **Unsupported SDK param.** An added `temperature=0` raised on every rerank call;
   the per-call fallback swallowed it and the whole run silently dropped to
   retrieval-only (26.2 vs ~67). Caught because the score fell to the no-key
   baseline. (Likewise, the back-translation eval caught a query-weighting bug
   that tanked non-English notes — invisible on the English dev set.)

## Hours spent

~4–5 hours (setup, data, development, evaluation, writeup).
