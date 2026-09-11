#!/usr/bin/env python3
"""Build the ingest manifest from a harvest's screening log.

The screening log is the record of a COLLECTION: one row per document
inspected, including the ones excluded and why. The manifest is the input to
INGEST: one row per document to be read. They are deliberately different files,
and this script is the only place that converts between them.

    python scripts/manifest_from_log.py ./us-harvest ./us-harvest/manifest_us.csv

WHAT IS AND IS NOT CARRIED OVER
-------------------------------
Only rows with no `exclusion_reason` become manifest rows. An agency that was
unreachable, a document with no body, a slug that 404'd -- those stay in the
screening log, which is where the account of what happened belongs, and they do
not become documents the scanner is asked to read.

Column mapping, matching `manifest_us_pilot_20.csv` exactly so the full run and
the pilot are the same shape:

    path             absolute path to the .txt
    institution      the agency's display name
    country          always "US" here
    url              the published page the text is verbatim against
    title            document title
    doc_type         `normalised_document_type` (one of the eight)
    date             ISO publication date
    delivery_status  "unknown" -- spoken vs written is not knowable from a
                     press page, and guessing it would fabricate evidence
    speaker_hint     `expected_officeholder`, the officeholder eligible on
                     that date; NOT a claim that they spoke
    notes            `speaker_evidence`, so the ingest stage can see how much
                     trace of the officeholder the collector actually found

VERIFICATION
------------
Every path is checked to exist before it is written. A manifest naming a file
that is not there fails at ingest with a confusing error a long way from the
cause, so it is refused here instead, with a count.
"""

from __future__ import annotations

import csv
import os
import sys

MANIFEST_COLUMNS = [
    "path", "institution", "country", "url", "title", "doc_type", "date",
    "delivery_status", "speaker_hint", "notes",
]


def build(corpus: str, out_path: str, country: str = "US") -> int:
    log = os.path.join(corpus, "screening_log.csv")
    if not os.path.isfile(log):
        sys.exit("no screening log at " + log)

    with open(log, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))

    collected = [r for r in rows if not r.get("exclusion_reason")]
    out, missing, undated = [], [], []
    for r in collected:
        # `eps ingest` REFUSES a manifest row with no date -- it needs one to
        # decide which officeholder was eligible -- so an undated document
        # cannot enter the corpus however good its text is.
        #
        # These are dropped here rather than given a guessed date. The ten
        # Energy documents this first applied to could not be dated
        # defensibly: `datePublished` was identical across different articles
        # (a bulk-import stamp), the first `<time>` on the page is a
        # "last reviewed" value carrying the current date, and the remaining
        # candidates disagreed with the displayed date by up to four days.
        # They stay in the screening log as collected-and-undated, so the
        # evidence is preserved and the decision is reversible.
        if not (r.get("date") or "").strip():
            undated.append(r.get("url", ""))
            continue
        rel = r.get("text_file") or ""
        if not rel:
            missing.append("(row with no text_file) " + r.get("url", ""))
            continue
        path = rel if os.path.isabs(rel) else os.path.join(corpus, rel)
        path = os.path.normpath(path)
        if not os.path.isfile(path):
            missing.append(path)
            continue
        out.append({
            "path": path,
            "institution": r.get("institution", ""),
            "country": country,
            "url": r.get("url", ""),
            "title": r.get("document_title", ""),
            "doc_type": r.get("normalised_document_type", ""),
            "date": r.get("date", ""),
            "delivery_status": "unknown",
            "speaker_hint": r.get("expected_officeholder", ""),
            "notes": r.get("speaker_evidence", ""),
        })

    print("  log rows            : %d" % len(rows))
    print("  collected (no excl.): %d" % len(collected))
    print("  dropped, undated    : %d  (ingest requires a date)" % len(undated))
    for u in undated[:3]:
        print("       %s" % u[:88])
    if len(undated) > 3:
        print("       ... and %d more" % (len(undated) - 3))
    print("  manifest rows       : %d" % len(out))
    if missing:
        print("  !! %d collected rows name a file that is not on disk:"
              % len(missing))
        for m in missing[:5]:
            print("       %s" % m)
        print("     run scripts/reconcile_corpus.py before trusting this.")

    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=MANIFEST_COLUMNS,
                                lineterminator="\n")
        writer.writeheader()
        for row in out:
            writer.writerow(row)
    print("  written             : %s" % out_path)

    # A quick shape report, because a manifest that is the wrong shape is
    # cheaper to catch here than after an extraction run.
    import collections
    print("  by doc_type         : %s"
          % dict(collections.Counter(r["doc_type"] for r in out)))
    undated = sum(1 for r in out if not r["date"])
    print("  undated             : %d" % undated)
    no_speaker = sum(1 for r in out if not r["speaker_hint"])
    print("  no speaker_hint     : %d" % no_speaker)
    return 1 if missing else 0


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        sys.exit("usage: manifest_from_log.py <corpus-dir> <out.csv> [country]")
    raise SystemExit(build(sys.argv[1], sys.argv[2],
                           sys.argv[3] if len(sys.argv) == 4 else "US"))
