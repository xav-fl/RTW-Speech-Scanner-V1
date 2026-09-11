#!/usr/bin/env python3
"""Merge a single-agency repair run into an existing US harvest.

WHY THIS EXISTS
---------------
`harvest_us.py` opens the screening log with mode "w". That is correct for a
harvest -- the log is a record of one pass over the sources, and appending to it
would produce a file describing no particular moment. But it means a single
agency cannot be repaired without re-running all 24.

That matters because transient failures are not rare. Three consecutive full
runs each lost a different agency to `WinError 10054`, a connection reset
mid-walk: State in run 2, GSA in run 3. `ListingIncomplete` (H-55) makes those
losses loud rather than silent, which is the right behaviour, but re-running
everything to recover one agency risks losing a different one to the next blip.

So: run the failed agency alone into a scratch directory, then merge.

    python -m eps.harvest_us --only us-gsa --out /tmp/gsa-repair ...
    python scripts/merge_harvest.py /tmp/gsa-repair ./us-harvest

The merge replaces every row for the agencies present in the repair log,
copies their documents and sidecars, and leaves every other agency untouched.
It refuses to merge a repair whose rows are all exclusions, so a failed repair
cannot quietly overwrite a good result with a worse one.
"""

from __future__ import annotations

import csv
import os
import shutil
import sys


def load(path: str) -> list:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def merge(repair_dir: str, target_dir: str) -> int:
    repair_log = os.path.join(repair_dir, "screening_log.csv")
    target_log = os.path.join(target_dir, "screening_log.csv")
    for p in (repair_log, target_log):
        if not os.path.isfile(p):
            sys.exit("missing screening log: " + p)

    repair = load(repair_log)
    target = load(target_log)
    if not repair:
        sys.exit("repair log is empty")

    agencies = {r["source_slug"] for r in repair if r.get("source_slug")}
    collected = [r for r in repair if not r.get("exclusion_reason")]
    if not collected:
        sys.exit("repair run collected nothing (%s); refusing to merge over "
                 "existing rows" % ", ".join(sorted(agencies)))

    before = {a: sum(1 for r in target
                     if r["source_slug"] == a and not r["exclusion_reason"])
              for a in agencies}

    kept = [r for r in target if r.get("source_slug") not in agencies]
    merged = kept + repair
    # Keep the file readable: group by agency, then by date within it.
    merged.sort(key=lambda r: (r.get("source_slug", ""), r.get("date", "")))

    # Documents and sidecars.
    src_docs = os.path.join(repair_dir, "documents")
    dst_docs = os.path.join(target_dir, "documents")
    os.makedirs(dst_docs, exist_ok=True)
    copied = 0
    if os.path.isdir(src_docs):
        for name in os.listdir(src_docs):
            shutil.copy2(os.path.join(src_docs, name),
                         os.path.join(dst_docs, name))
            copied += 1

    with open(target_log, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(target[0].keys()))
        writer.writeheader()
        for row in merged:
            writer.writerow({k: row.get(k, "") for k in target[0].keys()})

    for a in sorted(agencies):
        after = sum(1 for r in repair
                    if r["source_slug"] == a and not r["exclusion_reason"])
        print("  %-18s %d -> %d collected" % (a, before.get(a, 0), after))
    print("  %d files copied, %d log rows total" % (copied, len(merged)))
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__.strip().splitlines()[0] +
                 "\n\nusage: merge_harvest.py <repair-dir> <target-dir>")
    raise SystemExit(merge(sys.argv[1], sys.argv[2]))
