"""
queue_to_manifest.py - turn the harvest's extraction_queue.csv into the
manifest.csv that `eps ingest` expects.

The two files describe the same documents in different vocabularies. This is
the translation, and nothing else: no filtering decisions are made silently.
Anything dropped is reported.

Typical pilot (one department, ten documents, mixed types):

    python queue_to_manifest.py --queue extraction_queue.csv ^
        --docs-root . ^
        --out manifest_dfe.csv ^
        --institution "Department for Education" ^
        --limit 8 --sample spread --plus-shortest 2

Everything, for the full run later:

    python queue_to_manifest.py --queue extraction_queue.csv ^
        --docs-root . --out manifest_all.csv

If `eps ingest --write-template` produces different column names from the ones
assumed here, generate a template first and pass it with --template; the header
will be copied from it verbatim.
"""

import argparse
import csv
import os
import sys
from collections import defaultdict

DEFAULT_COLUMNS = [
    "path", "institution", "country", "url", "title",
    "doc_type", "date", "delivery_status", "speaker_hint",
]


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def row_to_manifest(r, docs_root, country):
    rel = (r.get("text_file") or "").replace("\\", os.sep).replace("/", os.sep)
    full = os.path.normpath(os.path.join(docs_root, rel)) if docs_root else rel
    return {
        "path": full,
        "institution": r.get("institution", "").strip(),
        "country": country,
        "url": r.get("url", "").strip(),
        "title": r.get("document_title", "").strip(),
        "doc_type": r.get("normalised_document_type", "").strip(),
        "date": r.get("date", "").strip(),
        "delivery_status": "unknown",
        "speaker_hint": r.get("expected_officeholder", "").strip(),
    }


def pick(rows, limit, mode):
    """Choose `limit` rows from `rows` (each an (index, dict) pair)."""
    if limit is None or limit >= len(rows):
        return rows
    if mode == "first":
        return rows[:limit]
    if mode == "longest":
        return sorted(rows, key=lambda p: -int(p[1].get("word_count") or 0))[:limit]
    # spread: round-robin across document types, longest first inside each type
    by_type = defaultdict(list)
    for pair in rows:
        by_type[pair[1].get("normalised_document_type", "")].append(pair)
    for k in by_type:
        by_type[k].sort(key=lambda p: -int(p[1].get("word_count") or 0))
    order = sorted(by_type, key=lambda k: -len(by_type[k]))
    out = []
    while len(out) < limit and any(by_type[k] for k in order):
        for k in order:
            if by_type[k] and len(out) < limit:
                out.append(by_type[k].pop(0))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--docs-root", default="",
                    help="prefix for the text_file paths; leave blank to keep "
                         "them relative")
    ap.add_argument("--country", default="UK")
    ap.add_argument("--institution", action="append", default=None,
                    help="repeatable; exact name as it appears in the queue")
    ap.add_argument("--doc-type", action="append", default=None,
                    help="repeatable: speech, press_release, statement, letter...")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--sample", choices=["first", "spread", "longest"],
                    default="spread")
    ap.add_argument("--plus-shortest", type=int, default=0,
                    help="also include the N shortest documents, as negative "
                         "controls that should yield nothing")
    ap.add_argument("--template", default=None,
                    help="an eps-generated manifest template; its header is "
                         "used instead of the built-in column list")
    args = ap.parse_args()

    rows = read_csv(args.queue)

    live = []
    dropped_excluded = 0
    for i, r in enumerate(rows, start=2):
        if (r.get("is_primary") or "").strip().lower() not in ("yes", "true", "1"):
            dropped_excluded += 1
        elif (r.get("exclusion_reason") or "").strip():
            dropped_excluded += 1
        else:
            live.append((i, r))
    print(f"queue: {len(rows)} rows, {len(live)} live, "
          f"{dropped_excluded} already excluded by the harvest")

    if args.institution:
        wanted = set(args.institution)
        seen = {r["institution"] for _, r in live}
        for w in wanted:
            if w not in seen:
                sys.exit(f"ERROR: no rows for institution {w!r}. "
                         f"Names present include: "
                         f"{sorted(seen)[:5]} ...")
        live = [p for p in live if p[1]["institution"] in wanted]
        print(f"  after --institution filter: {len(live)}")

    if args.doc_type:
        wanted = set(args.doc_type)
        live = [p for p in live if p[1]["normalised_document_type"] in wanted]
        print(f"  after --doc-type filter: {len(live)}")

    if not live:
        sys.exit("ERROR: nothing left to write. Loosen the filters.")

    chosen = pick(live, args.limit, args.sample)

    if args.plus_shortest:
        already = {id(p[1]) for p in chosen}
        rest = [p for p in live if id(p[1]) not in already]
        rest.sort(key=lambda p: int(p[1].get("word_count") or 0))
        extra = rest[:args.plus_shortest]
        if len(extra) < args.plus_shortest:
            print(f"  note: only {len(extra)} spare rows for --plus-shortest")
        chosen = chosen + extra

    chosen.sort(key=lambda p: (p[1]["institution"], p[1]["date"]))

    columns = DEFAULT_COLUMNS
    if args.template:
        with open(args.template, newline="", encoding="utf-8-sig") as fh:
            columns = next(csv.reader(fh))
        print(f"  using column order from {args.template}: {columns}")

    out_rows = []
    missing_fields = []
    for i, r in chosen:
        m = row_to_manifest(r, args.docs_root, args.country)
        for col in columns:
            m.setdefault(col, "")
        for col in ("path", "institution", "url", "title", "doc_type",
                    "date", "speaker_hint"):
            if col in columns and not m.get(col):
                missing_fields.append(f"queue row {i}: {col} is empty")
        out_rows.append({c: m.get(c, "") for c in columns})

    if missing_fields:
        print("\nWARNING - these would fail manifest validation:")
        for line in missing_fields[:20]:
            print("   " + line)
        if len(missing_fields) > 20:
            print(f"   ... and {len(missing_fields) - 20} more")

    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=columns)
        w.writeheader()
        w.writerows(out_rows)

    words = sum(int(r.get("word_count") or 0) for _, r in chosen)
    types = defaultdict(int)
    insts = defaultdict(int)
    for _, r in chosen:
        types[r["normalised_document_type"]] += 1
        insts[r["institution"]] += 1
    print(f"\nwrote {args.out}: {len(out_rows)} documents, {words:,} words")
    print("  by type: " + ", ".join(f"{k} {v}" for k, v in
                                    sorted(types.items(), key=lambda kv: -kv[1])))
    if len(insts) <= 6:
        print("  by institution: " + ", ".join(f"{k} {v}" for k, v in
                                               sorted(insts.items())))
    else:
        print(f"  across {len(insts)} institutions")


if __name__ == "__main__":
    main()
