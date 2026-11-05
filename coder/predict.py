"""Prediction pipeline.

Phase 0: a constant-code baseline so the end-to-end pipeline is green from the
first commit and passes the mechanical gates (every id gets a valid code).

Later phases replace `Predictor.predict` with:
  1. BM25 retrieval over WHO-enriched code text  -> shortlist of candidates
  2. LLM rerank (Claude Haiku) that picks the best 3 at the right specificity
  3. A no-key fallback that returns the retrieval top-3

The only hard contract: `predict` and `fallback` always return a list of valid
MMS codes (strings), best first. Never raise to the caller.
"""

# Placeholder baseline code — a real, valid MMS 2026-01 category.
# (Malaria due to Plasmodium falciparum, unspecified.) Replaced in Phase 2+.
_BASELINE = ["1F40.Z"]


class Predictor:
    def __init__(self) -> None:
        pass

    def predict(self, text: str) -> list[str]:
        """Return up to 3 MMS codes, best first, for a single note."""
        return list(_BASELINE)

    def fallback(self) -> list[str]:
        """Always-available answer used when anything upstream fails."""
        return list(_BASELINE)
