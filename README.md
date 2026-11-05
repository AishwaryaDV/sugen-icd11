# ICD-11 coder

Reads a clinical consult note and proposes the ICD-11 MMS (2026-01) code(s).

## Run

From a clean clone:

```
docker compose run coder /in/notes.jsonl /out/predictions.jsonl
```

Input: JSONL, one `{"id", "text"}` per line. Output: JSONL, one
`{"id", "codes": [up to 3, best first]}` per line. Every input id appears in the
output. With no `ANTHROPIC_API_KEY` set, the system still answers every note via
the retrieval-only fallback (lower accuracy).

## Approach

Retrieval then rerank:
1. **Retrieve** — BM25 over WHO-enriched code text (title + definition + index
   terms + inclusions + synonyms) narrows 18,375 codes to a shortlist.
2. **Rerank** — Claude Haiku picks the best 3 from the shortlist at the right
   specificity (most specific the note supports; `.Z` when detail is absent).
3. **Fallback** — no key / API error / timeout returns the retrieval top-3.

## Results
<!-- TODO: dev score from score.py (slice A), and our hidden-score estimate. -->

## Data added
<!-- TODO: WHO ICD-11 enrichment (definitions, index terms, inclusions, synonyms),
     pulled from the official WHO ICD-API served offline (release 2026-01). -->

## How we evaluated beyond the 60 dev notes
<!-- TODO: cross-validation on dev; hand-written / translated out-of-distribution
     probes across chapters not in the dev set. -->

## One place AI tooling was wrong and we caught it
<!-- TODO -->

## Hours spent
<!-- TODO: one line. -->
