#!/usr/bin/env python3
"""US collector for the economics-relevant policy statements project.

Produces the same document records the UK harvester produces: a screening log
with one row per document inspected, and a text file per document holding the
rendered blocks with the same `> ` quote prefix the UK rewriter uses. `eps
extract` and `eps build` never learn that the US exists.

Each text file has a `<name>.blocks.json` sidecar carrying `Block.speaker` for
ingest. The speaker never goes in the .txt: that file is verbatim against the
published page, and annotating it would break the guarantee the whole dataset
rests on.

Two differences from the UK log, both forced by what US agencies publish:

  * Two columns are renamed to de-anglicise the schema -- `govuk_slug` becomes
    `source_slug`, `govuk_document_type` becomes `source_document_type`. The UK
    harvester is not touched.

  * `speaker_match` becomes `speaker_evidence`, and NOTHING is filtered on it.
    No US agency publishes an equivalent of GOV.UK's `links.speaker`, so the
    collector records what it found and leaves eligibility to be decided
    downstream, where the decision is reversible.

There is no minimum-length rule. The UK queue silently dropped documents under
roughly forty words and thirteen letters vanished with no logged reason. Here
every document is written with its `word_count`, so any threshold can be
applied later and documented.

Usage:
    python -m eps.harvest_us --start 2026-01-01 --end 2026-07-31 --out ./us-harvest
    python -m eps.harvest_us --audit --out ./us-harvest --sample 12
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import re
import sys
import time
from typing import Optional

try:                                    # run as a module, or as a script
    from .sources.base import Fetcher
    from .sources.blocks import (
        Block, detect_us_quotes, name_appears, names_match, quote_speakers,
        render,
    )
    from .sources.us import ADAPTERS
except ImportError:                     # pragma: no cover - direct execution
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from eps.sources.base import Fetcher
    from eps.sources.blocks import (
        Block, detect_us_quotes, name_appears, names_match, quote_speakers,
        render,
    )
    from eps.sources.us import ADAPTERS

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.path.normpath(
    os.path.join(HERE, "..", "..", "config", "us_agencies.csv"))


class TransportPool:
    """One fetcher per transport, chosen from the config's `transport` column.

    Nine of the 24 agencies refuse every stdlib HTTP client and need Chrome's
    TLS fingerprint (H-64). Rather than teach each adapter which pipe it wants
    -- they are written against the `Fetcher` interface and should not know --
    the harvester reads `transport` from `us_agencies.csv` and hands over the
    matching client.

    The impersonating client is built LAZILY, so a run restricted to the
    fourteen `http` agencies still works on a machine that has never installed
    `curl_cffi`. If it is missing when an agency needs it, that agency fails
    with a named error rather than the whole run refusing to start.
    """

    def __init__(self, pause: float = 0.4):
        self.pause = pause
        self._http = Fetcher(pause=pause)
        self._impersonate = None
        self._browser = None

    def for_agency(self, row: dict):
        transport = (row.get("transport") or "http").strip().lower()
        if transport == "impersonate":
            if self._impersonate is None:
                from .sources.transport import ImpersonatingFetcher
                self._impersonate = ImpersonatingFetcher(pause=self.pause)
            return self._impersonate
        if transport == "browser":
            # Energy's article body is assembled client-side and exists in no
            # other form, so a browser is the only way to read it (H-85).
            # `networkidle` rather than the default: the body arrives after the
            # initial document, and a domcontentloaded snapshot misses it.
            if self._browser is None:
                from .sources.browser import BrowserFetcher
                self._browser = BrowserFetcher(pause=self.pause, headed=False,
                                               wait_until="networkidle")
            return self._browser
        return self._http

    def close(self) -> None:
        for name in ("_impersonate", "_browser"):
            obj = getattr(self, name)
            if obj is not None:
                obj.close()
                setattr(self, name, None)

#: The 16 UK columns with the two renames, plus `date_source`.
#:
#: `date_source` is a column rather than a note because several US sites carry
#: no machine-readable date at all. A date read from prose is not the same
#: evidence as a date read from a <time> element, and a corpus that cannot tell
#: the two apart cannot report its own reliability.
LOG_COLUMNS = [
    "institution", "source_slug", "document_title", "source_document_type",
    "normalised_document_type", "date", "date_source", "url",
    "linked_speakers", "expected_officeholder", "speaker_evidence",
    "word_count", "text_file", "retrieval_date", "exclusion_reason",
    "is_primary", "duplicate_of",
]

SPEAKER_EVIDENCE = (
    "speaker_is_document",  # the whole document is the officeholder's own words
    "attributed_quote",     # a quote block carries the expected officeholder
    "name_in_body",         # named in the body, no attributed quote
    "name_in_title",        # named in the title only
    "other_speaker",        # quotes exist, all attributed to someone else
    "none",                 # no trace of the officeholder
)

#: Document types where the officeholder is the sole author, so there is
#: nothing to attribute block by block. Mirrors the UK's SPEAKER_ONLY_TYPES
#: (I-08), but deliberately narrower: the UK set also contains `statement`,
#: `op_ed` and `letter`, and a US "statement" is frequently a departmental
#: statement issued in the agency's name rather than the Secretary's. Widening
#: it is a PI decision, not a coding one.
SPEAKER_IS_DOCUMENT_TYPES = {"speech", "testimony"}

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

def load_agencies(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def parse_label_map(raw: str) -> dict:
    """`Press Releases=press_release;Readouts=press_release` -> dict."""
    out: dict = {}
    for pair in (raw or "").split(";"):
        if "=" not in pair:
            continue
        key, _, value = pair.partition("=")
        key, value = key.strip(), value.strip()
        if key and value:
            out[key] = value
    return out


def load_officeholders(path: Optional[str]) -> list[dict]:
    """Read the US rows of an officeholders CSV. Read-only; never written."""
    if not path:
        return []
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if (row.get("country") or "").strip() != "United States":
                continue
            rows.append({
                "institution_id": (row.get("institution_id") or "").strip(),
                "institution": (row.get("institution") or "").strip(),
                "officeholder": (row.get("officeholder") or "").strip(),
                "start_date": (row.get("start_date") or "").strip(),
                "end_date": (row.get("end_date") or "").strip(),
            })
    return rows


def eligible_on(officeholders: list[dict], institution_id: str,
                date_iso: str) -> list[str]:
    """Which officeholder(s) held this agency on this date.

    `end_date` is treated as inclusive, matching the UK harvest (H-14), so the
    two corpora do not disagree about handover days. With no date, every
    officeholder recorded for the agency is returned: a document that cannot be
    dated cannot be narrowed, and guessing would fabricate evidence.
    """
    out = []
    for row in officeholders:
        if row["institution_id"] != institution_id:
            continue
        name = row["officeholder"]
        if not name or name.startswith("["):
            continue                     # "[none - agency dissolved]"
        if date_iso:
            if row["start_date"] and date_iso < row["start_date"]:
                continue
            if row["end_date"] and date_iso > row["end_date"]:
                continue
        if name not in out:
            out.append(name)
    return out


# --------------------------------------------------------------------------
# Speaker evidence
# --------------------------------------------------------------------------

def speaker_evidence(blocks: list[Block], title: str, text: str,
                     expected: list[str], doc_type: str = "",
                     bylines: list[str] | None = None) -> str:
    """Record what was found. Decide nothing.

    The ladder runs on how much trace of the expected officeholder the document
    carries, strongest first:

        speaker_is_document > attributed_quote > name_in_body
                            > name_in_title > other_speaker > none

    ylines are authors the INDEX named for this document, where the source
    prints one. A byline matching the expected officeholder reaches
    speaker_is_document on the source's own authority.

    `speaker_is_document` sits at the top because it is the strongest evidence
    there is: a speech or testimony is the officeholder talking from the first
    word to the last, with nothing to attribute block by block. Without it
    those documents recorded `none` -- indistinguishable from a press release
    that never mentions them, and the exact opposite of the truth.

    `other_speaker` sits below the name values on purpose. The brief defines it
    as "quotes exist, all attributed to someone else" and `name_in_body` as
    "named in the body, no attributed quote"; both can hold at once, and a
    document that names the officeholder is more evidence than one that does
    not. Whether any of these count as eligible is a live PI question, which is
    exactly why the value is recorded rather than acted on.
    """
    if not expected:
        return "none"

    bylines = [b for b in (bylines or []) if b]

    if doc_type in SPEAKER_IS_DOCUMENT_TYPES:
        return "speaker_is_document"

    # A BYLINE naming the expected officeholder is the same claim made by the
    # source rather than by the document type, and it is decided per document
    # instead of per category.
    #
    # State is the only agency of the 24 whose index prints an author, as a
    # person: "Marco Rubio" on 19 of a 22-row sample, "Thomas 'Tommy' Pigott"
    # on 3. That distinction is exactly what the `statement` question turned
    # on -- a Press Statement over the Secretary's name IS his, one over the
    # spokesperson's is not, and the type alone cannot tell them apart (H-86).
    if any(names_match(b, e) for b in bylines for e in expected):
        return "speaker_is_document"

    speakers = quote_speakers(blocks)
    if any(names_match(s, e) for s in speakers for e in expected):
        return "attributed_quote"
    if any(_names_appear(e, text) for e in expected):
        return "name_in_body"
    if any(_names_appear(e, title) for e in expected):
        return "name_in_title"
    if speakers:
        return "other_speaker"
    return "none"


def _names_appear(name: str, haystack: str) -> bool:
    """Delegates to the shared rule. See `blocks.name_appears()`."""
    return name_appears(name, haystack)


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def text_filename(url: str, date_iso: str) -> str:
    path = re.sub(r"^https?://[^/]+", "", url).strip("/")
    slug = re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-")[:120]
    return os.path.join("documents", "%s__%s.txt" % (date_iso or "undated", slug))


def sidecar_path(relpath: str) -> str:
    """`documents/x.txt` -> `documents/x.blocks.json`."""
    return relpath[:-len(".txt")] + ".blocks.json" if relpath.endswith(".txt") \
        else relpath + ".blocks.json"


def write_document(out_root: str, relpath: str, doc, blocks: list[Block],
                   body: str) -> None:
    """The rendered blocks, and nothing else, plus a sidecar beside them.

    **No metadata header.** The earlier version wrote six header lines (H-36).
    That was wrong for two reasons and is superseded here:

      * the UK files ingest actually consumes -- `documents_v2/`, written by
        the rewriter -- carry no header either, so a header made the US corpus
        the odd one out at exactly the point they are supposed to be
        indistinguishable;
      * the sidecar is indexed against `render()` output, and a header would
        put paragraphs in the text with no block to pair them with.

    Nothing is lost. Every header field is in the sidecar and in the screening
    log, both machine-readable, and neither is inside the verbatim text.
    """
    full = os.path.join(out_root, relpath)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as fh:
        fh.write(body)

    # The sidecar carries `Block.speaker` to ingest. It never goes in the .txt:
    # that file is verbatim against the published page, anchor-phrase
    # verification (E-08) matches against it, and an annotation would be text
    # the agency never published.
    payload = {
        "url": doc.ref.url,
        "institution_id": doc.ref.institution_id,
        "title": doc.title,
        "date": doc.date,
        "date_source": doc.date_source,
        "source_document_type": doc.source_document_type,
        # Lets a consumer detect a sidecar that has drifted from its .txt
        # before it silently mis-attributes. Cheap, and the failure it catches
        # is the one that would be hardest to see.
        "text_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "blocks": [
            {"index": i, "kind": b.kind, "speaker": b.speaker, "method": b.method}
            for i, b in enumerate(blocks)
        ],
    }
    with open(os.path.join(out_root, sidecar_path(relpath)), "w",
              encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
        fh.write("\n")


# --------------------------------------------------------------------------
# Harvest
# --------------------------------------------------------------------------

def harvest(args) -> int:
    agencies = load_agencies(args.agencies)
    if args.only:
        wanted = {a.strip() for a in args.only.split(",") if a.strip()}
        agencies = [a for a in agencies if a["institution_id"] in wanted]
        missing = wanted - {a["institution_id"] for a in agencies}
        if missing:
            sys.exit("Unknown institution_id: %s" % ", ".join(sorted(missing)))

    officeholders = load_officeholders(args.officeholders)
    if args.officeholders and not officeholders:
        print("  !! no United States rows in %s -- speaker_evidence will be "
              "'none' for every document" % args.officeholders)

    os.makedirs(args.out, exist_ok=True)
    log_path = os.path.join(args.out, "screening_log.csv")
    retrieval_date = time.strftime("%Y-%m-%d")
    fetchers = TransportPool(pause=args.pause)
    unknown_labels: dict = {}
    n_docs = 0

    with open(log_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=LOG_COLUMNS)
        writer.writeheader()

        for row in agencies:
            iid = row["institution_id"]
            agency = row["agency"]
            adapter_cls = ADAPTERS.get(iid)

            # Section 5 of the RA guide: a logged zero must be distinguishable
            # from an agency nobody checked. An agency with no adapter yet is a
            # third state again, and says so.
            if adapter_cls is None:
                writer.writerow(_zero_row(agency, iid, retrieval_date,
                                          "adapter_not_implemented"))
                print("%-46s      -- no adapter" % agency[:46])
                continue

            adapter = adapter_cls(
                fetcher=fetchers.for_agency(row),
                label_map=parse_label_map(row.get("label_map", "")) or None,
            )
            try:
                refs = list(adapter.list_documents(args.start, args.end))
            except Exception as exc:                 # noqa: BLE001
                writer.writerow(_zero_row(agency, iid, retrieval_date,
                                          "listing_unreachable"))
                print("%-46s      -- listing failed: %s" % (agency[:46], exc))
                continue

            print("%-46s %4d documents" % (agency[:46], len(refs)))
            if not refs:
                writer.writerow(_zero_row(agency, iid, retrieval_date,
                                          "no_documents_in_window"))
                fh.flush()
                continue

            seen_urls: dict = {}
            for ref in refs:
                adapter.fetcher.rest()
                doc = adapter.fetch_document(ref)
                norm = adapter.normalise_type(doc.source_document_type, doc.title)

                base = {
                    "institution": agency,
                    "source_slug": iid,
                    "document_title": doc.title,
                    "source_document_type": doc.source_document_type,
                    "normalised_document_type": norm,
                    "date": doc.date,
                    "date_source": doc.date_source,
                    "url": ref.url,
                    "retrieval_date": retrieval_date,
                    "is_primary": "yes",
                    "duplicate_of": "",
                }

                # The window was applied to the INDEX date. `fetch_document`
                # often refines it from the document itself, and a refined date
                # can land outside the window -- an agency whose listing shows
                # curated or evergreen items surfaces older documents, and NSF
                # did exactly that (a 2025-12-17 release enumerated from a 2026
                # capture). Re-checking here is what keeps the corpus's date
                # range equal to the window that was asked for.
                if doc.status == "ok" and not adapter.in_window(
                        doc.date, args.start, args.end):
                    row_out = dict(base)
                    row_out.update({
                        "linked_speakers": "", "expected_officeholder": "",
                        "speaker_evidence": "", "word_count": 0,
                        "text_file": "",
                        "exclusion_reason": "outside_window_after_refetch",
                    })
                    writer.writerow(row_out)
                    fh.flush()
                    continue

                if doc.status != "ok":
                    row_out = dict(base)
                    row_out.update({
                        "linked_speakers": "", "expected_officeholder": "",
                        "speaker_evidence": "", "word_count": 0,
                        "text_file": "", "exclusion_reason": doc.status,
                    })
                    writer.writerow(row_out)
                    fh.flush()
                    continue

                blocks = detect_us_quotes(doc.html)
                body = render(blocks)
                expected = eligible_on(officeholders, iid, doc.date)
                evidence = speaker_evidence(blocks, doc.title, body, expected, norm,
                                            getattr(doc, "speaker_hints", None))

                # Treasury indexes the same item under more than one newsroom
                # category. Dedupe the same way the UK log does rather than
                # dropping the second sighting.
                dup_of = seen_urls.get(ref.url, "")
                relpath = text_filename(ref.url, doc.date)
                if not dup_of:
                    seen_urls[ref.url] = ref.url
                    write_document(args.out, relpath, doc, blocks, body)

                # `quote_speakers` reports who the BLOCKS attribute a quotation
                # to. An adapter may also learn the author from the index --
                # State is the only one of the 24 whose listing prints it, as
                # "Marco Rubio, Secretary of State" or "Tommy Pigott, Principal
                # Deputy Spokesperson". That is the Department's own assertion
                # of authorship and it is stronger evidence than anything this
                # code infers, so it belongs in the log.
                #
                # It was being collected into `RawDocument.speaker_hints` and
                # discarded here, which left `linked_speakers` empty for 260 of
                # 262 State statements -- the evidence that decides each case
                # was thrown away one step before it was needed (H-86).
                speakers = list(quote_speakers(blocks))
                for hint in getattr(doc, "speaker_hints", []) or []:
                    hint = (hint or "").strip()
                    if hint and hint not in speakers:
                        speakers.append(hint)

                row_out = dict(base)
                row_out.update({
                    "linked_speakers": "; ".join(speakers),
                    "expected_officeholder": "; ".join(expected),
                    "speaker_evidence": evidence,
                    "word_count": len(body.split()),
                    "text_file": relpath if not dup_of else "",
                    "exclusion_reason": "",
                    "is_primary": "no" if dup_of else "yes",
                    "duplicate_of": dup_of,
                })
                writer.writerow(row_out)
                fh.flush()
                n_docs += 1

            for label, count in adapter.unknown_labels.items():
                unknown_labels[(iid, label)] = count

    print("\nDone. %d documents written." % n_docs)
    print("Screening log: %s" % log_path)
    if unknown_labels:
        print("\n  !! source labels with no label_map entry (typed as 'other'):")
        for (iid, label), count in sorted(unknown_labels.items()):
            print("       %-14s %-32s %d" % (iid, label, count))
    return 0


def _zero_row(agency: str, iid: str, retrieval_date: str, reason: str) -> dict:
    row = {c: "" for c in LOG_COLUMNS}
    row.update({
        "institution": agency, "source_slug": iid, "word_count": 0,
        "retrieval_date": retrieval_date, "exclusion_reason": reason,
        "is_primary": "yes",
    })
    return row


# --------------------------------------------------------------------------
# Audit
# --------------------------------------------------------------------------
# Generalised from `audit_text_fidelity.py`, which found the welding fault once,
# against one well-behaved source. With 24 adapters this is a standing gate, run
# per agency, not a one-off rescue.

WORD = re.compile(r"[A-Za-z][A-Za-z'’-]+")


def strip_header(s: str) -> str:
    """Drop the metadata header. Those lines are the harness, not the page."""
    m = re.search(r"^-{3,}\s*$", s, re.M)
    return s[m.end():] if m else s


def words(s: str) -> list[str]:
    return [w.lower() for w in WORD.findall(s)]


def compare(old_text: str, new_text: str) -> dict:
    ow, nw = words(old_text), words(new_text)
    oset, nset = set(ow), set(nw)
    welded = []
    for e in sorted(oset - nset):
        if len(e) < 5:
            continue
        for i in range(2, len(e) - 1):
            if e[:i] in nset and e[i:] in nset:
                welded.append((e, e[:i] + " " + e[i:]))
                break
    return {"old_words": len(ow), "new_words": len(nw), "welded": welded}


def report_uniformity(by_agency: dict, out_root: str) -> list:
    """Flag agencies whose documents are suspiciously all the same length.

    THE CHEAPEST DEFECT TEST IN THE PIPELINE, and the only one that catches a
    body selector pointed at the wrong region of the page.

    A body selector that matches navigation, a sidebar or a theme block does
    not fail. It returns the same markup on every page of the site, so every
    document comes out identical, the harvest reports success for all of them,
    the screening log shows no exclusions, and the refetch audit passes --
    because extraction that is consistently wrong matches itself perfectly.

    Four failures were found this way and by nothing else:

        us-justice   713 documents, 1 distinct word count  (the DOJ nav menu)
        us-energy    102 documents, 1 distinct word count  (a sidebar promo)
        us-dhs       the first of TWO `field--name-body` divs
        us-hud       the first of SIX, five of them theme CSS

    A healthy agency has nearly as many distinct word counts as documents --
    State 414 of 810, Justice 524 of 713 after the fix, SSA 17 of 17. The
    threshold below is deliberately loose: it is looking for "all the same",
    not for a subtle skew, and a false alarm costs one look at a document.

    Returns the list of suspect institution_ids.
    """
    print("word-count variance (no network; every document, not a sample)")
    suspect = []
    for iid, rows in sorted(by_agency.items()):
        counts = []
        for r in rows:
            path = os.path.join(out_root, r["text_file"].replace("\\", os.sep))
            try:
                with open(path, encoding="utf-8") as fh:
                    counts.append(len(fh.read().split()))
            except OSError:
                continue
        if not counts:
            continue
        distinct = len(set(counts))
        # One distinct length is conclusive. Beyond that, an agency whose
        # documents take fewer than 5% as many distinct lengths as it has
        # documents is not publishing that uniformly.
        bad = distinct <= max(1, len(counts) // 20)
        flag = "   <-- SUSPECT: every document nearly the same length" if bad else ""
        if bad:
            suspect.append(iid)
        print("    %-18s %4d docs  %4d distinct lengths  median %5d%s"
              % (iid, len(counts), distinct,
                 sorted(counts)[len(counts) // 2], flag))
    if suspect:
        print("\n  !! %d agenc%s look%s like a body selector pointed at the wrong\n"
              "     element. Read one document from each before extracting: %s"
              % (len(suspect), "y" if len(suspect) == 1 else "ies",
                 "s" if len(suspect) == 1 else "",
                 ", ".join(suspect)))
    print()
    return suspect


def audit(args) -> int:
    log_path = os.path.join(args.out, "screening_log.csv")
    if not os.path.isfile(log_path):
        sys.exit("No screening log at %s. Run the harvest first." % log_path)
    with open(log_path, newline="", encoding="utf-8-sig") as fh:
        rows = [r for r in csv.DictReader(fh)
                if r.get("text_file") and not r.get("exclusion_reason")]

    by_agency: dict = {}
    for r in rows:
        by_agency.setdefault(r["source_slug"], []).append(r)

    fetchers = TransportPool(pause=args.pause)
    # The audit refetches live pages, so it needs the same per-agency transport
    # the harvest used. Without it the nine impersonate-tier agencies would all
    # report `fetch failed` and the audit would look like a corpus problem.
    agency_config = {a["institution_id"]: a
                     for a in load_agencies(args.agencies)}
    random.seed(args.seed)

    # Run the offline check FIRST. It needs no network, covers every document
    # rather than a sample, and catches the one failure the refetch audit
    # cannot -- see `report_uniformity`.
    uniform = report_uniformity(by_agency, args.out)

    print("auditing up to %d documents per agency\n" % args.sample)
    overall_bad = overall_welded = 0

    for iid, agency_rows in sorted(by_agency.items()):
        adapter_cls = ADAPTERS.get(iid)
        if adapter_cls is None:
            continue
        adapter = adapter_cls(fetcher=fetchers.for_agency(
            agency_config.get(iid, {})))
        sample = random.sample(agency_rows, min(args.sample, len(agency_rows)))
        n_bad = n_welded = n_quotes = checked = 0
        print("%s  (%d of %d)" % (iid, len(sample), len(agency_rows)))
        for r in sample:
            path = os.path.join(args.out, r["text_file"].replace("\\", os.sep))
            if not os.path.isfile(path):
                print("    MISSING FILE  %s" % path)
                continue
            from .sources.base import DocumentRef
            ref = DocumentRef(institution_id=iid, url=r["url"],
                              title=r["document_title"], date=r["date"])
            adapter.fetcher.rest()
            doc = adapter.fetch_document(ref)
            if doc.status != "ok":
                print("    fetch failed   %s (%s)" % (r["url"], doc.status))
                continue
            blocks = detect_us_quotes(doc.html)
            fresh = render(blocks)
            old = strip_header(open(path, encoding="utf-8", errors="replace").read())
            d = compare(old, fresh)
            quotes = sum(1 for b in blocks if b.kind == "quote")
            checked += 1
            n_quotes += quotes
            if d["welded"]:
                n_bad += 1
                n_welded += len(d["welded"])
            flag = "OK " if not d["welded"] else "BAD"
            print("    %s %3d welded  %2d quote-blocks  %-14s %s"
                  % (flag, len(d["welded"]), quotes,
                     r["normalised_document_type"], r["document_title"][:40]))
            for a, b in d["welded"][:4]:
                print("          %r should be %r" % (a, b))
        print("    -> %d/%d documents show welded words, %d instances, "
              "%d quote blocks total\n" % (n_bad, checked, n_welded, n_quotes))
        overall_bad += n_bad
        overall_welded += n_welded

    failed = False
    if overall_bad:
        print("%d documents show welded words (%d instances). The frozen corpus "
              "does not match the pages it cites." % (overall_bad, overall_welded))
        failed = True
    else:
        print("No welded words found.")

    # Reported last as well as first, because the refetch output is long and a
    # warning printed before it scrolls away. This is the finding that matters
    # most: welded words are a handful of characters, a wrong body selector is
    # an entire agency.
    if uniform:
        print("UNIFORM WORD COUNTS in %s -- the body selector is probably "
              "pointed at navigation or a sidebar rather than the article."
              % ", ".join(uniform))
        failed = True

    return 1 if failed else 0


# --------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--start", default="2026-01-01")
    ap.add_argument("--end", default="2026-07-31")
    ap.add_argument("--out", default="./us-harvest")
    ap.add_argument("--agencies", default=DEFAULT_CONFIG,
                    help="config/us_agencies.csv")
    ap.add_argument("--officeholders", default=None,
                    help="CSV with United States officeholder rows (read-only)")
    ap.add_argument("--only", default=None,
                    help="comma-separated institution_id list")
    ap.add_argument("--audit", action="store_true",
                    help="refetch a sample, re-derive the text, report welded "
                         "words and quote-block counts per agency")
    ap.add_argument("--sample", type=int, default=12)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--pause", type=float, default=0.4)
    args = ap.parse_args(argv)
    return audit(args) if args.audit else harvest(args)


if __name__ == "__main__":
    raise SystemExit(main())
