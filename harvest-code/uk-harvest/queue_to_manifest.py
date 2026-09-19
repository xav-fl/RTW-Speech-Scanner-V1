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

The full UK corpus. Read the text from the re-rendered folder (H-91) and leave
out `letter`, which is a GOV.UK page describing an attachment, never the letter
itself, and is excluded by decision (H-92):

    python queue_to_manifest.py --queue screening_log.csv ^
        --rewrite-log documents_v2/rewrite_log.csv ^
        --out manifest_uk_full.csv ^
        --doc-type press_release --doc-type speech ^
        --doc-type statement --doc-type op_ed

If `eps ingest --write-template` produces different column names from the ones
assumed here, generate a template first and pass it with --template; the header
will be copied from it verbatim.
"""

import argparse
import csv
import os
import re
import sys
from collections import defaultdict

_SENTENCE = re.compile(r"[.!?][\"'’”)]?(?:\s|$)")

DEFAULT_COLUMNS = [
    "path", "institution", "country", "url", "title",
    "doc_type", "date", "delivery_status", "speaker_hint", "notes",
]

#: Types that can be wholly one person's words. A press release linked to a
#: minister is ABOUT their announcement; it is not their words, so a link never
#: makes a press release whole-document -- its quotes are found by the
#: colon-frame rule instead.
WHOLE_DOCUMENT_TYPES = {"speech", "statement", "op_ed", "letter"}
SPEAKER_IS_DOCUMENT = "speaker_is_document"


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
        # The harvester's verdict on GOV.UK's speaker link. `linked` means the
        # page names the expected officeholder as its speaker; `linked_mismatch`
        # means it names someone else. Only the first, on a whole-document type,
        # lets ingest attribute every unit to the officeholder (H-93).
        "notes": (SPEAKER_IS_DOCUMENT
                  if (r.get("speaker_match") or "").strip() == "linked"
                  and (r.get("normalised_document_type") or "").strip()
                  in WHOLE_DOCUMENT_TYPES
                  else (r.get("speaker_match") or "").strip()),
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
    ap.add_argument("--rewrite-log", default=None,
                    help="documents_v2/rewrite_log.csv: take each document's "
                         "path from the re-rendered text, not from text_file")
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

    # The queue's `text_file` names the ORIGINAL extraction, which flattened
    # GOV.UK's <blockquote> into plain paragraphs. On that text the attribution
    # rule marks nothing in any press release: 0 units across 719 measured,
    # against 2,250 on the re-rendered text (H-91). A manifest built from
    # text_file therefore looks complete and extracts nothing from two thirds of
    # the corpus. With --rewrite-log, the path comes from the rewriter's own
    # record of where it wrote each URL, and a URL it did not write is dropped
    # and named rather than silently falling back to the old file.
    rewritten = None
    if args.rewrite_log:
        log_dir = os.path.dirname(os.path.abspath(args.rewrite_log))
        rewritten = {}
        for x in read_csv(args.rewrite_log):
            if x.get("status") == "ok" and x.get("new_file"):
                name = x["new_file"].replace("\\", "/").rsplit("/", 1)[-1]
                rewritten[x["url"].strip()] = os.path.join(log_dir, name)
        not_rewritten = [r for _, r in chosen if r.get("url", "").strip() not in rewritten]
        if not_rewritten:
            print(f"  dropped, not re-rendered: {len(not_rewritten)}")
            for r in not_rewritten[:5]:
                print(f"       {r.get('url', '')[:88]}")
        chosen = [(i, r) for i, r in chosen if r.get("url", "").strip() in rewritten]

    # A document with no sentence-ending punctuation anywhere is not prose --
    # a headline, a download stub, a list of names -- and the model would be
    # paid to find nothing in it. Same rule as the US manifest (H-89).
    if rewritten is not None:
        prose = []
        for i, r in chosen:
            body = open(rewritten[r["url"].strip()], encoding="utf-8",
                        errors="replace").read()
            if _SENTENCE.search(body):
                prose.append((i, r))
            else:
                print(f"  dropped, no prose: {r.get('url', '')[:88]}")
        chosen = prose

    out_rows = []
    missing_fields = []
    for i, r in chosen:
        m = row_to_manifest(r, args.docs_root, args.country)
        if rewritten is not None:
            m["path"] = rewritten[r["url"].strip()]
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
