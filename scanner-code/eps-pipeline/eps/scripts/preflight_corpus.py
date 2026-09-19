#!/usr/bin/env python3
"""Pre-extract defect audit. Offline, free, run it before spending money.

The extract stage costs real money and produces a dataset that gets cited. The
failure modes that matter are not crashes -- a crash is cheap and obvious. They
are the ones that produce a full, plausible, wrong dataset:

  * a body selector pointed at navigation, so every document is the same
  * boilerplate that survived extraction and reads as prose
  * duplicate documents inflating counts
  * a document long enough to be truncated inside `render_units`
  * a speaker_hint naming someone who did not hold that office on that date
  * every unit marked attributable, so the model is told the whole page is
    the officeholder speaking

Each check below exists because something in this class actually happened, or
because it would be invisible in the screening log if it did.

    python scripts/preflight_corpus.py runs/us-full/documents.pkl

Exit code 1 if anything is flagged. Nothing here calls the network or the API.
"""

from __future__ import annotations

import collections
import hashlib
import itertools
import pickle
import re
import sys

#: `render_units` truncates above this. A document past it loses its tail
#: silently, and the model is asked to select from a partial document.
RENDER_MAX_CHARS = 120_000

#: Phrases that mean navigation, chrome or a stub reached the corpus.
#:
#: A bare "cookie" and "privacy policy" were in this list and had to come out.
#: They matched eight Education releases that are entirely genuine prose, for
#: the plain reason that Education's Student Privacy Policy Office is the
#: SUBJECT of them. The wording that actually signals a consent banner is
#: narrower, and is what is matched now. A check that cries wolf on real
#: documents is worse than no check at all: nobody reads its output twice.
CHROME = re.compile(
    r"skip to main content|^\s*menu\b|official website of the united states|"
    r"here.s how you know|download\.pdf|javascript is (?:disabled|required)|"
    r"enable javascript|accept (?:all )?cookies|this (?:site|website) uses "
    r"cookies|cookie (?:policy|preferences|settings)|^\s*breadcrumb", re.I)

#: A handover day can legitimately carry both names -- the outgoing holder
#: in the morning and the incoming one in the afternoon. Ranges are allowed
#: to touch on one day; wider than that is two people holding one office.
HANDOVER_TOLERANCE_DAYS = 1

#: Mojibake signatures from double-decoded UTF-8.
MOJIBAKE = re.compile(r"â€™|â€œ|â€\x9d|Ã©|Ã¢|â€“|Â ")


def h(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8", "replace")).hexdigest()


def check(docs) -> list:
    findings = []
    by_agency = collections.defaultdict(list)
    for d in docs:
        by_agency[d.institution].append(d)

    # -- 1. exact duplicate text -----------------------------------------
    seen = collections.defaultdict(list)
    for d in docs:
        seen[h(d.text)].append(d)
    dupes = {k: v for k, v in seen.items() if len(v) > 1}
    if dupes:
        n = sum(len(v) - 1 for v in dupes.values())
        findings.append(
            ("DUPLICATE TEXT", "%d documents are exact duplicates of another "
             "(%d distinct texts). They inflate counts and would be extracted "
             "twice." % (n, len(dupes)),
             [("%s | %s" % (v[0].institution, v[0].title[:60])) for v in
              list(dupes.values())[:5]]))

    # -- 2. truncation inside render_units --------------------------------
    # Approximate the rendered length: each unit gains its id and a separator.
    long_docs = []
    for d in docs:
        approx = sum(len(u.text) + len(u.unit_id) + 3 for u in d.units)
        if approx > RENDER_MAX_CHARS:
            long_docs.append((approx, d))
    if long_docs:
        long_docs.sort(reverse=True, key=lambda x: x[0])
        findings.append(
            ("TRUNCATED AT EXTRACT", "%d documents render longer than %d chars "
             "and will be cut off mid-document by render_units()."
             % (len(long_docs), RENDER_MAX_CHARS),
             ["%d chars | %s | %s" % (n, d.institution, d.title[:50])
              for n, d in long_docs[:5]]))

    # -- 3. chrome and stubs in the body ----------------------------------
    chrome_hits = [d for d in docs if CHROME.search(d.text[:400])]
    if chrome_hits:
        per = collections.Counter(d.institution for d in chrome_hits)
        findings.append(
            ("CHROME IN BODY", "%d documents open with navigation, a cookie "
             "notice or a download stub rather than prose." % len(chrome_hits),
             ["%s x%d" % (k, v) for k, v in per.most_common(5)]))

    # -- 4. shared boilerplate opening ------------------------------------
    # A whole agency starting with the same 80 characters means a template or
    # a wrapper is being collected as content.
    for inst, ds in sorted(by_agency.items()):
        if len(ds) < 8:
            continue
        heads = collections.Counter(d.text.strip()[:80] for d in ds)
        head, n = heads.most_common(1)[0]
        if n > max(4, len(ds) * 0.5):
            findings.append(
                ("SHARED OPENING", "%s: %d of %d documents begin with the same "
                 "80 characters." % (inst, n, len(ds)), [repr(head)]))

    # -- 5. mojibake -------------------------------------------------------
    moji = [d for d in docs if MOJIBAKE.search(d.text)]
    if moji:
        per = collections.Counter(d.institution for d in moji)
        findings.append(
            ("MOJIBAKE", "%d documents contain double-decoded UTF-8 (e.g. "
             "'a€™' for an apostrophe)." % len(moji),
             ["%s x%d" % (k, v) for k, v in per.most_common(5)]))

    repl = [d for d in docs if "�" in d.text]
    if repl:
        findings.append(
            ("REPLACEMENT CHARS", "%d documents contain U+FFFD, meaning bytes "
             "were lost at decode." % len(repl),
             [d.title[:60] for d in repl[:5]]))

    # -- 6. degenerate titles ---------------------------------------------
    for inst, ds in sorted(by_agency.items()):
        if len(ds) < 5:
            continue
        titles = collections.Counter((d.title or "").strip() for d in ds)
        t, n = titles.most_common(1)[0]
        if n > max(3, len(ds) * 0.25):
            findings.append(
                ("REPEATED TITLE", "%s: %d of %d documents share the title %r "
                 "-- title-based rules downstream will misfire."
                 % (inst, n, len(ds), t[:50]), []))
        empty = sum(1 for d in ds if not (d.title or "").strip())
        if empty:
            findings.append(
                ("EMPTY TITLE", "%s: %d documents have no title." % (inst, empty), []))

    # -- 7. attribution sanity --------------------------------------------
    all_sel = [d for d in docs
               if d.units and all(u.attributable for u in d.units)
               and d.doc_type not in ("speech", "testimony")]
    if all_sel:
        per = collections.Counter(d.institution for d in all_sel)
        findings.append(
            ("EVERY UNIT ATTRIBUTABLE", "%d non-speech documents have EVERY "
             "unit marked as the officeholder's words. For a press release "
             "that is almost certainly over-attribution." % len(all_sel),
             ["%s x%d" % (k, v) for k, v in per.most_common(5)]))

    # -- 8. dates ----------------------------------------------------------
    bad_dates = [d for d in docs if not getattr(d, "pub_date", None)]
    if bad_dates:
        findings.append(("NO DATE", "%d documents have no pub_date." % len(bad_dates), []))
    dated = [d for d in docs if getattr(d, "pub_date", None)]
    if dated:
        lo = min(d.pub_date for d in dated)
        hi = max(d.pub_date for d in dated)
        print("  date range: %s .. %s" % (lo, hi))

    # -- 9. speaker hint ---------------------------------------------------
    no_speaker = [d for d in docs if not (getattr(d, "speaker_hint", "") or "").strip()]
    if no_speaker:
        per = collections.Counter(d.institution for d in no_speaker)
        findings.append(
            ("NO SPEAKER HINT", "%d documents carry no expected officeholder, "
             "so stage 1 has nobody to attribute to." % len(no_speaker),
             ["%s x%d" % (k, v) for k, v in per.most_common(5)]))
    # Several names on one agency is NORMAL: an office changes hands mid-window
    # and both holders appear, which is the join working. What is not normal is
    # two people credited with one office over the same stretch of dates. So the
    # test is overlap, not count.
    for inst, ds in sorted(by_agency.items()):
        spans = collections.defaultdict(list)
        for d in ds:
            hint = (getattr(d, "speaker_hint", "") or "").strip()
            when = getattr(d, "pub_date", None)
            if not hint or not when:
                continue
            # The handover day itself is recorded as "Outgoing; Incoming" on a
            # single row. Treating that string as a third officeholder is what
            # made the old count-based check fire on DHS and Justice, where the
            # join was correct and the transition was documented (H-43).
            for name in (n.strip() for n in hint.split(";")):
                if name:
                    spans[name].append(when)
        ranges = {n: (min(v), max(v)) for n, v in spans.items()}
        overlaps = []
        for a, b in itertools.combinations(sorted(ranges), 2):
            lo, hi = max(ranges[a][0], ranges[b][0]), min(ranges[a][1], ranges[b][1])
            days = (hi - lo).days + 1
            if days > HANDOVER_TOLERANCE_DAYS:
                overlaps.append(
                    "%s (%s..%s) and %s (%s..%s) share %d days"
                    % (a, ranges[a][0], ranges[a][1],
                       b, ranges[b][0], ranges[b][1], days))
        if overlaps:
            findings.append(
                ("OVERLAPPING SPEAKERS", "%s: two officeholders are credited "
                 "with this office over the same dates, so the officeholder "
                 "join is not date-aware here." % inst, overlaps[:4]))
        elif len(ranges) > 1:
            # Reported, not flagged: worth seeing, not worth blocking on.
            print("  handover: %s -- %s" % (inst, "; ".join(
                "%s %s..%s" % (n, r[0], r[1])
                for n, r in sorted(ranges.items(), key=lambda kv: kv[1][0]))))

    # -- 10. very short bodies --------------------------------------------
    tiny = [d for d in docs if len(d.text.split()) < 40]
    if tiny:
        per = collections.Counter(d.institution for d in tiny)
        findings.append(
            ("VERY SHORT", "%d documents are under 40 words. Some are genuine "
             "readouts; some are stubs." % len(tiny),
             ["%s x%d" % (k, v) for k, v in per.most_common(5)]))

    return findings


def main(path: str) -> int:
    docs = pickle.load(open(path, "rb"))
    print("corpus: %d documents, %d agencies\n"
          % (len(docs), len({d.institution for d in docs})))
    findings = check(docs)
    print()
    if not findings:
        print("No defects found. Safe to extract.")
        return 0
    for name, summary, examples in findings:
        print("[%s]" % name)
        print("  %s" % summary)
        for e in examples:
            print("     - %s" % e)
        print()
    print("%d issue class(es) flagged. Review before extracting." % len(findings))
    return 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: preflight_corpus.py <documents.pkl>")
    raise SystemExit(main(sys.argv[1]))
