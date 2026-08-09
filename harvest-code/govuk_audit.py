#!/usr/bin/env python3
"""
Coverage audit for the GOV.UK harvest.

Answers three questions for any department, without opening a browser:

  1. RECONCILIATION -- does the screening log contain exactly as many documents
     as the Search API says exist for those filters? A mismatch means the
     harvest dropped something.

  2. RESIDUAL -- what document types exist in the window that the harvest did
     NOT pull? Shows you what your DOC_TYPE_MAP is excluding, so exclusion is
     a decision rather than an accident.

  3. PERSON CROSS-CHECK -- search by the minister's own person page instead of
     by department. Catches documents filed under a different organisation
     (joint announcements, No10, cross-department launches) that a
     department-filtered search cannot see.

Standard library only.

Usage:
    python govuk_audit.py --only "Education" --start 2026-01-01 --end 2026-07-31 \
        --log ./harvest/screening_log.csv --officeholders officeholders_2026.csv

    # audit every department at once:
    python govuk_audit.py --log ./harvest/screening_log.csv \
        --officeholders officeholders_2026.csv --out audit_report.csv
"""

import argparse
import csv
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter

SEARCH_API = "https://www.gov.uk/api/search.json"
UA = "academic-research-audit/1.0 (economics policy statements project)"

# Reuse the harvest's canonical list and name normalisers so the two scripts can
# never drift apart. Both files must sit in the same folder.
try:
    from govuk_harvest import (CANONICAL_UK_DEPARTMENTS, normalise_institution,
                               OFFICEHOLDER_ALIASES, resolve_departments)
except ImportError:
    sys.exit("govuk_harvest.py must be in the same folder as this script.")

# Must match DOC_TYPE_MAP in govuk_harvest.py. If you edit one, edit both.
HARVESTED_TYPES = {
    "speech", "authored_article", "written_statement", "oral_statement",
    "government_response", "press_release", "news_story", "correspondence",
    "transcript",
}


def get_json(url, params=None, retries=4):
    if params:
        url = url + "?" + urllib.parse.urlencode(params, doseq=True)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            if attempt == retries - 1:
                sys.stderr.write("FAILED %s -- %s\n" % (url, e))
                return None
            time.sleep(2 ** attempt)
    return None


def window(start, end):
    return "from:%s,to:%s" % (start, end)


# ------------------------------------------------------------ 1 + 2: by type

def type_breakdown(slug, start, end):
    """Every document type this org published in the window, with counts.

    Uses count=0 plus an aggregate, so this is one cheap request regardless of
    how many thousands of documents the org published."""
    data = get_json(SEARCH_API, {
        "filter_organisations": slug,
        "filter_public_timestamp": window(start, end),
        "count": 0,
        "aggregate_content_store_document_type": 200,
    })
    if not data:
        return None, None
    total = data.get("total", 0)
    agg = data.get("aggregates", {}).get("content_store_document_type", {})
    counts = {}
    for opt in agg.get("options", []):
        val = opt.get("value", {})
        name = val.get("slug") or val.get("title") or "unknown"
        counts[name] = opt.get("documents", 0)
    return total, counts


# ------------------------------------------------- 3: by person, not by dept

def find_person_slug(name):
    """Resolve a minister's GOV.UK person page slug from their name."""
    cleaned = re.sub(r"\((.*?)\)", "", name)
    cleaned = re.sub(r"\b(Rt Hon|The|Sir|Dame|Lord|Baroness|Mr|Mrs|Ms|Dr)\b\.?",
                     "", cleaned).strip()
    data = get_json(SEARCH_API, {
        "filter_format": "person",
        "q": cleaned,
        "count": 5,
        "fields": ["title", "slug", "link"],
    })
    if not data:
        return None
    for r in data.get("results", []):
        if r.get("title", "").lower().strip() == cleaned.lower():
            return r.get("slug") or (r.get("link") or "").rsplit("/", 1)[-1]
    results = data.get("results", [])
    if results:
        return results[0].get("slug") or (results[0].get("link") or "").rsplit("/", 1)[-1]
    return None


def docs_by_person(person_slug, start, end):
    """Documents GOV.UK links to this person, regardless of which org filed them."""
    data = get_json(SEARCH_API, {
        "filter_people": person_slug,
        "filter_public_timestamp": window(start, end),
        "count": 200,
        "order": "-public_timestamp",
        "fields": ["title", "link", "public_timestamp",
                   "content_store_document_type", "organisations"],
    })
    if not data:
        return []
    return data.get("results", [])


# ------------------------------------------------------------------- helpers

def load_log(path):
    rows = []
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
    except FileNotFoundError:
        sys.exit("Screening log not found: %s" % path)
    return rows


def load_uk_officeholders(path):
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if (row.get("country") or "").strip() != "United Kingdom":
                continue
            rows.append({
                "institution": (row.get("institution") or "").strip(),
                "officeholder": (row.get("officeholder") or "").strip(),
                "start_date": (row.get("start_date") or "").strip(),
                "end_date": (row.get("end_date") or "").strip(),
            })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default="./harvest/screening_log.csv")
    ap.add_argument("--officeholders", default=None)
    ap.add_argument("--start", default="2026-01-01")
    ap.add_argument("--end", default="2026-07-31")
    ap.add_argument("--only", default=None,
                    help="Substring of one institution name, to audit one department")
    ap.add_argument("--out", default=None, help="Optional CSV summary path")
    args = ap.parse_args()

    log = load_log(args.log)
    officeholders = load_uk_officeholders(args.officeholders) if args.officeholders else []

    # Group the harvested rows by institution, ignoring the placeholder rows the
    # harvest writes for departments that published nothing.
    by_inst = {}
    for r in log:
        if r.get("exclusion_reason") == "no_documents_in_window":
            by_inst.setdefault(r.get("institution", ""), [])
            continue
        by_inst.setdefault(r.get("institution", ""), []).append(r)

    # Iterate over the CANONICAL list, not over what happens to be in the log.
    # A department that produced nothing must still get a row, otherwise a
    # genuine zero is indistinguishable from a department that was skipped.
    resolved, _unresolved = resolve_departments()
    slug_for = {d["canonical"]: d["slug"] for d in resolved}

    institutions = list(CANONICAL_UK_DEPARTMENTS)
    if args.only:
        institutions = [i for i in institutions if args.only.lower() in i.lower()]

    summary_rows = []

    for inst in institutions:
        rows = by_inst.get(inst, [])
        slug = (rows[0].get("govuk_slug", "") if rows else slug_for.get(inst, ""))
        if not slug:
            print("\n" + "=" * 72)
            print("%s\n  No GOV.UK slug resolved -- cannot audit." % inst)
            summary_rows.append({
                "institution": inst, "govuk_slug": "",
                "all_docs_in_window": "", "api_count_for_mapped_types": "",
                "log_count": len(rows), "reconciliation": "UNRESOLVED_SLUG",
                "speeches_linked_to_officeholder": 0,
                "docs_missed_by_org_filter": 0,
                "in_log": "yes" if inst in by_inst else "NO",
            })
            continue
        print("\n" + "=" * 72)
        print(inst)
        print("=" * 72)

        # ---- 1 + 2 -------------------------------------------------------
        total, counts = type_breakdown(slug, args.start, args.end)
        if counts is None:
            print("  Could not reach the Search API for this org.")
            continue

        harvested_expected = sum(v for k, v in counts.items() if k in HARVESTED_TYPES)
        harvested_actual = len(rows)

        print("\n  All documents published in window: %d" % total)
        print("\n  PULLED BY THE HARVEST")
        for k in sorted(counts, key=lambda x: -counts[x]):
            if k in HARVESTED_TYPES:
                got = sum(1 for r in rows if r.get("govuk_document_type") == k)
                flag = "" if got == counts[k] else "   <-- MISMATCH"
                print("    %-28s api=%-5d log=%-5d%s" % (k, counts[k], got, flag))

        print("\n  NOT PULLED (check these are deliberate exclusions)")
        residual = [(k, v) for k, v in counts.items() if k not in HARVESTED_TYPES]
        if not residual:
            print("    (nothing)")
        for k, v in sorted(residual, key=lambda x: -x[1]):
            print("    %-28s %d" % (k, v))

        status = "OK" if harvested_actual == harvested_expected else "MISMATCH"
        print("\n  RECONCILIATION: api=%d  log=%d  -> %s"
              % (harvested_expected, harvested_actual, status))

        # ---- speaker attribution breakdown --------------------------------
        match_counts = Counter(r.get("speaker_match", "") for r in rows)
        print("\n  SPEAKER ATTRIBUTION IN LOG")
        for k, v in match_counts.most_common():
            print("    %-28s %d" % (k or "(blank)", v))

        speeches_linked = sum(
            1 for r in rows
            if r.get("govuk_document_type") == "speech"
            and r.get("speaker_match") == "linked"
        )
        print("\n  Speeches linked to the eligible officeholder: %d" % speeches_linked)

        # ---- 3 -------------------------------------------------------------
        person_extra = 0
        if officeholders:
            # Only spells at THIS institution. A minister who moved department
            # mid-window (several did at the 2026-07-20 reshuffle) otherwise
            # has their entire output at the OTHER department counted here as
            # "missed", which is what inflated this column previously.
            inst_key = normalise_institution(inst)
            inst_key = OFFICEHOLDER_ALIASES.get(inst_key, inst_key)
            spells = [
                o for o in officeholders
                if OFFICEHOLDER_ALIASES.get(normalise_institution(o["institution"]),
                                            normalise_institution(o["institution"]))
                == inst_key and o["officeholder"]
            ]
            names = sorted({o["officeholder"] for o in spells})
            # Compare against every URL in the log, not just this department's.
            # Ministers who head two institutions (the DBT Secretary of State
            # also heads UKEF) otherwise have all their output at the other
            # institution reported as "missed" here, even though the harvest
            # captured it. "Missed" should mean absent from the harvest entirely.
            harvested_urls = {r.get("url", "") for r in log if r.get("url")}
            print("\n  PERSON CROSS-CHECK (documents filed under another org)")
            if not names:
                print("    No officeholder rows matched this institution name.")
            for name in names:
                pslug = find_person_slug(name)
                time.sleep(0.3)
                if not pslug:
                    print("    %-32s could not resolve person page" % name)
                    continue
                docs = docs_by_person(pslug, args.start, args.end)
                # Tenure window for this person AT THIS INSTITUTION.
                spans = [(o["start_date"] or "0000-00-00",
                          o["end_date"] or "9999-99-99")
                         for o in spells if o["officeholder"] == name]

                def _in_tenure(doc_date):
                    return any(lo <= doc_date <= hi for lo, hi in spans)

                missing = [
                    d for d in docs
                    if "https://www.gov.uk" + d.get("link", "") not in harvested_urls
                    and d.get("content_store_document_type") in HARVESTED_TYPES
                    and _in_tenure((d.get("public_timestamp") or "")[:10])
                ]
                person_extra += len(missing)
                print("    %-32s %d linked docs, %d not in harvest"
                      % (name, len(docs), len(missing)))
                for d in missing[:8]:
                    orgs = "; ".join(
                        o.get("title", "") for o in (d.get("organisations") or [])
                    )
                    print("        %s  %-14s %s"
                          % ((d.get("public_timestamp") or "")[:10],
                             d.get("content_store_document_type", ""),
                             (d.get("title", "") or "")[:60]))
                    print("            filed under: %s" % (orgs or "(none)"))
                if len(missing) > 8:
                    print("        ... and %d more" % (len(missing) - 8))
                time.sleep(0.3)

        summary_rows.append({
            "institution": inst,
            "govuk_slug": slug,
            "all_docs_in_window": total,
            "api_count_for_mapped_types": harvested_expected,
            "log_count": harvested_actual,
            "reconciliation": status,
            "speeches_linked_to_officeholder": speeches_linked,
            "docs_missed_by_org_filter": person_extra,
            "in_log": "yes" if inst in by_inst else "NO",
        })

    if args.out and summary_rows:
        with open(args.out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(summary_rows[0]))
            w.writeheader()
            w.writerows(summary_rows)
        print("\nSummary written to %s" % args.out)


if __name__ == "__main__":
    main()
