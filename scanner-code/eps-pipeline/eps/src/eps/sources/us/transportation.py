"""Transportation -- the agency the survey wrongly recorded as blocked.

`/briefing-room` answers "Access Denied" INSTEAD OF 404, which read as a block
for a week. The live newsroom is `/newsroom`, with sections press-releases,
speeches and icymi plus a separate `/testimony` page; documents keep the old
`/briefing-room/<slug>` paths.

An ordinary Drupal view underneath: `?page=0..33`, a `label_format` span giving
the agency's own type, and `<time datetime=...>` on every row.
"""

from __future__ import annotations

import re
from typing import Iterable, Iterator

from ..base import (DocumentRef, ListingIncomplete, RawDocument, SourceAdapter,
                    attr, slice_element)
from ..text import _clean_inline

BASE = "https://www.transportation.gov"

SECTIONS = {
    "/newsroom/press-releases": "Press Release",
    "/newsroom/speeches": "Speech",
    "/testimony": "Testimony",
}

MAX_PAGES = 60

#: The card, not the label. `label_format` is a SPAN inside the card, so a
#: pattern looking for a div with that class matches nothing and the adapter
#: reports zero documents for a page holding ten.
_ROW = re.compile(r'<div\b[^>]*class="[^"]*card-newsroom', re.I)
_LINK = re.compile(
    r'<h[12]\b[^>]*class="[^"]*node__title[^"]*"[^>]*>\s*'
    r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S)
_TIME = re.compile(r"<time\b[^>]*>", re.I)
_LABEL = re.compile(
    r'<span\b[^>]*class="[^"]*label_format[^"]*"[^>]*>(.*?)</span>', re.I | re.S)

#: DOT puts the release in `node__content`. The page's FIRST <h1> is the site
#: logo, so anchoring on the headline finds navigation; `node__content` sits
#: inside the article element and is unambiguous.
_BODY = re.compile(r'<div\b[^>]*class="[^"]*node__content', re.I)
_MAIN = re.compile(r'<article\b[^>]*class="[^"]*node--type-article', re.I)
_H1 = re.compile(r"<h1\b[^>]*>(.*?)</h1>", re.I | re.S)


class TransportationAdapter(SourceAdapter):
    institution_id = "us-transportation"
    agency = "Department of Transportation"
    tier = "listing"
    date_filter = "client"
    pagination = "page_param"
    newsroom_url = BASE + "/newsroom/press-releases"
    feed_url = ""

    label_map = {
        "Press Release": "press_release",
        "Speech": "speech",
        "Testimony": "testimony",
        "ICYMI": "other",
    }

    def list_documents(self, start_date: str, end_date: str) -> Iterable[DocumentRef]:
        seen: set[str] = set()
        for path, label in SECTIONS.items():
            for ref in self._section(path, label, start_date, end_date):
                if ref.url in seen:
                    continue
                seen.add(ref.url)
                yield ref

    def _section(self, path: str, label: str, start_date: str,
                 end_date: str) -> Iterator[DocumentRef]:
        listing = BASE + path
        for page in range(MAX_PAGES):
            try:
                html = self.fetcher.get_text(listing, {"page": page})
            except FileNotFoundError:
                return
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

    def _rows(self, html: str, label: str, listing: str) -> list:
        out = []
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
            lab = _LABEL.search(row)
            out.append(DocumentRef(
                institution_id=self.institution_id,
                url=BASE + href if href.startswith("/") else href,
                title=_clean_inline(link.group(2)),
                date=date,
                date_source="listing" if date else "inferred",
                source_document_type=_clean_inline(lab.group(1)) if lab else label,
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
        # `node__content` opens with the headline and the printed date, so
        # slicing it whole puts the title into the corpus as a sentence of the
        # release. Same trim as GSA and OPM.
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
                doc.date, doc.date_source = stamp, "metadata"
        return doc
