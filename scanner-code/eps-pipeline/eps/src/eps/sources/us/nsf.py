"""National Science Foundation -- the EPA pattern, second application.

Same shape as `epa.py`, for a different reason, which is what makes the pattern
worth having rather than a one-off:

    EPA  the listing is behind a human-verification step
    NSF  the listing pages over AJAX, so `?page=N` is accepted and ignored

Both leave the same situation: the index cannot be walked, individual documents
can be fetched, and the archive holds server-rendered captures of the index.
So both enumerate from archived captures and fetch every body live, which keeps
the `.txt` verbatim against the page the agency publishes today.

WHAT WAS MEASURED
-----------------
`?page=N` on nsf.gov/news returns byte-identical pages for 0, 1, 5 and 20 --
the same 12 rows spanning 2026-09-08 back to 2025-07-25. There is no pager in
the HTML at all; the view fetches over AJAX. A plain fetch can therefore never
reach item 13, however many pages it asks for.

The archive holds **192 captures** of the listing inside
2026-01-01..2026-07-31, each carrying about 11 server-rendered rows with a real
`<time>` on each. Union across captures is the only route to the window.

THE SAME CAVEAT AS EPA
----------------------
This cannot say which documents are missing. NSF's coverage figure has to be
reported alongside the corpus, not assumed complete. NSF also publishes far
less than the cabinet departments, so the absolute number is small either way.

The host is unreliable under sustained access: repeated requests return HTTP
202 challenge responses and connection resets. Pacing is therefore deliberately
slower than the default, and a failed capture is skipped rather than fatal.
"""

from __future__ import annotations

import gzip
import json
import re
import time
import urllib.parse
import urllib.request
from typing import Iterable

from ..base import (DocumentRef, ListingIncomplete, RawDocument, SourceAdapter,
                    attr, slice_element)
from ..text import _clean_inline

BASE = "https://www.nsf.gov"
LISTING = BASE + "/news"

CDX = "https://web.archive.org/cdx/search/cdx"
REPLAY = "https://web.archive.org/web/%sid_/" + LISTING
UA = "eps-research/0.1 (academic research; contact via institution)"

MAX_SNAPSHOTS = 250

#: Section pages and utility paths that sit among the article links.
_NOT_A_DOCUMENT = re.compile(
    r"/news/(?:media-toolkits|releases|media-advisories|statements|search|"
    r"news-releases|archive)/?$", re.I)

#: Anchored, not lazy. See the note in energy.py.
_LINK = re.compile(
    r'href="(?:https?://web\.archive\.org/web/\d+(?:id_)?/?)?'
    r'(?:https?://(?:www\.)?nsf\.gov)?'
    r'(/news/[a-z0-9][a-z0-9\-]{10,})"', re.I)
_ROW = re.compile(r"<(?:article|li|div)\b[^>]*>", re.I)
_TIME_TAG = re.compile(r"<time\b[^>]*>", re.I)

_BODY = re.compile(r'<div\b[^>]*class="[^"]*node__content', re.I)
_H1 = re.compile(r"<h1\b[^>]*>(.*?)</h1>", re.I | re.S)


def _archive_get(url: str, timeout: int = 120, retries: int = 4) -> str:
    """Fetch from web.archive.org, with retries.

    The CDX API returns HTTP 504 under load often enough that a single attempt
    is not a fair test of whether an agency can be enumerated. Without this a
    busy minute at the Archive is indistinguishable from an agency having no
    captures, and the run records `listing_unreachable` for a source that is
    fine.
    """
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
            raw = urllib.request.urlopen(req, timeout=timeout).read()
            if raw[:2] == b"\x1f\x8b":               # gzip magic
                raw = gzip.decompress(raw)
            return raw.decode("utf-8", "replace")
        except Exception as exc:                     # noqa: BLE001
            last = exc
            if attempt < retries - 1:
                time.sleep(3 * (attempt + 1))
    raise last if last else RuntimeError("archive fetch failed: " + url)


class NsfAdapter(SourceAdapter):
    institution_id = "us-nsf"
    agency = "National Science Foundation"
    tier = "listing"
    date_filter = "client"
    pagination = "none"
    newsroom_url = LISTING
    feed_url = ""

    label_map = {
        "News Release": "press_release",
        "Announcement": "press_release",
        "Statement": "statement",
        "Podcast": "other",
        "Media Toolkit": "other",
    }

    # -- enumeration -------------------------------------------------------

    def _snapshots(self, start_date: str, end_date: str) -> list:
        q = {
            "url": "nsf.gov/news",
            "output": "json",
            "fl": "timestamp,original",
            "filter": "statuscode:200",
            "collapse": "timestamp:8",
            "from": start_date.replace("-", ""),
            "to": end_date.replace("-", ""),
            "limit": str(MAX_SNAPSHOTS),
        }
        try:
            rows = json.loads(_archive_get(CDX + "?" + urllib.parse.urlencode(q)))
        except Exception as exc:                     # noqa: BLE001
            raise ListingIncomplete(
                "%s: archived listing index unreachable: %s"
                % (self.institution_id, exc)) from exc
        return [r[0] for r in rows[1:]
                if r[1].rstrip("/").endswith("/news")]

    def list_documents(self, start_date: str, end_date: str) -> Iterable[DocumentRef]:
        snapshots = self._snapshots(start_date, end_date)
        if not snapshots:
            raise ListingIncomplete(
                "%s: no archived captures of the listing in %s..%s"
                % (self.institution_id, start_date, end_date))
        seen: set[str] = set()
        for ts in snapshots:
            try:
                html = _archive_get(REPLAY % ts)
            except Exception:                        # noqa: BLE001
                continue                             # a flaky host, not a fault
            for ref in self._rows(html):
                if ref.url in seen:
                    continue
                seen.add(ref.url)
                if self.in_window(ref.date, start_date, end_date):
                    yield ref
            self.fetcher.rest()

    def _rows(self, html: str) -> list:
        """Pair each article link with the nearest following `<time>`.

        NSF's rows carry no single wrapping element the archive preserves
        reliably, so the link and its date are paired by position: a link takes
        the first `<time>` that appears after it and before the next link.
        Where no date is found the ref is still emitted, undated, because
        `in_window` keeps undated documents rather than dropping them.
        """
        out = []
        links = list(_LINK.finditer(html))
        for i, m in enumerate(links):
            path = m.group(1)
            if _NOT_A_DOCUMENT.search(path):
                continue
            end = links[i + 1].start() if i + 1 < len(links) else len(html)
            t = _TIME_TAG.search(html, m.end(), end)
            date = attr(t.group(0), "datetime")[:10] if t else ""
            out.append(DocumentRef(
                institution_id=self.institution_id,
                url=BASE + path,
                title="",                # the archived anchor text is unreliable
                date=date,
                date_source="listing" if date else "inferred",
                source_document_type="News Release",
                listing_url=LISTING,
            ))
        return out

    # -- fetching, from the live site --------------------------------------

    def fetch_document(self, ref: DocumentRef) -> RawDocument:
        doc = RawDocument(
            ref=ref, title=ref.title, date=ref.date, date_source=ref.date_source,
            source_document_type=ref.source_document_type, fetched_at=self.now(),
        )
        try:
            page = self.fetcher.get_text(ref.url)
        except Exception as exc:                     # noqa: BLE001
            doc.status = "fetch_failed"
            doc.error = "%s: %s" % (type(exc).__name__, exc)
            return doc

        body = slice_element(page, _BODY, "div")
        if not body.strip():
            doc.status = "no_body"
            return doc
        doc.html = body

        # The title comes from the page, not the index: the archived anchor
        # text is often truncated or wrapped.
        h1 = _H1.search(page)
        if h1:
            doc.title = _clean_inline(h1.group(1)) or doc.title

        t = _TIME_TAG.search(page)
        if t:
            stamp = attr(t.group(0), "datetime")[:10]
            if stamp:
                doc.date = stamp
                doc.date_source = "metadata"
        return doc
