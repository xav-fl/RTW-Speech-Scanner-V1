"""USDA -- a Drupal listing behind a TLS fingerprint block.

Ordinary in every respect except reachability: `?page=N`, ten rows a page,
"Showing: 1 - 10 of 349 Results", and every row carrying a real
`<time datetime=...>`. It needs `ImpersonatingFetcher` (transport: browser)
and nothing else.

Three sections are unioned. `transcripts-speeches` is the one that matters for
this project and is easy to miss: it is where the Secretary's delivered remarks
go, while `press-releases` is departmental output.
"""

from __future__ import annotations

import re
from typing import Iterable, Iterator

from ..base import (DocumentRef, ListingIncomplete, RawDocument, SourceAdapter,
                    attr, slice_element)
from ..text import _clean_inline

BASE = "https://www.usda.gov"

SECTIONS = {
    "press-releases": "Press Release",
    "agency-news-releases": "Agency News Release",
    "transcripts-speeches": "Transcripts and Speeches",
}

MAX_PAGES = 60

_ROW = re.compile(r'<div\b[^>]*class="[^"]*views-row', re.I)
_LINK = re.compile(
    r'<h2\b[^>]*>\s*<a\b[^>]*href="(/about-usda/news/[^"]+)"[^>]*>(.*?)</a>',
    re.I | re.S)
_TIME = re.compile(r"<time\b[^>]*>", re.I)
_URL_DATE = re.compile(r"/(20\d\d)/(\d{2})/(\d{2})/")

#: USDA's own class is `field--body` -- ONE dash -- not Drupal's usual
#: `field--name-body`, which on this site belongs to navigation blurbs. Slicing
#: the first `field--name-body` returns the site's "About Food" menu text, so
#: a corpus built on it would be navigation rather than press releases. Same
#: fault family as DHS and HUD (H-56), in a third spelling.
_BODY = re.compile(r'<div\b[^>]*class="[^"]*field--body', re.I)
_MAIN = re.compile(r'<div\b[^>]*class="[^"]*main-content--wrapper', re.I)
_H1 = re.compile(r"<h1\b[^>]*>(.*?)</h1>", re.I | re.S)


class AgricultureAdapter(SourceAdapter):
    institution_id = "us-agriculture"
    agency = "Department of Agriculture"
    tier = "listing"
    date_filter = "client"
    pagination = "page_param"
    newsroom_url = BASE + "/about-usda/news/press-releases"
    feed_url = ""

    label_map = {
        "Press Release": "press_release",
        "Agency News Release": "press_release",
        "Transcripts and Speeches": "speech",
        "Blog": "other",
    }

    def list_documents(self, start_date: str, end_date: str) -> Iterable[DocumentRef]:
        seen: set[str] = set()
        for section, label in SECTIONS.items():
            for ref in self._section(section, label, start_date, end_date):
                if ref.url in seen:
                    continue
                seen.add(ref.url)
                yield ref

    def _section(self, section: str, label: str, start_date: str,
                 end_date: str) -> Iterator[DocumentRef]:
        listing = BASE + "/about-usda/news/" + section
        for page in range(MAX_PAGES):
            try:
                html = self.fetcher.get_text(listing, {"page": page})
            except FileNotFoundError:
                return                      # section does not exist
            except Exception as exc:        # noqa: BLE001
                raise ListingIncomplete(
                    "%s: index page unreachable: %s"
                    % (self.institution_id, exc)) from exc
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
            link = _LINK.search(row)
            if not link:
                continue
            href = link.group(1)
            t = _TIME.search(row)
            date = attr(t.group(0), "datetime")[:10] if t else ""
            source = "listing"
            if not date:
                u = _URL_DATE.search(href)
                if u:
                    date, source = "%s-%s-%s" % u.groups(), "inferred"
            out.append(DocumentRef(
                institution_id=self.institution_id,
                url=BASE + href,
                title=_clean_inline(link.group(2)),
                date=date,
                date_source=source if date else "inferred",
                source_document_type=label,
                listing_url=listing,
            ))
        return out

    def fetch_document(self, ref: DocumentRef) -> RawDocument:
        doc = RawDocument(
            ref=ref, title=ref.title, date=ref.date, date_source=ref.date_source,
            source_document_type=ref.source_document_type, fetched_at=self.now())
        try:
            page = self.fetcher.get_text(ref.url)
        except Exception as exc:            # noqa: BLE001
            doc.status = "fetch_failed"
            doc.error = "%s: %s" % (type(exc).__name__, exc)
            return doc
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
        t = _TIME.search(page)
        if t:
            stamp = attr(t.group(0), "datetime")[:10]
            if stamp:
                doc.date, doc.date_source = stamp, "metadata"
        return doc
