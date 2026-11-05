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
    "Rules:\n"
    "- Choose the MOST SPECIFIC code the note supports. A general/parent code is "
    "wrong when a more specific child code fits the documented detail.\n"
    "- When the note does NOT state the detail a more specific code requires, "
    "choose the unspecified variant (code ending in Z, e.g. .Z) rather than "
    "guessing a specific subtype.\n"
    "- Ignore diagnoses the note rules out or excludes; code the condition the "
    "clinician actually diagnosed or treated.\n"
    "- Only choose codes from the candidate list, written exactly as given.\n"
    "- Output only the chosen codes, best first, one per line. No other text."
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

    def complete(self, system: str, user: str) -> str:
        resp = self.client.messages.create(
            model=self.model, max_tokens=120, system=system,
            messages=[{"role": "user", "content": user}],
        )
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
