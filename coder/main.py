"""CLI entrypoint.

    docker compose run coder /in/notes.jsonl /out/predictions.jsonl

Reads JSONL notes ({"id", "text"}), writes JSONL predictions
({"id", "codes": [up to 3, best first]}) one line at a time, flushing as it
goes so a timeout or cap never zeroes a completed note. Every input id must
appear in the output, so per-note failures fall back rather than crash.
"""
import json
import os
import sys

from coder.predict import Predictor


def run(in_path: str, out_path: str) -> None:
    predictor = Predictor()
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(in_path, encoding="utf-8") as fin, open(out_path, "w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            rid = None
            try:
                rec = json.loads(line)
                rid = rec.get("id")
                codes = predictor.predict(rec.get("text", "") or "")
            except Exception:  # noqa: BLE001 — never let one bad note abort the run
                codes = predictor.fallback()
            if rid is None:
                # Unparseable line with no id: nothing to key the output on. Skip.
                continue
            fout.write(json.dumps({"id": rid, "codes": list(codes)[:3]}, ensure_ascii=False) + "\n")
            fout.flush()


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit("usage: python -m coder.main <in.jsonl> <out.jsonl>")
    run(sys.argv[1], sys.argv[2])


if __name__ == "__main__":
    main()
