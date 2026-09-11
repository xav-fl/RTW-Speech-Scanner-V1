#!/usr/bin/env python3
"""Quarantine documents on disk that the screening log does not describe.

WHY THIS EXISTS
---------------
`harvest_us.py` rewrites `screening_log.csv` on every run but writes documents
into `documents/` without clearing it. That is the safe default -- a crashed run
must not destroy the previous corpus -- but it means the directory accumulates
files from earlier runs whose rows are no longer in the log.

After three full runs and one repair, 19 such files were left behind: DOL
sub-agency releases collected before the `osec` filter existed, and GSA
documents superseded by the repair pass. Nothing reads them today, because the
log is authoritative. But a consumer that walked `documents/` directly -- which
is an obvious thing to do -- would silently pick up 19 documents belonging to no
row, including agency output the project had deliberately excluded.

So the invariant this restores is simple and worth having:

    every .txt in documents/ has a row in screening_log.csv, and vice versa.

Orphans are MOVED to `documents/_orphaned/`, not deleted. They were expensive to
collect and a mistake here should be reversible.

    python scripts/reconcile_corpus.py ./us-harvest            # report only
    python scripts/reconcile_corpus.py ./us-harvest --apply    # move them
"""

from __future__ import annotations

import csv
import os
import shutil
import sys


def reconcile(corpus: str, apply: bool = False) -> int:
    log = os.path.join(corpus, "screening_log.csv")
    docs = os.path.join(corpus, "documents")
    if not os.path.isfile(log):
        sys.exit("no screening log at " + log)
    if not os.path.isdir(docs):
        sys.exit("no documents directory at " + docs)

    with open(log, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    logged = {os.path.basename(r["text_file"])
              for r in rows if r.get("text_file")}

    ondisk = {f for f in os.listdir(docs) if f.endswith(".txt")}
    orphans = sorted(ondisk - logged)
    missing = sorted(logged - ondisk)

    print("  log rows naming a file : %d" % len(logged))
    print("  .txt files on disk     : %d" % len(ondisk))
    print("  orphans (disk, no row) : %d" % len(orphans))
    print("  missing (row, no file) : %d" % len(missing))

    if missing:
        print("\n  !! rows whose document is absent -- these are a REAL fault,")
        print("     not tidy-up, and this script will not invent them:")
        for name in missing[:10]:
            print("       %s" % name)

    if not orphans:
        return 0

    print("\n  orphans:")
    for name in orphans[:20]:
        print("    %s" % name[:96])
    if len(orphans) > 20:
        print("    ... and %d more" % (len(orphans) - 20))

    if not apply:
        print("\n  (report only; pass --apply to move them to documents/_orphaned/)")
        return 0

    dest = os.path.join(docs, "_orphaned")
    os.makedirs(dest, exist_ok=True)
    moved = 0
    for name in orphans:
        for f in (name, name[:-4] + ".blocks.json"):
            src = os.path.join(docs, f)
            if os.path.isfile(src):
                shutil.move(src, os.path.join(dest, f))
                moved += 1
    print("\n  moved %d files to %s" % (moved, dest))
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        sys.exit("usage: reconcile_corpus.py <corpus-dir> [--apply]")
    raise SystemExit(reconcile(args[0], "--apply" in sys.argv))
