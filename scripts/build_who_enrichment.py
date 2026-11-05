#!/usr/bin/env python3
"""Build the WHO ICD-11 enrichment file for every MMS 2026-01 code.

Source: WHO ICD-11 API served locally from the offline Docker image
(whoicd/icd-api), release pinned to 2026-01. No rate limits, no network at
grade time -- the output JSON is shipped in the repo.

For each code we pull title + definition + index terms + inclusions + synonyms
+ fully-specified name, and assemble a single `search_text` blob used by the
retrieval index. Residual codes (.Z / .Y) have no entity of their own (the API
404s), so they inherit their nearest ancestor's enrichment, tagged unspecified.

Usage:
  python3 build_who_enrichment.py [--limit N] [--out PATH] [--port 8382]
"""
import argparse, json, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor

MMS_PATH = "data/mms-2026-01.json"
LOCAL = "http://localhost:{port}/icd/release/11/2026-01/mms/{id}"
HEADERS = {"Accept": "application/json", "API-Version": "v2", "Accept-Language": "en"}


def txt(v):
    return v.get("@value") if isinstance(v, dict) else v


def entity_id(uri):
    return uri.rstrip("/").split("/")[-1]


def fetch_entity(url):
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r), None
    except urllib.error.HTTPError as e:
        return None, e.code
    except Exception as e:  # noqa: BLE001
        return None, str(e)


def extract(ent):
    """Pull the enrichment fields we care about from a WHO entity."""
    return {
        "title": txt(ent.get("title")),
        "definition": txt(ent.get("definition")),
        "fsn": txt(ent.get("fullySpecifiedName") or {}),
        "synonym": [txt(s.get("label")) for s in ent.get("synonym", [])],
        "indexTerm": [txt(s.get("label")) for s in ent.get("indexTerm", [])],
        "inclusion": [txt(s.get("label")) for s in ent.get("inclusion", [])],
    }


def parent_code(code):
    """Derive the parent code for a residual (.Z/.Y) code by stripping the suffix."""
    c = code.strip()
    if c and c[-1] in ("Z", "Y"):
        c = c[:-1]
        if c.endswith("."):
            c = c[:-1]
        return c
    return None


def build_search_text(code, title, enr, residual):
    parts = [title or ""]
    if enr:
        parts.append(enr.get("fsn") or "")
        parts.append(enr.get("definition") or "")
        parts += enr.get("synonym") or []
        parts += enr.get("indexTerm") or []
        parts += enr.get("inclusion") or []
    if residual:
        parts.append("unspecified" if code.rstrip().endswith("Z") else "other specified")
    seen, out = set(), []
    for p in parts:
        p = (p or "").strip()
        if p and p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    return " | ".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="process only first N codes (testing)")
    ap.add_argument("--out", default="data/who_enrichment.json")
    ap.add_argument("--port", type=int, default=8382)
    ap.add_argument("--workers", type=int, default=16)
    a = ap.parse_args()

    rows = json.load(open(MMS_PATH))
    if a.limit:
        rows = rows[: a.limit]
    by_code = {r["code"]: r for r in rows}

    # Pass 1: fetch every code's entity (threaded; residuals will 404)
    raw = {}

    def work(r):
        ent, err = fetch_entity(LOCAL.format(port=a.port, id=entity_id(r["uri"])))
        return r["code"], (extract(ent) if ent else None), err

    fetched = failed = 0
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for i, (code, enr, err) in enumerate(ex.map(work, rows), 1):
            raw[code] = enr
            if enr:
                fetched += 1
            else:
                failed += 1
            if i % 1000 == 0:
                print(f"  fetched {i}/{len(rows)} (ok {fetched}, miss {failed})", file=sys.stderr)

    # Pass 2: resolve misses (residuals / 404) by inheriting nearest ancestor
    inherited = orphan = 0
    out = {}
    for r in rows:
        code = r["code"]
        enr = raw.get(code)
        residual = bool(r.get("residual"))
        if enr is None:
            anc, hops = code, 0
            while enr is None and hops < 6:
                anc = parent_code(anc) or (anc[: anc.rfind(".")] if "." in anc else None)
                if not anc:
                    break
                enr = raw.get(anc)
                hops += 1
            if enr is not None:
                inherited += 1
            else:
                orphan += 1
        out[code] = {
            "code": code,
            "title": r.get("title"),
            "chapter": r.get("chapter"),
            "depth": r.get("depth"),
            "leaf": r.get("leaf"),
            "residual": residual,
            "enrichment": enr,  # may be None for true orphans
            "search_text": build_search_text(code, r.get("title"), enr, residual),
        }

    json.dump(out, open(a.out, "w"), ensure_ascii=False)
    print(f"codes {len(rows)}  fetched {fetched}  inherited {inherited}  orphan {orphan}")
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
