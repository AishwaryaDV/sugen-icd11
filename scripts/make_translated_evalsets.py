#!/usr/bin/env python3
"""Build grounded multilingual eval sets by translating the REAL dev notes.

Unlike hand-authored probe notes, these keep the authentic clinical content and
the real gold labels -- only the language changes. So they isolate the "not
always English" risk on genuine data, with no invented ground truth.

Translates all 60 dev notes to French, and a 20-note subset to Swahili, via the
LLM. One-time; outputs are committed so scoring needs no re-translation.

Usage:  python3 scripts/make_translated_evalsets.py   (needs ANTHROPIC_API_KEY)
"""
import json
import os
import sys

from anthropic import Anthropic

DEV = "data/dev_notes.jsonl"
cl = Anthropic(timeout=30, max_retries=2)

LANGS = {
    "fr": ("French", 60),
    "sw": ("Swahili", 20),
}


def translate(text: str, language: str) -> str:
    sys_p = (
        f"Translate this clinical consult note into {language}. Preserve all "
        "clinical meaning, measurements, and abbreviations' intent. Keep it in the "
        "same terse consult-note style. Output only the translation."
    )
    r = cl.messages.create(model="claude-haiku-4-5", max_tokens=600, system=sys_p,
                           messages=[{"role": "user", "content": text}])
    return "".join(b.text for b in r.content if getattr(b, "type", None) == "text").strip()


def main():
    notes = [json.loads(l) for l in open(DEV)]
    for code, (language, n) in LANGS.items():
        out = f"data/eval_dev_{code}.jsonl"
        with open(out, "w", encoding="utf-8") as f:
            for note in notes[:n]:
                tr = translate(note["text"], language)
                f.write(json.dumps({"id": note["id"], "gold": note["gold"],
                                    "text": tr, "lang": code}, ensure_ascii=False) + "\n")
                print(f"  {note['id']} -> {language}", file=sys.stderr)
        print(f"wrote {out} ({n} notes, {language})")


if __name__ == "__main__":
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("needs ANTHROPIC_API_KEY")
    main()
