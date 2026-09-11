#!/usr/bin/env python3
"""Drop manifest rows whose text is byte-identical to another row's.

WHY THIS EXISTS
---------------
Fourteen pairs of US documents carry exactly the same text under two different
URLs. Every one was verified against the live site: the agencies really did
publish the same words twice. The harvest is faithful; the corpus is not
therefore correct, because a dataset that counts statements would count each of
these twice.

The duplication has four shapes, all seen:

    same text, alias slug     EPA published one op-ed under two headlines
    same text, corrected URL  Justice reissued a release with "$160" -> "$135"
    same text, "-0" reissue   SBA's CMS emits a numbered copy on re-publication
    same text, fact sheet     State posts a release and its fact sheet as two

and one that is the agency's own mistake rather than a republication: SBA's
Minnesota release of 2026-01-26 carries the body of its Florida release of
2026-01-16, headline and all metadata Minnesota, prose entirely Florida. That
page still reads that way today. The Minnesota row is dropped for the same
reason as the rest -- there is one statement here, not two -- and the record
below is what preserves the fact that SBA published the page at all.

CHOOSING WHICH COPY TO KEEP
---------------------------
Deterministic, in this order:

  1. a typed document beats one typed `other`   (State: statement > fact sheet)
  2. the URL slug that matches the title        (Justice: "$135" over "$160")
  3. the earlier publication date               (the original, not the reissue)
  4. the shorter URL                            (drops "-0", "-1", "-fact-sheet")
  5. the URL, lexicographically                 (so reruns agree)

Rule 2 is skipped for a group where any slug is opaque, because an ID like
`press-releases/sb0394` cannot agree with a title and would otherwise lose to
a wordy re-post of itself. That is exactly the Treasury pair, and the official
press-release number is the copy worth keeping.

NOTHING IS DELETED. The documents stay on disk and stay in the screening log;
only the ingest manifest loses the row, and `duplicates.csv` records every
dropped row against the one it duplicates. Reversing this is a text edit.

    python scripts/dedupe_corpus.py manifest_us_full.csv           # report
    python scripts/dedupe_corpus.py manifest_us_full.csv --apply   # rewrite
"""

from __future__ import annotations

import collections
import csv
import hashlib
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from eps.harvest.local import MANIFEST_COLUMNS, extract_text  # noqa: E402

#: A slug is "wordy" if it carries at least this many alphabetic segments. Below
#: it, the slug is an identifier and tells us nothing about the title.
WORDY_SEGMENTS = 3

#: Short words are dropped from the title/slug comparison: "and", "the", "of"
#: are in every slug and in no way evidence of a match.
_WORD = re.compile(r"[a-z0-9]+")


def _words(text: str) -> set:
    return {w for w in _WORD.findall((text or "").lower()) if len(w) > 3}


def _slug(url: str) -> str:
    return (url or "").rstrip("/").rsplit("/", 1)[-1]


def _is_wordy(url: str) -> bool:
    parts = [p for p in _slug(url).split("-") if p.isalpha()]
    return len(parts) >= WORDY_SEGMENTS


def _agreement(row: dict) -> float:
    """Fraction of the title's substantial words that appear in the URL slug."""
    title = _words(row.get("title", ""))
    if not title:
        return 0.0
    return len(title & _words(_slug(row.get("url", "")))) / len(title)


def rank_key(row: dict, use_agreement: bool):
    doc_type = (row.get("doc_type") or "").strip()
    return (
        1 if doc_type in ("", "other") else 0,
        -_agreement(row) if use_agreement else 0.0,
        (row.get("date") or "").strip(),
        len(row.get("url") or ""),
        (row.get("url") or ""),
    )


def digest(row: dict) -> str:
    text = extract_text(_path(row)).strip()
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def _path(row: dict):
    from pathlib import Path
    return Path(row["path"].strip())


def dedupe(manifest: str, apply: bool = False) -> int:
    with open(manifest, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))

    groups = collections.defaultdict(list)
    for row in rows:
        try:
            groups[digest(row)].append(row)
        except Exception as exc:                      # noqa: BLE001
            sys.exit("cannot read %s: %s" % (row.get("path"), exc))

    dupes = [g for g in groups.values() if len(g) > 1]
    print("  manifest rows        : %d" % len(rows))
    print("  distinct texts       : %d" % len(groups))
    print("  texts with >1 copy   : %d" % len(dupes))

    dropped: list[tuple[dict, dict]] = []
    for group in dupes:
        use_agreement = all(_is_wordy(r.get("url", "")) for r in group)
        ordered = sorted(group, key=lambda r: rank_key(r, use_agreement))
        keep, rest = ordered[0], ordered[1:]
        print("\n  keep : %s | %s" % ((keep.get("date") or "")[:10], keep["url"][-92:]))
        for row in rest:
            print("  drop : %s | %s" % ((row.get("date") or "")[:10], row["url"][-92:]))
            dropped.append((row, keep))

    if not dropped:
        print("\n  no duplicate texts.")
        return 0
    print("\n  rows to drop: %d" % len(dropped))

    record = os.path.join(os.path.dirname(os.path.abspath(manifest)), "duplicates.csv")
    if not apply:
        print("  (report only; pass --apply to rewrite the manifest)")
        return 0

    with open(record, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["dropped_url", "dropped_date", "dropped_title",
                    "duplicate_of_url", "institution", "dropped_path"])
        for row, keep in dropped:
            w.writerow([row.get("url", ""), row.get("date", ""), row.get("title", ""),
                        keep.get("url", ""), row.get("institution", ""),
                        row.get("path", "")])
    print("  recorded %d in %s" % (len(dropped), record))

    shutil.copyfile(manifest, manifest + ".bak")
    gone = {id(r) for r, _ in dropped}
    kept = [r for r in rows if id(r) not in gone]
    with open(manifest, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=MANIFEST_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(kept)
    print("  manifest rewritten: %d rows (was %d); original at %s.bak"
          % (len(kept), len(rows), os.path.basename(manifest)))
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        sys.exit("usage: dedupe_corpus.py <manifest.csv> [--apply]")
    raise SystemExit(dedupe(args[0], "--apply" in sys.argv))
