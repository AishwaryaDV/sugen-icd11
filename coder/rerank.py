"""LLM reranking (Claude Haiku primary, OpenAI fallback).

Retrieval gets the gold code into the ~40-candidate shortlist (recall ceiling
~0.83 on dev); this step reads the note and the candidates' titles+definitions
and picks the best 3 at the right specificity -- the part BM25 structurally
can't do (depth: .0 vs .00 vs .Z, and ignoring ruled-out differentials).

Provider policy: Anthropic is primary (Claude Haiku 4.5). We only fall back to
OpenAI if no ANTHROPIC_API_KEY is present but an OPENAI_API_KEY is -- the brief
says the grading box may supply either, so we must not assume a provider. The
prompt and reply-parsing are provider-agnostic; only the API call differs.

Robustness: any API/parse failure returns [] and the pipeline falls back to the
retrieval top-3. Per-request timeout + capped retries protect the 60-min budget.
Both the OpenAI and Anthropic Python SDKs honour HTTPS_PROXY (the grading box's
only egress) by default.
"""
import os
import re

MODEL_ANTHROPIC = "claude-haiku-4-5"
MODEL_OPENAI = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

SYSTEM = (
    "You are an expert clinical coder assigning ICD-11 MMS codes to outpatient "
    "consult notes.\n\n"
    "You are given a consult note and a shortlist of candidate ICD-11 codes, each "
    "with its title and definition. Choose the up to 3 candidate codes that best "
    "match the note's diagnosis, best first.\n\n"
    "Pick the code at the RIGHT level of specificity — the most specific code the "
    "note actually SUPPORTS, and no more specific than that:\n"
    "- A more specific child code is correct ONLY IF the note documents the detail "
    "that distinguishes it (the organism, subtype, severity, cause, or site). Do "
    "NOT guess that detail.\n"
    "- When the note names a condition but NOT the distinguishing detail, choose "
    "the unspecified variant (code ending in Z, e.g. '.Z') or the plain parent "
    "category — never a specific child you cannot justify from the text.\n"
    "- Examples of the rule: 'pneumonia' with no organism named -> the unspecified "
    "pneumonia code, NOT the bacterial one. 'Malaria' with no species -> the "
    "unspecified malaria code; only pick the falciparum code if the note says "
    "falciparum. 'Acute appendicitis' with no peritonitis described -> the plain "
    "acute appendicitis code, NOT the with/without-peritonitis variants.\n"
    "- Ignore diagnoses the note rules out or excludes; code the condition the "
    "clinician actually diagnosed or treated.\n\n"
    "Only choose codes from the candidate list, written exactly as given. Output "
    "only the chosen codes, best first, one per line. No other text."
)

EXPAND_SYS = (
    "You are a clinical coder. Read the consult note and output the most likely "
    "diagnosis as 1 to 3 short medical terms (the disease names a coder would look "
    "up in ICD-11), comma-separated. These bridge a note that describes symptoms "
    "to the diagnosis name. Output only the terms, no commentary."
)

_CODE_TOKEN = re.compile(r"[A-Z0-9][A-Z0-9./&-]*")


def _stem(code: str) -> str:
    return code.split("&")[0].split("/")[0].strip().upper()


class _AnthropicBackend:
    name = "anthropic"

    def __init__(self, timeout: float) -> None:
        from anthropic import Anthropic  # lazy import

        self.client = Anthropic(timeout=timeout, max_retries=1)
        self.model = MODEL_ANTHROPIC
        self.in_tokens = 0
        self.out_tokens = 0

    def complete(self, system: str, user: str) -> str:
        # NB: the anthropic SDK no longer accepts a `temperature` kwarg, so we
        # can't force greedy decoding; the reranker is mildly nondeterministic
        # (~1 note/60 wobble). Acceptable: it averages out over 600 notes, and
        # any per-call error here falls back to retrieval anyway.
        resp = self.client.messages.create(
            model=self.model, max_tokens=120, system=system,
            messages=[{"role": "user", "content": user}],
        )
        self.in_tokens += resp.usage.input_tokens
        self.out_tokens += resp.usage.output_tokens
        return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")


class _OpenAIBackend:
    name = "openai"

    def __init__(self, timeout: float) -> None:
        from openai import OpenAI  # lazy import

        self.client = OpenAI(timeout=timeout, max_retries=1)
        self.model = MODEL_OPENAI

    def complete(self, system: str, user: str) -> str:
        resp = self.client.chat.completions.create(
            model=self.model, max_tokens=120,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
        )
        return resp.choices[0].message.content or ""


class Reranker:
    def __init__(self, backend) -> None:
        self.backend = backend

    def expand_diagnosis(self, note: str) -> str:
        """Return short diagnosis terms for the note, or "" on failure. Used to
        bridge symptom-only notes to the diagnosis name before retrieval (BM25
        can't infer 'gastritis' from 'burning pain eased by food')."""
        try:
            return self.backend.complete(EXPAND_SYS, (note or "").strip()).strip()
        except Exception:  # noqa: BLE001
            return ""

    def rerank(self, note: str, candidates: list[dict]) -> list[str]:
        """candidates: [{"code","title","definition"}]. Returns ordered codes
        (a subset of the candidates), or [] on any failure."""
        if not candidates:
            return []
        lines = []
        for c in candidates:
            defn = (c.get("definition") or "").replace("\n", " ")[:300]
            lines.append(f'{c["code"]}: {c.get("title") or ""}' + (f" — {defn}" if defn else ""))
        user = (
            "CONSULT NOTE:\n" + (note or "").strip()
            + "\n\nCANDIDATE CODES:\n" + "\n".join(lines)
            + "\n\nReturn the best up to 3 codes, best first, one per line."
        )
        try:
            text = self.backend.complete(SYSTEM, user)
        except Exception:  # noqa: BLE001 — fall back to retrieval on any API error
            return []
        return self._parse(text, candidates)

    @staticmethod
    def _parse(text: str, candidates: list[dict]) -> list[str]:
        by_stem = {_stem(c["code"]): c["code"] for c in candidates}
        out: list[str] = []
        for tok in _CODE_TOKEN.findall((text or "").upper()):
            code = by_stem.get(_stem(tok.rstrip(".")))
            if code and code not in out:
                out.append(code)
                if len(out) == 3:
                    break
        return out


def make_reranker(timeout: float = 20.0):
    """Build a reranker from whatever key is present (Anthropic preferred).
    Returns None if no key / SDK is available -> retrieval-only path."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return Reranker(_AnthropicBackend(timeout))
        except Exception:  # noqa: BLE001
            pass
    if os.environ.get("OPENAI_API_KEY"):
        try:
            return Reranker(_OpenAIBackend(timeout))
        except Exception:  # noqa: BLE001
            pass
    return None
