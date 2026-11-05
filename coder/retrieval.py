"""BM25 retrieval over WHO-enriched code text.

Loads the shipped enrichment file and builds an in-memory BM25 index at startup.
No network, no key -- this is also the fallback path.

Indexing choices (tuned on the 60 dev notes, recall@K):
- Stopwords removed (biggest single win; conversational ambient notes especially).
- Label fields (title, FSN, synonyms, index terms, inclusions) weighted 3x over
  the definition prose, which is long and adds noise.
- BM25 length penalty reduced (b=0.3) so short leaf codes aren't buried under
  long category definitions.
"""
import heapq
import json
import os
import re

from rank_bm25 import BM25Okapi

from coder.preprocess import build_query

_DATA = os.path.join(os.path.dirname(__file__), "..", "data", "who_enrichment.json")
_TOKEN = re.compile(r"[a-z0-9]+")

# English + conversational/clinical filler. Removing these lifts dev recall@20
# from ~0.42 to ~0.58 on its own.
STOPWORDS = set(
    """a an the and or of to in on with without for from by at as is are was were be been being
    this that these those it its he she they them his her their you your we our i me my mr mrs ms dr
    doctor patient no not any has have had do does did will would can could should may might must at
    least since ago about over under per also then than so if but out up down very more most some such
    each other one two three today yesterday day days week weeks month months year years am pm okay ok
    yes yeah well now here there what when how why who which into onto off again back only just like get
    got see seen say said tell told come came feel feeling felt go going went take taking took give given
    use used last next new old right left""".split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall((text or "").lower()) if len(t) > 1 and t not in STOPWORDS]


def _index_text(entry: dict) -> str:
    """Build the document indexed for a code: label fields x3 + definition x1."""
    enr = entry.get("enrichment") or {}
    labels = [entry.get("title") or "", enr.get("fsn") or ""]
    labels += enr.get("synonym") or []
    labels += enr.get("indexTerm") or []
    labels += enr.get("inclusion") or []
    label_text = " | ".join(p for p in labels if p)
    definition = enr.get("definition") or ""
    return " | ".join([label_text, label_text, label_text, definition])


class Retriever:
    def __init__(self, path: str = _DATA) -> None:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.codes: list[str] = list(data.keys())
        corpus = [tokenize(_index_text(data[c])) for c in self.codes]
        self.bm25 = BM25Okapi(corpus, b=0.3)

    def search(self, text: str, k: int = 50) -> list[tuple[str, float]]:
        """Return up to k (code, score) pairs, best first."""
        # Preprocess the note into a retrieval query (negation stripping, A/P
        # weighting, abbreviation expansion), then cap length: BM25 scoring is
        # O(len(query) * n_docs), so a pathologically long note would otherwise
        # blow the time budget. Real consult notes are a few hundred tokens.
        query = tokenize(build_query(text))[:1000]
        scores = self.bm25.get_scores(query)
        top = heapq.nlargest(k, range(len(scores)), key=scores.__getitem__)
        return [(self.codes[i], float(scores[i])) for i in top]
