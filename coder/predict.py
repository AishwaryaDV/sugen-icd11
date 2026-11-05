"""Prediction pipeline: BM25 retrieval -> LLM rerank -> fallback.

1. Retrieve a ~40-candidate shortlist with BM25 over WHO-enriched text.
2. If an API key is present, Claude Haiku reranks the shortlist and picks the
   best 3 at the right specificity.
3. No key / API error / empty rerank -> return the retrieval top-3.

Hard contract: `predict` always returns up to 3 valid MMS codes, never raises.
"""
from coder.retrieval import Retriever
from coder.rerank import make_reranker

# Safe default if retrieval yields nothing or the index fails to load (valid
# MMS code: Malaria due to Plasmodium falciparum, unspecified).
FALLBACK_CODES = ["1F40.Z"]

_CANDIDATES = 40  # shortlist size handed to the reranker (dev recall@40 ~0.83)


class Predictor:
    def __init__(self) -> None:
        self.retriever = Retriever()
        # Anthropic preferred, OpenAI fallback, None if no key -> retrieval-only.
        # (Brief requires a valid answer for every note even with no key set.)
        self.reranker = make_reranker()
        # Optional wall-clock deadline (monotonic seconds). When set and passed,
        # predict() skips the LLM and uses instant retrieval so the run always
        # finishes within the time cap (an unfinished note scores 0).
        self.deadline = None

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
        import time

        time_ok = self.deadline is None or time.monotonic() < self.deadline
        if self.reranker is not None and time_ok:
            # LLM diagnosis-extraction before retrieval bridges symptom-only
            # notes to the diagnosis name (BM25 can't infer it). Retrieve on the
            # note plus the expansion (weighted), then rerank.
            try:
                expansion = self.reranker.expand_diagnosis(text)
            except Exception:  # noqa: BLE001
                expansion = ""
            query = text + (" . " + (expansion + " ") * 3 if expansion else "")
            cand = [c for c, _ in self.retriever.search(query, k=_CANDIDATES)]
            if not cand:
                return list(FALLBACK_CODES)
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
            return cand[:3]  # rerank failed/empty -> retrieval top-3

        # No-key path: pure retrieval.
        cand = [c for c, _ in self.retriever.search(text, k=_CANDIDATES)]
        return cand[:3] or list(FALLBACK_CODES)

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
