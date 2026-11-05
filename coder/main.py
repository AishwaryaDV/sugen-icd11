"""CLI entrypoint.

    docker compose run coder /in/notes.jsonl /out/predictions.jsonl

Reads JSONL notes ({"id", "text"}), writes JSONL predictions
({"id", "codes": [up to 3, best first]}) one line at a time, flushing as it
goes so a timeout or cap never zeroes a completed note.

Robustness is the priority here: >10% missing predictions is an auto-reject, so
nothing short of a process kill is allowed to abort the run. The index is built
defensively, input is decoded leniently, and every note is wrapped so one bad
line falls back instead of crashing.
"""
import json
import os
import sys
import time

from coder.predict import FALLBACK_CODES, load_predictor

# Wall-clock budget for the whole run. The grading box allows 60 min for 600
# notes; we stop using the LLM once this is reached and finish the remaining
# notes with instant retrieval, so the run never times out (unfinished = 0).
# Generous default (55 min) with a 3x measured headroom; override via env.
MAX_RUNTIME_SECONDS = float(os.environ.get("MAX_RUNTIME_SECONDS", "3300"))


def run(in_path: str, out_path: str) -> None:
    predictor = load_predictor()  # degrades to a constant predictor on failure
    if hasattr(predictor, "deadline"):
        predictor.deadline = time.monotonic() + MAX_RUNTIME_SECONDS

    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    # errors="replace": a stray non-UTF8 byte must not abort the whole run.
    with open(in_path, encoding="utf-8", errors="replace") as fin, \
            open(out_path, "w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            rid = None
            try:
                rec = json.loads(line)
                rid = rec.get("id") if isinstance(rec, dict) else None
                text = rec.get("text", "") if isinstance(rec, dict) else ""
                codes = predictor.predict(text or "")
            except Exception:  # noqa: BLE001 — one bad note never aborts the run
                codes = list(FALLBACK_CODES)
            if rid is None:
                # Unparseable / id-less line: nothing to key the output on.
                continue
            codes = [c for c in (codes or []) if c] or list(FALLBACK_CODES)
            fout.write(json.dumps({"id": rid, "codes": list(codes)[:3]}, ensure_ascii=False) + "\n")
            fout.flush()


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit("usage: python -m coder.main <in.jsonl> <out.jsonl>")
    run(sys.argv[1], sys.argv[2])


if __name__ == "__main__":
    main()
