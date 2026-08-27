"""
check_queue.py - pre-flight checks on the harvest output, before anything is
ingested or any money is spent.

Every check either passes silently or prints a numbered problem. It exits with
status 1 if anything failed, so you can tell at a glance.

Usage (from the folder holding this script):

    python check_queue.py --queue extraction_queue.csv ^
                          --docs-root . ^
                          --officeholders officeholders_2026.csv

--docs-root is the folder the `text_file` paths in the queue are relative to.
If the queue says `documents\\2026-07-29__foo.txt` and that file lives at
C:\\WISE\\harvest\\documents\\2026-07-29__foo.txt, then --docs-root is
C:\\WISE\\harvest.
"""

import argparse
import csv
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

# The 24 UK ministerial departments named in the field guide, Section 2.
GUIDE_UK_INSTITUTIONS = [
    "Attorney General's Office",
    "Cabinet Office",
    "Department for Business and Trade",
    "Department for Culture, Media and Sport",
    "Department for Education",
    "Department for Energy Security and Net Zero",
    "Department for Environment, Food and Rural Affairs",
    "Department for Science, Innovation and Technology",
    "Department for Transport",
    "Department for Work and Pensions",
    "Department of Health and Social Care",
    "Foreign, Commonwealth and Development Office",
    "HM Treasury",
    "Home Office",
    "Ministry of Defence",
    "Ministry of Housing, Communities and Local Government",
    "Ministry of Justice",
    "Northern Ireland Office",
    "Office of the Advocate General for Scotland",
    "Office of the Leader of the House of Commons",
    "Office of the Leader of the House of Lords",
    "Scotland Office",
    "UK Export Finance",
    "Wales Office",
]

VALID_DOC_TYPES = {
    "speech", "statement", "press_release", "testimony",
    "letter", "op_ed", "interview_transcript", "other",
}

WINDOW_START = date(2026, 1, 1)
WINDOW_END = date(2026, 7, 31)


def parse_date(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        y, m, d = s.split("-")
        return date(int(y), int(m), int(d))
    except Exception:
        return None


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


class Report:
    def __init__(self):
        self.problems = []
        self.notes = []

    def fail(self, heading, lines):
        self.problems.append((heading, list(lines)))

    def note(self, line):
        self.notes.append(line)

    def render(self):
        for line in self.notes:
            print(line)
        if not self.problems:
            print("\nAll checks passed. Nothing to fix.")
            return 0
        print(f"\n{len(self.problems)} check(s) found something:\n")
        for i, (heading, lines) in enumerate(self.problems, 1):
            print(f"[{i}] {heading}")
            for line in lines[:25]:
                print(f"      {line}")
            if len(lines) > 25:
                print(f"      ... and {len(lines) - 25} more")
            print()
        return 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", required=True)
    ap.add_argument("--docs-root", default=None,
                    help="folder the text_file paths are relative to; "
                         "omit to skip the file-existence check")
    ap.add_argument("--officeholders", default=None,
                    help="officeholders_2026.csv; omit to skip the "
                         "speaker-attribution check")
    ap.add_argument("--end-date-exclusive", action="store_true", default=True)
    args = ap.parse_args()

    rep = Report()
    rows = read_csv(args.queue)
    rep.note(f"Queue: {len(rows)} rows from {args.queue}")

    # ---- 0. queue rows we should not be extracting -----------------------
    live, skipped = [], []
    for i, r in enumerate(rows, start=2):
        if (r.get("is_primary") or "").strip().lower() not in ("yes", "true", "1"):
            skipped.append((i, r, "is_primary is not yes"))
        elif (r.get("exclusion_reason") or "").strip():
            skipped.append((i, r, r["exclusion_reason"]))
        else:
            live.append((i, r))
    rep.note(f"Live rows (primary, not excluded): {len(live)}")
    if skipped:
        rep.note(f"Rows the queue itself excludes: {len(skipped)} (correctly ignored)")

    words = sum(int(r.get("word_count") or 0) for _, r in live)
    rep.note(f"Total words queued: {words:,}")

    # ---- 1. document type ------------------------------------------------
    bad_types = [f"row {i}: {r['normalised_document_type']!r}"
                 for i, r in live
                 if r.get("normalised_document_type") not in VALID_DOC_TYPES]
    if bad_types:
        rep.fail("Document types not in the Section 4 list", bad_types)
    rep.note("Doc types: " + ", ".join(
        f"{k} {v}" for k, v in
        Counter(r["normalised_document_type"] for _, r in live).most_common()))

    # ---- 2. dates --------------------------------------------------------
    bad_dates = []
    for i, r in live:
        d = parse_date(r.get("date"))
        if d is None:
            bad_dates.append(f"row {i}: unreadable date {r.get('date')!r}")
        elif not (WINDOW_START <= d <= WINDOW_END):
            bad_dates.append(f"row {i}: {d} is outside the collection window")
    if bad_dates:
        rep.fail("Dates missing or outside 2026-01-01..2026-07-31", bad_dates)

    # ---- 3. duplicate URLs ----------------------------------------------
    by_url = defaultdict(list)
    for i, r in live:
        by_url[(r.get("url") or "").strip()].append(i)
    dupes = [f"rows {v}: {k}" for k, v in by_url.items() if len(v) > 1]
    if dupes:
        rep.fail("Same URL appears on more than one live row", dupes)

    # ---- 4. institution coverage ----------------------------------------
    present = Counter(r["institution"] for _, r in live)
    missing = [n for n in GUIDE_UK_INSTITUTIONS if n not in present]
    unexpected = [n for n in present if n not in GUIDE_UK_INSTITUTIONS]
    if missing:
        rep.fail(
            "Institutions from the field guide with zero documents "
            "(Section 5 needs a real zero, not an absence)",
            missing)
    if unexpected:
        rep.fail(
            "Institutions in the queue that are not on the field guide's list "
            "of 24 (name mismatch, or a new department)",
            [f"{n} ({present[n]} docs)" for n in unexpected])

    # ---- 5. files exist --------------------------------------------------
    if args.docs_root:
        root = Path(args.docs_root)
        missing_files, empty_files = [], []
        for i, r in live:
            rel = (r.get("text_file") or "").replace("\\", "/")
            p = root / rel
            if not p.is_file():
                missing_files.append(f"row {i}: {p}")
            elif p.stat().st_size == 0:
                empty_files.append(f"row {i}: {p}")
        if missing_files:
            rep.fail("text_file paths that do not exist on disk", missing_files)
        if empty_files:
            rep.fail("text_file paths that exist but are empty", empty_files)
        if not missing_files and not empty_files:
            rep.note(f"All {len(live)} document files found under {root}")

    # ---- 6. speaker attribution against the officeholder table ----------
    if args.officeholders:
        oh = [r for r in read_csv(args.officeholders)
              if (r.get("country") or "").strip().lower().startswith(("uk", "united k"))]
        spells = defaultdict(list)
        for r in oh:
            spells[r["institution"].strip()].append({
                "person": r["officeholder"].strip(),
                "start": parse_date(r.get("start_date")),
                "end": parse_date(r.get("end_date")),
                "eligible": (r.get("eligible_speaker") or "").strip().lower(),
            })

        # 6a. overlapping spells inside the table itself
        overlaps = []
        for inst, ss in spells.items():
            ss_sorted = sorted(ss, key=lambda s: s["start"] or date.min)
            for a, b in zip(ss_sorted, ss_sorted[1:]):
                a_end = a["end"] or date.max
                if b["start"] and b["start"] < a_end:
                    overlaps.append(
                        f"{inst}: {a['person']} ends {a['end']}, "
                        f"{b['person']} starts {b['start']}")
        if overlaps:
            rep.fail(
                "Officeholder spells overlap. Treating end_date as exclusive "
                "resolves a same-day handover; anything wider is a data error",
                overlaps)

        # 6b. every live row resolves to exactly one eligible spell
        no_match, many_match, name_mismatch, unknown_inst = [], [], [], []
        for i, r in live:
            inst = r["institution"].strip()
            d = parse_date(r.get("date"))
            if inst not in spells:
                unknown_inst.append(f"row {i}: {inst!r} is not in the officeholder table")
                continue
            if d is None:
                continue
            hits = []
            for s in spells[inst]:
                start_ok = s["start"] is None or s["start"] <= d
                end_ok = s["end"] is None or (
                    d < s["end"] if args.end_date_exclusive else d <= s["end"])
                if start_ok and end_ok:
                    hits.append(s)
            if not hits:
                no_match.append(f"row {i}: {inst} on {d} matches nobody")
            elif len(hits) > 1:
                many_match.append(
                    f"row {i}: {inst} on {d} matches "
                    + " and ".join(h["person"] for h in hits))
            else:
                s = hits[0]
                if s["person"] != (r.get("expected_officeholder") or "").strip():
                    name_mismatch.append(
                        f"row {i}: {inst} on {d} - queue says "
                        f"{r.get('expected_officeholder')!r}, table says "
                        f"{s['person']!r}")
                if s["eligible"] not in ("yes", "y", "true", "1"):
                    name_mismatch.append(
                        f"row {i}: {inst} on {d} - {s['person']} is marked "
                        f"eligible_speaker={s['eligible']!r}")
        if unknown_inst:
            rep.fail("Institutions in the queue with no officeholder rows", unknown_inst)
        if no_match:
            rep.fail("Documents whose date falls in a gap between officeholders", no_match)
        if many_match:
            rep.fail("Documents whose date matches two officeholders at once "
                     "(this is the silent mis-attribution case)", many_match)
        if name_mismatch:
            rep.fail("Queue speaker disagrees with the officeholder table", name_mismatch)
        if not any([unknown_inst, no_match, many_match, name_mismatch]):
            rep.note(f"All {len(live)} rows resolve to exactly one eligible "
                     f"officeholder, and the names agree")

    sys.exit(rep.render())


if __name__ == "__main__":
    main()
