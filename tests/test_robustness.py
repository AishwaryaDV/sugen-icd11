"""Robustness regression test.

>10% missing predictions is an auto-reject, so the run must survive every
malformed note: empty text, missing field, a pathologically huge note,
non-English text, non-string text, whitespace, and invalid UTF-8 bytes. Every
id-bearing note must get exactly one line with valid MMS codes.

Run: python tests/test_robustness.py   (or: pytest tests/)
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)  # make `coder` importable when run as a plain script

from coder.main import run  # noqa: E402
VALID = {r["code"] for r in json.load(open(os.path.join(ROOT, "data", "mms-2026-01.json")))}


def _write_nasty(path: str) -> set[str]:
    lines = [
        json.dumps({"id": "ok", "text": "28M fever chills, smear P. falciparum malaria"}),
        json.dumps({"id": "empty", "text": ""}),
        json.dumps({"id": "notext"}),
        json.dumps({"id": "huge", "text": "fever cough " * 40000}),
        json.dumps({"id": "unicode", "text": "fièvre, toux et paludisme confirmé"}),
        json.dumps({"id": "ws", "text": "   \n  "}),
        json.dumps({"id": "intext", "text": 12345}),
        "",                              # blank line
        "{bad json here",                # malformed JSON -> skipped (no id)
        json.dumps("just a string"),     # valid JSON, not an object -> skipped
        json.dumps({"id": "afterbad", "text": "acute tonsillitis, sore throat"}),
    ]
    with open(path, "wb") as f:
        f.write(("\n".join(lines)).encode("utf-8"))
        f.write(b'\n{"id":"badbyte","text":"fever \xff\xfe cough"}\n')  # invalid UTF-8
    return {"ok", "empty", "notext", "huge", "unicode", "ws", "intext", "afterbad", "badbyte"}


def test_robustness():
    with tempfile.TemporaryDirectory() as d:
        inp, outp = os.path.join(d, "in.jsonl"), os.path.join(d, "out.jsonl")
        expect_ids = _write_nasty(inp)
        run(inp, outp)  # must not raise
        out = [json.loads(line) for line in open(outp)]
    ids = {o["id"] for o in out}
    assert expect_ids <= ids, f"missing ids: {expect_ids - ids}"
    for o in out:
        assert o["codes"], f"empty codes for {o['id']}"
        assert all(c in VALID for c in o["codes"]), f"invalid code for {o['id']}: {o['codes']}"


if __name__ == "__main__":
    test_robustness()
    print("robustness test passed")
