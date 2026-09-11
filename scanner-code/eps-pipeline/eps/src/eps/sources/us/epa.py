"""Environmental Protection Agency -- index from the archive, text from the page.

EPA is the one agency where the two halves of collection have to come from
different places, so the reasoning is set out in full.

WHAT IS BLOCKED, AND WHAT IS NOT
--------------------------------
`/newsreleases/search`, the listing, serves an interactive human-verification
page to every automated client tried: urllib, curl, the .NET stack, httpx,
Chrome TLS impersonation, headless Chromium, and -- the point that settled it --
**a headed Playwright browser with a person at the keyboard**. The widget
reports a temporary error and will not complete, because the browser is
automation-controlled. That is not something to work around: a verification
step is a request for a person, and a person could not answer it either.

Individual `/newsreleases/<slug>` pages are NOT blocked. They return 200 with
title, date and body over ordinary TLS impersonation.

So the listing is the only thing out of reach, and the listing is only needed
to learn which slugs exist.

THE SPLIT
---------
    enumeration -> archived captures of the listing
    document text -> the live page, fetched now

That keeps the guarantee the corpus rests on. Every `.txt` is verbatim against
the page EPA publishes today; nothing archival reaches the text. Only the list
of URLs is historical, and a URL is not evidence about what was said.

WHAT IT COSTS, MEASURED
-----------------------
The listing was captured on 96 separate days across 2026-01-01..2026-07-31.
Replaying all 78 distinct captures of the first page yields **423 documents on
133 publication days** -- about **86% of the window's business days**, with
22 uncovered, several of which are public holidays. Per-snapshot yield decays
from 15 new documents to 2-4, which is the saturation signature of a
nearly-closed set.

The defect is not the 14%. It is that **this route cannot say which documents
are missing**. A corpus built this way must carry that caveat explicitly:
EPA present, coverage approximately 86% of publication days, completeness
unverifiable. Recorded in H-52 and H-74.

Paging the archive would close the gap and is not available: only 3 captures of
`?page=N` exist, against 96 of page 1.
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

BASE = "https://www.epa.gov"
LISTING = BASE + "/newsreleases/search"

CDX = "https://web.archive.org/cdx/search/cdx"
REPLAY = "https://web.archive.org/web/%sid_/" + LISTING
UA = "eps-research/0.1 (academic research; contact via institution)"

#: Cap on archived captures replayed per run. 96 exist for a seven-month
#: window; the cap is a runaway guard for a longer one.
MAX_SNAPSHOTS = 200

_ROW = re.compile(r'<li\b[^>]*class="[^"]*usa-collection__item', re.I)
_HEADING = re.compile(
    r'<h3\b[^>]*class="[^"]*usa-collection__heading[^"]*"[^>]*>\s*'
    r'<a\b[^>]*href="(/newsreleases/[^"]+)"[^>]*>(.*?)</a>', re.I | re.S)
_TIME = re.compile(r"<time\b[^>]*>", re.I)

#: The release page wraps its content in `<article class="article">`, which
#: opens with the headline, the date and a "Contact Information" block before
#: any prose. Slicing the article whole would put the press-office email
#: address into the corpus as a sentence of the release, so the chrome is
#: trimmed after the contact block where there is one.
_BODY = re.compile(r'<article\b[^>]*class="[^"]*\barticle\b', re.I)
_CONTACT_END = re.compile(
    r'<div\b[^>]*class="[^"]*field__label[^"]*"[^>]*>\s*Contact Information'
    r'.*?</div>\s*</div>', re.I | re.S)
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


class EpaAdapter(SourceAdapter):
    institution_id = "us-epa"
    agency = "Environmental Protection Agency"
    tier = "listing"
    date_filter = "client"
    #: Not `page_param`: the archive holds page 1 only, so the walk is over
    #: captures rather than over pages.
    pagination = "none"
    newsroom_url = LISTING
    feed_url = ""

    label_map = {
        "News Release": "press_release",
        "Press Release": "press_release",
    }

    # -- enumeration -------------------------------------------------------

    def _snapshots(self, start_date: str, end_date: str) -> list:
        """Capture timestamps of the listing, one per day, within the window."""
        q = {
            "url": "epa.gov/newsreleases/search",
            "output": "json",
            "fl": "timestamp,original",
            "filter": "statuscode:200",
            "collapse": "timestamp:8",          # one capture per day
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
        out = []
        for row in rows[1:]:
            ts, original = row[0], row[1]
            # The CDX prefix match also returns `/search?page=N`; page 1 only.
            if original.rstrip("/").endswith("/newsreleases/search"):
                out.append(ts)
        return out

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
                # One bad capture is not a reason to lose the other 95. The
                # route is already a documented partial; a hard failure here
                # would replace a measured 86% with nothing.
                continue
            for ref in self._rows(html):
                if ref.url in seen:
                    continue
                seen.add(ref.url)
                if self.in_window(ref.date, start_date, end_date):
                    yield ref
            self.fetcher.rest()

    def _rows(self, html: str) -> list:
        out = []
        starts = [m.start() for m in _ROW.finditer(html)]
        for i, start in enumerate(starts):
            end = starts[i + 1] if i + 1 < len(starts) else len(html)
            row = html[start:end]
            head = _HEADING.search(row)
            if not head:
                continue
            href = head.group(1)
            # Archived pages carry rewritten links; keep only the real path.
            m = re.search(r"(/newsreleases/[^\"'?#]+)$", href)
            if m:
                href = m.group(1)
            t = _TIME.search(row)
            date = attr(t.group(0), "datetime")[:10] if t else ""
            out.append(DocumentRef(
                institution_id=self.institution_id,
                url=BASE + href,
                title=_clean_inline(head.group(2)),
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

        body = slice_element(page, _BODY, "article")
        if not body.strip():
            doc.status = "no_body"
            return doc
        # Trim the headline/date/contact chrome that opens the article.
        contact = _CONTACT_END.search(body)
        if contact:
            body = body[contact.end():]
        else:
            cut = re.search(r"</h1\s*>", body, re.I)
            if cut:
                body = body[cut.end():]
        doc.html = body

        h1 = _H1.search(page)
        if h1:
            doc.title = _clean_inline(h1.group(1)) or doc.title

        t = _TIME.search(page)
        if t:
            stamp = attr(t.group(0), "datetime")[:10]
            if stamp:
                doc.date = stamp
                doc.date_source = "metadata"
        return doc
