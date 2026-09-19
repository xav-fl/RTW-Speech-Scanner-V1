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

Two further drops happen here rather than at collection, because both are only
visible once the text is on disk: a row with no date (H-84) and a row whose
text contains no sentence (H-89). Each is counted on its own line in the report
and each stays in the screening log, so nothing is lost and both are reversible.

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
import io
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from eps.normalise import (TRANSCRIPT_MIN_LABELS, TRANSCRIPT_TYPES,  # noqa: E402
                           speaker_label, transcript_labels)
from eps.sources.blocks import names_match  # noqa: E402

SPEAKER_IS_DOCUMENT = "speaker_is_document"


def document_verdict(row: dict, body: str) -> str:
    """Re-decide `speaker_is_document` for a speech, testimony or transcript.

    The collector grants it to these types BY TYPE, and measured against the
    documents that is wrong more than half the time (H-94). Decided in order:

      1. two or more distinct speaker labels -> `transcript`; ingest attributes
         it line by line, so reporters and foreign ministers stay theirs.
      2. a byline line reading "As Delivered By: <someone else>" ->
         `other_speaker`. Treasury published a speech prepared by the Secretary
         and delivered by an Under Secretary; the words were spoken by him.
      3. the officeholder named two or more times in the running prose ->
         `name_in_body`. A speech does not keep saying its own speaker's name;
         a news release about them does. The one document this catches, a
         Treasury release titled "Secretary Bessent Takes Decisive Action",
         names him 13 times; no genuine speech in the corpus names its speaker
         more than once.
      4. the title, the index byline, or a short byline line opening the body
         names the officeholder -> `speaker_is_document`.
      5. otherwise `other_speaker`: an Associate Attorney General, a Deputy
         Secretary of State, an Assistant Secretary of the Treasury.

    Every row of any other type keeps the collector's evidence unchanged.
    """
    evidence = (row.get("speaker_evidence") or "").strip()
    doc_type = (row.get("normalised_document_type") or "").strip()
    if doc_type not in TRANSCRIPT_TYPES:
        return evidence

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    if len(transcript_labels(paragraphs)) >= TRANSCRIPT_MIN_LABELS:
        return "transcript"
    if evidence != SPEAKER_IS_DOCUMENT:
        return evidence

    expected = [e.strip() for e in (row.get("expected_officeholder") or "").split(";")
                if e.strip()]
    bylines = [b.strip() for b in (row.get("linked_speakers") or "").split(";")
               if b.strip()]
    title = row.get("document_title") or ""

    def names(text: str, person: str) -> bool:
        surname = [t for t in re.split(r"[^A-Za-zÀ-ɏ'-]+", person) if t][-1:]
        return bool(surname) and bool(
            re.search(r"\b%s\b" % re.escape(surname[0]), text, re.I))

    def is_byline(p: str) -> bool:
        return len(p.split()) <= 12 and not re.search(r"[.!?]$", p)

    head = [p for p in paragraphs[:4] if is_byline(p)]
    # A speaker label is not a mention: "SECRETARY RUBIO:" opening his own
    # remarks would otherwise count against him.
    prose = [p.split(":", 1)[1] if speaker_label(p) else p
             for p in paragraphs if not is_byline(p)]

    for p in head:
        if re.search(r"deliver", p, re.I) and not any(names(p, e) for e in expected):
            return "other_speaker"
    if any(sum(len(re.findall(r"\b%s\b" % re.escape(
            [t for t in re.split(r"[^A-Za-zÀ-ɏ'-]+", e) if t][-1]), p))
            for p in prose) >= 2 for e in expected):
        return "name_in_body"
    for e in expected:
        if (names(title, e) or any(names_match(b, e) for b in bylines)
                or any(names(p, e) for p in head)):
            return SPEAKER_IS_DOCUMENT
    return "other_speaker"

#: A document with no sentence-ending punctuation ANYWHERE in it is not
#: prose. It is a headline, a download stub, or a list of tags that the
#: body selector reached instead of the article.
#:
#: Length cannot do this job. State's call readouts are 33 words and are
#: real published statements; the two stubs this catches are 10 and 12
#: words. A word threshold set high enough to catch the stubs throws away
#: eleven genuine documents. The sentence test separates them exactly:
#: across 4,486 collected documents it matches those two and nothing else.
_SENTENCE = re.compile(r"[.!?][\"'’”)]?(?:\s|$)")

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
    out, missing, undated, bodyless = [], [], [], []
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
        # A row can pass every check above and still carry no document. Two did:
        # an Energy release whose entire body was its own subheadline, and an
        # SBA testimony published only as a PDF, whose page body was a list of
        # programme tags and the word "Download.PDF". Both would have been sent
        # to the model, which would have found nothing and charged for looking.
        body = io.open(path, encoding="utf-8", errors="replace").read()
        if not _SENTENCE.search(body):
            bodyless.append("%s  (%d words)" % (r.get("url", ""), len(body.split())))
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
            "notes": document_verdict(r, body),
        })

    print("  log rows            : %d" % len(rows))
    print("  collected (no excl.): %d" % len(collected))
    print("  dropped, undated    : %d  (ingest requires a date)" % len(undated))
    for u in undated[:3]:
        print("       %s" % u[:88])
    if len(undated) > 3:
        print("       ... and %d more" % (len(undated) - 3))
    print("  dropped, no prose   : %d  (headline or download stub, no body)"
          % len(bodyless))
    for b in bodyless[:3]:
        print("       %s" % b[:88])
    if len(bodyless) > 3:
        print("       ... and %d more" % (len(bodyless) - 3))
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
