# ICD-11 coder

Reads an outpatient consult note and proposes up to 3 ICD-11 MMS (2026-01) codes,
best first.

## Run

From a clean clone:

```
docker compose run coder /in/notes.jsonl /out/predictions.jsonl
```

Input: JSONL, one `{"id", "text"}` per line. Output: JSONL, one
`{"id", "codes": [up to 3, best first]}` per line. Every input id appears in the
output. The grading box supplies `ANTHROPIC_API_KEY` and/or `OPENAI_API_KEY`;
with **no** key set the system still answers every note via the retrieval-only
fallback (lower accuracy). Predictions are written as we go, and a wall-clock
guard degrades to instant retrieval near the time cap so the run never times out.

## Approach

Three stages (retrieve → rerank), with a keyless fallback at every step:

1. **Enrich** (build time) — each of the 18,375 codes is expanded with its WHO
   definition, synonyms, index terms and inclusions. Titles alone barely match
   real notes; the enrichment is what makes retrieval work.
2. **Retrieve** — the note is preprocessed (strip ruled-out differentials,
   up-weight the Assessment/Diagnosis line, expand clinical abbreviations), then
   BM25 over the enriched text returns ~40 candidates. With a key, one small LLM
   call first extracts the likely diagnosis to bridge symptom-only notes
   ("burning pain eased by food" → gastritis) and any language → English.
3. **Rerank** — Claude Haiku 4.5 picks the best 3 from the candidates at the
   right specificity: most specific the note *supports*, the `.Z` unspecified
   variant when the detail is absent, never a guessed subtype.

No key / API error / timeout → return the retrieval top-3. Output is always a
subset of valid MMS codes.

## Results

- **Dev score (`score.py`, 60 notes): ~66–67 / 75** — top-1 ~0.87, top-3 ~0.92.
  The score varies by about one note run-to-run because the reranker LLM samples;
  verified from a clean clone via the exact grading command (66.2/75 keyed).
  No-key fallback: 26.2 / 75.
- **Estimated hidden score: ~80–85 / 100.** Slice A (same distribution) should
  track dev at ~66–67/75. Slice B (different distribution, all chapters, not
  always English) is estimated conservatively at ~17–20/25 from our own probes
  (below).
- Well within the operating caps: **~21 min and ~$1.90 per 600 notes** (caps: 60
  min, $6), 0 missing, 0 invalid codes.

## Data added

WHO ICD-11 enrichment (definitions, synonyms, index terms, inclusions,
fully-specified names) for every MMS 2026-01 code. Pulled from the **official WHO
ICD-API run offline from its Docker image** (`whoicd/icd-api`, release pinned to
2026-01) — no rate limits, fully reproducible, shipped in the repo
(`data/who_enrichment.json`) so grading needs no network beyond the model API.
Verified byte-identical to the WHO cloud API on a 36-code spot-check. Residual
(`.Z`/`.Y`) codes have no entity of their own, so they inherit their parent's
enrichment, tagged unspecified.

## How we evaluated beyond the 60 dev notes

- **Per-note error analysis** (`score.py --per-note`) to separate retrieval-recall
  misses from rerank/depth errors and target each.
- **A 12-note slice-B probe set** (`data/sliceB_probes.jsonl`): 6 out-of-
  distribution chapters absent from the dev set (migraine, depression, otitis
  media, low back pain, anaemia, appendicitis) and 6 multilingual notes
  (French/Swahili/Spanish, translated from known-gold cases). This confirmed the
  pipeline is multilingual and generalises across chapters, and surfaced a general
  over-specification bug we then fixed.

## One place AI tooling was wrong and we caught it

While adding note preprocessing, the AI-generated pipeline applied the transforms
in the order *abbreviation-expansion → A/P-weighting*. Abbreviation expansion
strips punctuation, which deleted the `A:` / `Dx:` markers the A/P-weighting step
relies on — so A/P-weighting silently became a no-op. We caught it because the
combined config scored *worse* than A/P-weighting alone (recall@40 0.767 vs
0.800). Reordering so A/P-weighting runs while the punctuation is intact lifted
recall@40 from 0.70 to 0.83 and the dev score from 19.6 to 26.2.

## Hours spent

<!-- TODO: fill in -->
