#!/usr/bin/env python3
"""
Prepare the US harvest for extraction.

US counterpart to prepare_extraction.py (UK). Same job, different vocabulary:
the US screening log records attribution strength in `speaker_evidence` rather
than `speaker_match`, and unlike the GOV.UK harvest, expected_officeholder was
computed without checking the document date against the officeholder's spell
of office -- so a handful of documents predating an appointee's tenure are
currently tagged with that appointee's name (e.g. 2010-2024 Department of
Energy documents tagged "Chris Wright", who took office in 2025). This script
re-derives eligibility from officeholders_2026.csv, using the same inclusive
rule as the UK harvest's eligible_on() -- start_date <= date <= end_date,
blank end_date meaning still in post -- and drops anything that fails it,
regardless of what speaker_evidence says.

Does three things:

  1. DEDUPLICATE by URL, same rule as the UK script: keep the row whose
     attribution is strongest, tie-break alphabetically by institution. As of
     this writing the US log has zero duplicate URLs (unlike GOV.UK, US
     agencies don't share a publishing platform that cross-posts one release
     under several departments), so in practice this step is a no-op safety
     net rather than something expected to remove rows.

  2. CHECK DATE ELIGIBILITY against officeholders_2026.csv. expected_officeholder
     can list more than one name ("Kristi Noem; Markwayne Mullin" across a
     handover); a row is eligible if ANY of them held the post on the
     document's date. Rows that fail this are excluded even if speaker_evidence
     looks strong -- see D-01 note below.

  3. BUILD THE EXTRACTION QUEUE: primary, date-eligible, strong attribution
     (attributed_quote or speaker_is_document by default -- pass --include-weak
     to also allow name_in_body / name_in_title), long enough to contain a
     policy statement.

Nothing is deleted. The annotated screening log keeps every row, and is only
rewritten if the dedup step actually changes an is_primary/duplicate_of value.

D-01: this script does not attempt to repair the 44 rows with no
expected_officeholder at all (no roster entry matched) -- those simply can't
pass ok_match and fall out under "not attributable to eligible speaker".

Standard library only.

Usage (from the harvest-code folder):
    python prepare_extraction_us.py
    python prepare_extraction_us.py --include-weak        # also name_in_body/name_in_title
    python prepare_extraction_us.py --types speech,statement,testimony
    python prepare_extraction_us.py --skip-date-check      # not recommended, see module docstring
"""

import argparse
import csv
import os
import shutil
from collections import Counter, defaultdict

# Attribution strengths, best first -- mirrors UK's ATTRIBUTION_RANK but over
# the US vocabulary (speaker_evidence, not speaker_match).
ATTRIBUTION_RANK = {
    "attributed_quote": 0,
    "speaker_is_document": 0,
    "name_in_title": 1,
    "name_in_body": 1,
    "other_speaker": 2,
    "none": 3,
    "": 4,
}

STRONG = {"attributed_quote", "speaker_is_document"}
WEAK = {"name_in_body", "name_in_title"}


def choose_primary(rows):
    """Pick which row represents a document filed under several agencies."""
    return sorted(rows, key=lambda r: (
        ATTRIBUTION_RANK.get(r.get("speaker_evidence", ""), 9),
        r.get("institution", ""),
    ))[0]


def load_officeholder_spells(path):
    """institution -> list of (officeholder, start_date, end_date) for US rows."""
    spells = defaultdict(list)
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r.get("country") != "United States":
                continue
            spells[r["institution"].strip()].append((
                r.get("officeholder", "").strip(),
                r.get("start_date", "").strip(),
                r.get("end_date", "").strip(),
            ))
    return spells


def date_eligible(spells, institution, expected_officeholder, date_iso):
    """True if ANY name listed in expected_officeholder held `institution` on
    `date_iso`, per that officeholder's recorded spell(s). Same inclusive rule
    as govuk_harvest.py's eligible_on()."""
    if not expected_officeholder or not date_iso:
        return False
    names = {n.strip() for n in expected_officeholder.split(";") if n.strip()}
    for officeholder, start, end in spells.get(institution, []):
        if officeholder not in names:
            continue
        if start and date_iso < start:
            continue
        if end and date_iso > end:
            continue
        return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default="./us-harvest/screening_log.csv")
    ap.add_argument("--officeholders", default="./officeholders_2026.csv")
    ap.add_argument("--queue", default=None,
                    help="Output path (default: alongside the log, "
                         "extraction_queue_us.csv)")
    ap.add_argument("--min-words", type=int, default=40,
                    help="Skip documents shorter than this")
    ap.add_argument("--types", default=None,
                    help="Comma-separated normalised_document_type filter, "
                         "e.g. speech,statement,testimony")
    ap.add_argument("--include-weak", action="store_true",
                    help="Also queue documents matched only by name_in_body "
                         "or name_in_title")
    ap.add_argument("--skip-date-check", action="store_true",
                    help="Do not require the document date to fall inside the "
                         "expected officeholder's spell of office (not "
                         "recommended -- see module docstring)")
    args = ap.parse_args()

    with open(args.log, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames)
        rows = list(reader)

    spells = load_officeholder_spells(args.officeholders)

    real = [r for r in rows if not (r.get("exclusion_reason") or "").strip()]

    # ---- 1. deduplicate ----------------------------------------------------
    by_url = defaultdict(list)
    for r in real:
        by_url[r.get("url", "")].append(r)

    n_dupes = 0
    changed = False
    for url, group in by_url.items():
        if len(group) == 1:
            if group[0].get("is_primary") != "yes" or group[0].get("duplicate_of"):
                changed = True
            group[0]["is_primary"] = "yes"
            group[0]["duplicate_of"] = ""
            continue
        primary = choose_primary(group)
        if primary.get("is_primary") != "yes":
            changed = True
        primary["is_primary"] = "yes"
        primary["duplicate_of"] = ""
        for r in group:
            if r is primary:
                continue
            if r.get("is_primary") != "no":
                changed = True
            r["is_primary"] = "no"
            r["duplicate_of"] = primary.get("institution", "")
            if not r.get("exclusion_reason"):
                r["exclusion_reason"] = "duplicate_of_another_institution"
            n_dupes += 1

    for r in rows:
        r.setdefault("is_primary", "")
        r.setdefault("duplicate_of", "")

    # ---- 2. date eligibility (annotates in memory only) --------------------
    for r in real:
        r["_date_eligible"] = args.skip_date_check or date_eligible(
            spells, r.get("institution", "").strip(),
            r.get("expected_officeholder", ""), r.get("date", "").strip())

    # ---- 3. build the queue -------------------------------------------------
    ok_match = set(STRONG)
    if args.include_weak:
        ok_match |= WEAK
    type_filter = ({t.strip() for t in args.types.split(",")}
                   if args.types else None)

    queue, reasons = [], Counter()
    n_date_rejected = 0
    for r in real:
        if r.get("is_primary") != "yes":
            reasons["duplicate of another institution"] += 1
            continue
        if r.get("speaker_evidence") not in ok_match:
            reasons["not attributable to eligible speaker"] += 1
            continue
        if not r["_date_eligible"]:
            reasons["expected officeholder not in post on this date"] += 1
            n_date_rejected += 1
            continue
        if type_filter and r.get("normalised_document_type") not in type_filter:
            reasons["document type excluded"] += 1
            continue
        if int(r.get("word_count") or 0) < args.min_words:
            reasons["too short"] += 1
            continue
        queue.append(r)

    print("Screening log: %d rows (%d live, %d already excluded)"
          % (len(rows), len(real), len(rows) - len(real)))
    print("Duplicate rows resolved: %d" % n_dupes)
    if not args.skip_date_check:
        print("Rejected for date ineligibility (named officeholder not yet/no "
              "longer in post on the document date): %d" % n_date_rejected)
    print("\nExcluded from the extraction queue:")
    for k, v in reasons.most_common():
        print("  %-58s %d" % (k, v))
    print("\nQUEUED FOR EXTRACTION: %d documents" % len(queue))

    if queue:
        words = sum(int(r.get("word_count") or 0) for r in queue)
        print("  total words: %s" % format(words, ","))
        print("\n  by document type:")
        for t, c in Counter(r.get("normalised_document_type") for r in queue).most_common():
            print("    %-22s %d" % (t, c))
        print("\n  by institution:")
        for t, c in Counter(r.get("institution") for r in queue).most_common():
            print("    %-52s %d" % (t[:52], c))

    # ---- write ---------------------------------------------------------------
    out_fields = fields + [c for c in ("is_primary", "duplicate_of")
                           if c not in fields]

    if changed:
        backup = args.log + ".predupe.bak"
        if not os.path.exists(backup):
            shutil.copy2(args.log, backup)
            print("\nBackup written to %s" % backup)
        with open(args.log, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=out_fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    else:
        print("\nNo changes to is_primary/duplicate_of -- screening log left "
              "untouched (no backup written).")

    queue_path = args.queue or os.path.join(
        os.path.dirname(args.log) or ".", "extraction_queue_us.csv")
    with open(queue_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=out_fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(queue)
    print("\nQueue written to %s" % queue_path)


if __name__ == "__main__":
    main()
