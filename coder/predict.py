"""Prediction pipeline.

Phase 2: BM25 retrieval over WHO-enriched code text. `predict` returns the
retrieval top-3 (best first). This is also the no-key fallback path.

Later phases insert an LLM rerank between retrieval and the returned 3 to fix
specificity (most specific the note supports; `.Z` when detail is absent). The
hard contract stays: always return a list of valid MMS codes, never raise.
"""
from coder.retrieval import Retriever

# Safe default if retrieval somehow yields nothing (valid MMS code).
_FALLBACK = ["1F40.Z"]


class Predictor:
    def __init__(self) -> None:
        self.retriever = Retriever()

    def predict(self, text: str) -> list[str]:
        """Return up to 3 MMS codes, best first, for a single note."""
        hits = self.retriever.search(text, k=20)
        codes = [c for c, _ in hits[:3]]
        return codes or list(_FALLBACK)

    def fallback(self) -> list[str]:
        """Always-available answer used when anything upstream fails."""
        return list(_FALLBACK)
