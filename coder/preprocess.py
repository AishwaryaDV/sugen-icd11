"""Note -> retrieval query preprocessing.

Three domain-general transforms, applied in this order (order matters — see
below). Tuned on dev recall@K; together they lift recall@40 from 0.70 to 0.83
and top-1 from 0.22 to 0.32.

1. strip_negation    drop excluded differentials ("malaria excluded") so BM25
                     stops matching the disease that was ruled OUT.
2. weight_assessment repeat the Assessment / Diagnosis segment (where the
                     codeable diagnosis lives) over history/ROS noise. Runs
                     BEFORE abbreviation expansion so the "A:" / "Dx:" markers
                     still have their punctuation.
3. expand_abbrev     add expansions for clinical shorthand (URTI, SOB, MPS...)
                     so note vocab bridges to the WHO enrichment vocab. Runs
                     last (it drops punctuation, which the step above needs).
"""
import re

# Conservative, high-confidence-in-clinical-context expansions. Added (not
# substituted), so the original token is always retained too.
ABBREV = {
    "urti": "upper respiratory tract infection", "uri": "upper respiratory infection",
    "uti": "urinary tract infection", "sob": "shortness of breath dyspnoea",
    "mps": "malaria parasites", "mrdt": "malaria rapid diagnostic test",
    "rdt": "rapid diagnostic test", "htn": "hypertension", "dm": "diabetes mellitus",
    "t2dm": "type 2 diabetes mellitus", "iddm": "diabetes mellitus",
    "copd": "chronic obstructive pulmonary disease", "tb": "tuberculosis",
    "cap": "community acquired pneumonia", "gerd": "gastro-oesophageal reflux",
    "gord": "gastro-oesophageal reflux", "ckd": "chronic kidney disease",
    "aki": "acute kidney injury", "chf": "congestive heart failure",
    "mi": "myocardial infarction", "cva": "cerebrovascular accident stroke",
    "pud": "peptic ulcer disease", "pid": "pelvic inflammatory disease",
    "dvt": "deep vein thrombosis", "pe": "pulmonary embolism",
}

# Exclusion cues: a clause containing one is a ruled-out differential, not the
# diagnosis. Padded with spaces where the token is short to avoid false matches.
NEG_CUES = (
    "excluded", "ruled out", "rule out", "no evidence", "negative",
    "denies", "denied", " -ve ", " neg ",
)

_CLAUSE = re.compile(r"[.,;\n]| - ")
_WORD = re.compile(r"[A-Za-z0-9/]+")
_AP_MARKER = re.compile(r"\b(?:a|assessment|dx|impression|imp|diagnosis|p|plan)\s*[:\-]", re.I)


def strip_negation(text: str) -> str:
    kept = []
    for clause in _CLAUSE.split(text or ""):
        padded = " " + clause.lower() + " "
        if not any(cue in padded for cue in NEG_CUES):
            kept.append(clause)
    return " . ".join(kept)


def weight_assessment(text: str, times: int = 2) -> str:
    segs = [(text or "")[m.end(): m.end() + 120] for m in _AP_MARKER.finditer(text or "")]
    if not segs:
        return text or ""
    return text + (" " + " ".join(segs)) * times


def expand_abbreviations(text: str) -> str:
    out = []
    for w in _WORD.findall(text or ""):
        out.append(w)
        key = w.lower().strip("/")
        if key in ABBREV:
            out.append(ABBREV[key])
    return " ".join(out)


def build_query(text: str) -> str:
    t = strip_negation(text)
    t = weight_assessment(t)
    t = expand_abbreviations(t)
    return t
