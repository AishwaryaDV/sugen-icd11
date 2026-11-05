"""Prediction pipeline.

Phase 2: BM25 retrieval over WHO-enriched code text. `predict` returns the
retrieval top-3 (best first). This is also the no-key fallback path.

Later phases insert an LLM rerank between retrieval and the returned 3 to fix
specificity (most specific the note supports; `.Z` when detail is absent). The
hard contract stays: always return a list of valid MMS codes, never raise.
"""
from coder.retrieval import Retriever

# Safe default if retrieval yields nothing or the index fails to load (valid
# MMS code: Malaria due to Plasmodium falciparum, unspecified).
FALLBACK_CODES = ["1F40.Z"]


class Predictor:
    def __init__(self) -> None:
        self.retriever = Retriever()

    def predict(self, text: str) -> list[str]:
        """Return up to 3 MMS codes, best first, for a single note."""
        hits = self.retriever.search(text, k=50)
        codes = [c for c, _ in hits[:3]]
        return codes or list(FALLBACK_CODES)

    def fallback(self) -> list[str]:
        """Always-available answer used when anything upstream fails."""
        return list(FALLBACK_CODES)


class ConstantPredictor:
    """Last-resort predictor if the index can't be built (corrupt data, OOM).
    Guarantees the run still produces a valid line for every note."""

    def predict(self, text: str) -> list[str]:
        return list(FALLBACK_CODES)

    def fallback(self) -> list[str]:
        return list(FALLBACK_CODES)


def load_predictor():
    """Build the real predictor; degrade to the constant one rather than
    aborting the whole run (0 predictions => auto-reject)."""
    try:
        return Predictor()
    except Exception:  # noqa: BLE001
        return ConstantPredictor()
