"""Department of Homeland Security -- a USWDS collection listing.

The cleanest of the HTTP-reachable agencies. `?page=N` was verified to advance
(page 0 newest 2026-09-05, page 1 2026-09-01, page 3 2026-08-21), rows carry a
real `<time datetime=...>`, and the document URL encodes the date as well:

    /news/2026/09/05/<slug>

`items_per_page` is an exposed filter offering 5, 10, 25 and 50. Asking for 50
cuts the number of index requests fivefold for the same result, which matters on
a seven-month window, so the listing does.

One trap, and it is the Treasury mega-menu fault (H-42) in a new costume:
`field--name-body` appears TWICE on a DHS document page. The first occurrence,
about 14KB in, is a site-wide block carrying a `<style>` payload; the article is
the second, inside `block-system-main-block`. Slicing the first match would
yield a document of stylesheet text, so the body slice is anchored to the main
block first and the field is looked for only inside it.
"""

from __future__ import annotations

import re
from typing import Iterable, Iterator

from ..base import (DocumentRef, ListingIncomplete, RawDocument,
                    SourceAdapter, attr, slice_element)
from ..text import _clean_inline

BASE = "https://www.dhs.gov"

#: Sections to union.
#:
#: ONE section, and that is a finding rather than an oversight. The newsroom's
#: own navigation offers `press-releases`, `blog` and `featured` and nothing
#: else: there is no speeches section and no testimony section, and requests for
#: either fail rather than returning an empty view. `blog` is staff commentary
#: and `featured` is a re-presentation of items already in press-releases, so
#: neither is collected.
#:
#: Testimony by the Secretary is therefore not separable at the index here. It
#: is still caught, by `base.looks_like_testimony()` running over every title
#: for every adapter, which is exactly the case that rule exists for.
SECTIONS = {
    "press-releases": "Press Releases",
}

MAX_PAGES = 80
PER_PAGE = 50

_ROW = re.compile(r'<li\b[^>]*class="[^"]*usa-collection__item', re.I)
_TIME = re.compile(r"<time\b[^>]*>", re.I)
_HEADING = re.compile(
    r'<h3\b[^>]*class="[^"]*usa-collection__heading[^"]*"[^>]*>\s*'
    r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S)

#: The main content block. The body field is looked for only inside this.
_MAIN = re.compile(r'<div\b[^>]*id="block-mainpagecontent"', re.I)
_BODY = re.compile(r'<div\b[^>]*class="[^"]*field--name-body', re.I)
_H1 = re.compile(r"<h1\b[^>]*>(.*?)</h1>", re.I | re.S)
_RELEASE_DATE = re.compile(
    r'<span\b[^>]*class="[^"]*news-release-date-value[^"]*"[^>]*>(.*?)</span>',
    re.I | re.S)
_URL_DATE = re.compile(r"/news/(20\d\d)/(\d{2})/(\d{2})/")


class DhsAdapter(SourceAdapter):
    institution_id = "us-dhs"
    agency = "Department of Homeland Security"
    tier = "listing"
    date_filter = "client"
    pagination = "page_param"
    newsroom_url = BASE + "/news-releases/press-releases"
    feed_url = ""

    label_map = {
        "Press Releases": "press_release",
        "Speeches": "speech",
        "Testimony": "testimony",
        "Blog": "other",
        "Featured": "other",
    }

    # -- listing -----------------------------------------------------------

    def list_documents(self, start_date: str, end_date: str) -> Iterable[DocumentRef]:
        seen: set[str] = set()
        for section, label in SECTIONS.items():
            for ref in self._section_refs(section, label, start_date, end_date):
                if ref.url in seen:
                    continue
                seen.add(ref.url)
                yield ref

    def _section_refs(self, section: str, label: str, start_date: str,
                      end_date: str) -> Iterator[DocumentRef]:
        listing = BASE + "/news-releases/" + section
        for page in range(MAX_PAGES):
            try:
                html = self.fetcher.get_text(
                    listing, {"page": page, "items_per_page": PER_PAGE})
            except Exception as exc:  # noqa: BLE001
                raise ListingIncomplete(
                    "%s: index page unreachable: %s" % (self.institution_id, exc)
                ) from exc
            rows = self._rows(html, label, listing)
            if not rows:
                return
            for ref in rows:
                if self.in_window(ref.date, start_date, end_date):
                    yield ref
            newest = max((r.date for r in rows if r.date), default="")
            if newest and newest < start_date:
                return
            self.fetcher.rest()

    def _rows(self, html: str, label: str, listing: str) -> list[DocumentRef]:
        out: list[DocumentRef] = []
        starts = [m.start() for m in _ROW.finditer(html)]
        for i, start in enumerate(starts):
            end = starts[i + 1] if i + 1 < len(starts) else len(html)
            row = html[start:end]
            head = _HEADING.search(row)
            if not head:
                continue
            href = head.group(1)
            if not href.startswith("/news/"):
                continue
            t = _TIME.search(row)
            date = attr(t.group(0), "datetime")[:10] if t else ""
            source = "listing"
            if not date:
                # The path carries it too, which is weaker evidence than a
                # <time> element but far better than an empty column.
                u = _URL_DATE.search(href)
                if u:
                    date = "%s-%s-%s" % u.groups()
                    source = "inferred"
            out.append(DocumentRef(
                institution_id=self.institution_id,
                url=BASE + href,
                title=_clean_inline(head.group(2)),
                date=date,
                date_source=source if date else "inferred",
                source_document_type=label,
                listing_url=listing,
            ))
        return out

    # -- fetching ----------------------------------------------------------

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

        # Anchor to the main block BEFORE looking for the body field: the first
        # `field--name-body` on the page belongs to a site-wide style block.
        main = _MAIN.search(page)
        region = page[main.start():] if main else page
        body = slice_element(region, _BODY, "div")
        if not body.strip():
            doc.status = "no_body"
            return doc
        doc.html = body

        h1 = _H1.search(page)
        if h1:
            doc.title = _clean_inline(h1.group(1)) or doc.title

        rel = _RELEASE_DATE.search(page)
        if rel:
            from ..base import parse_date_text
            stamp = parse_date_text(_clean_inline(rel.group(1)))
            if stamp:
                doc.date = stamp
                doc.date_source = "metadata"
        return doc
