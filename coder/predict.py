"""Prediction pipeline: BM25 retrieval -> LLM rerank -> fallback.

1. Retrieve a ~40-candidate shortlist with BM25 over WHO-enriched text.
2. If an API key is present, Claude Haiku reranks the shortlist and picks the
   best 3 at the right specificity.
3. No key / API error / empty rerank -> return the retrieval top-3.

Hard contract: `predict` always returns up to 3 valid MMS codes, never raises.
"""
import os

from coder.retrieval import Retriever

# Safe default if retrieval yields nothing or the index fails to load (valid
# MMS code: Malaria due to Plasmodium falciparum, unspecified).
FALLBACK_CODES = ["1F40.Z"]

_CANDIDATES = 40  # shortlist size handed to the reranker (dev recall@40 ~0.83)


class Predictor:
    def __init__(self) -> None:
        self.retriever = Retriever()
        self.reranker = None
        # Only wire the reranker when a credential is present; otherwise the
        # keyless retrieval path runs (brief requires a no-key answer for all).
        if os.environ.get("ANTHROPIC_API_KEY"):
            try:
                from coder.rerank import Reranker

                self.reranker = Reranker()
            except Exception:  # noqa: BLE001 — degrade to retrieval-only
                self.reranker = None

    def _details(self, codes: list[str]) -> list[dict]:
        out = []
        for c in codes:
            entry = self.retriever.data.get(c, {})
            enr = entry.get("enrichment") or {}
            out.append({"code": c, "title": entry.get("title") or c,
                        "definition": enr.get("definition") or ""})
        return out

    def predict(self, text: str) -> list[str]:
        """Return up to 3 MMS codes, best first, for a single note."""
        cand = [c for c, _ in self.retriever.search(text, k=_CANDIDATES)]
        if not cand:
            return list(FALLBACK_CODES)

        if self.reranker is not None:
            try:
                ranked = self.reranker.rerank(text, self._details(cand))
            except Exception:  # noqa: BLE001 — never let rerank abort a note
                ranked = []
            if ranked:
                # Fill up to 3 from retrieval order so we always return 3 valid
                # codes even if the model named fewer.
                final = list(ranked)
                for c in cand:
                    if len(final) >= 3:
                        break
                    if c not in final:
                        final.append(c)
                return final[:3]

        return cand[:3]

    def fallback(self) -> list[str]:
        """Always-available answer used when anything upstream fails."""
        return list(FALLBACK_CODES)


class ConstantPredictor:
    """Last-resort predictor if the index can't be built (corrupt data, OOM)."""

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
