#!/usr/bin/env python3
"""
Prepare the harvest for extraction.

Does two things:

  1. DEDUPLICATE. Joint announcements are filed under several departments, so
     the same URL appears as several rows. The guide excludes duplicate versions
     of the same statement, so one row is marked primary and the rest are marked
     as duplicates -- retained in the screening log (Section 6 requires every
     page inspected to stay on record) but excluded from extraction.

     The primary is the department whose head is actually linked as speaker. If
     several qualify, or none do, the tie is broken alphabetically so the choice
     is reproducible rather than dependent on harvest order.

  2. BUILD THE EXTRACTION QUEUE. Writes extraction_queue.csv listing only the
     documents worth sending to the extractor: primary, attributable to an
     eligible speaker, and long enough to contain a policy statement.

Nothing is deleted. The annotated screening log keeps every row.

Standard library only.

Usage:
    python prepare_extraction.py --log ./harvest-v3/screening_log.csv
    python prepare_extraction.py --log ./harvest-v3/screening_log.csv \
        --types speech,oral_statement,written_statement    # speeches only
"""

import argparse
import csv
import os
import shutil
from collections import Counter, defaultdict

# Attribution strengths, best first. "linked" means GOV.UK explicitly records
# the eligible officeholder as speaker; the rest are weaker or negative.
ATTRIBUTION_RANK = {"linked": 0, "name_in_body": 1, "linked_mismatch": 2,
                    "no_match": 3, "no_officeholder_record": 4}


def choose_primary(rows):
    """Pick which row represents a document filed under several departments."""
    return sorted(rows, key=lambda r: (
        ATTRIBUTION_RANK.get(r.get("speaker_match", ""), 9),
        r.get("institution", ""),
    ))[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default="./harvest-v3/screening_log.csv")
    ap.add_argument("--queue", default=None,
                    help="Output path (default: alongside the log)")
    ap.add_argument("--min-words", type=int, default=40,
                    help="Skip documents shorter than this")
    ap.add_argument("--types", default=None,
                    help="Comma-separated govuk_document_type filter, "
                         "e.g. speech,oral_statement")
    ap.add_argument("--include-name-in-body", action="store_true",
                    help="Also queue documents matched only by name in body text")
    args = ap.parse_args()

    with open(args.log, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames)
        rows = list(reader)

    real = [r for r in rows if r.get("exclusion_reason") != "no_documents_in_window"]

    # ---- 1. deduplicate ---------------------------------------------------
    by_url = defaultdict(list)
    for r in real:
        by_url[r.get("url", "")].append(r)

    n_dupes = 0
    for url, group in by_url.items():
        if len(group) == 1:
            group[0]["is_primary"] = "yes"
            group[0]["duplicate_of"] = ""
            continue
        primary = choose_primary(group)
        primary["is_primary"] = "yes"
        primary["duplicate_of"] = ""
        for r in group:
            if r is primary:
                continue
            r["is_primary"] = "no"
            r["duplicate_of"] = primary.get("institution", "")
            if not r.get("exclusion_reason"):
                r["exclusion_reason"] = "duplicate_of_another_institution"
            n_dupes += 1

    for r in rows:
        r.setdefault("is_primary", "")
        r.setdefault("duplicate_of", "")

    # ---- 2. build the queue ----------------------------------------------
    ok_match = {"linked"}
    if args.include_name_in_body:
        ok_match.add("name_in_body")
    type_filter = ({t.strip() for t in args.types.split(",")}
                   if args.types else None)

    queue, reasons = [], Counter()
    for r in real:
        if r.get("is_primary") != "yes":
            reasons["duplicate of another institution"] += 1
            continue
        if r.get("speaker_match") not in ok_match:
            reasons["not attributable to eligible speaker"] += 1
            continue
        if type_filter and r.get("govuk_document_type") not in type_filter:
            reasons["document type excluded"] += 1
            continue
        if int(r.get("word_count") or 0) < args.min_words:
            reasons["too short"] += 1
            continue
        queue.append(r)

    print("Screening log: %d rows (%d documents, %d zero-department markers)"
          % (len(rows), len(real), len(rows) - len(real)))
    print("Duplicate rows resolved: %d" % n_dupes)
    print("\nExcluded from the extraction queue:")
    for k, v in reasons.most_common():
        print("  %-42s %d" % (k, v))
    print("\nQUEUED FOR EXTRACTION: %d documents" % len(queue))

    if queue:
        words = sum(int(r.get("word_count") or 0) for r in queue)
        print("  total words: %s" % format(words, ","))
        print("\n  by document type:")
        for t, c in Counter(r.get("govuk_document_type") for r in queue).most_common():
            print("    %-22s %d" % (t, c))
        print("\n  by institution:")
        for t, c in Counter(r.get("institution") for r in queue).most_common():
            print("    %-52s %d" % (t[:52], c))

    # ---- write ------------------------------------------------------------
    out_fields = fields + [c for c in ("is_primary", "duplicate_of")
                           if c not in fields]

    backup = args.log + ".predupe.bak"
    if not os.path.exists(backup):
        shutil.copy2(args.log, backup)
        print("\nBackup written to %s" % backup)

    with open(args.log, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=out_fields)
        w.writeheader()
        w.writerows(rows)
    print("Annotated screening log: %s" % args.log)

    queue_path = args.queue or os.path.join(os.path.dirname(args.log),
                                            "extraction_queue.csv")
    with open(queue_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=out_fields)
        w.writeheader()
        w.writerows(queue)
    print("Extraction queue:        %s" % queue_path)


if __name__ == "__main__":
    main()
