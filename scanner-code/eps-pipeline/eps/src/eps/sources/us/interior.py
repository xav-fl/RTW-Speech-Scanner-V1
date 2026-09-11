"""Department of the Interior -- a Drupal view with a server-side year facet.

Two things make this cheaper than Education's client-side walk:

  * `?published_at=2026` is an exposed filter, so a seven-month window costs one
    year rather than a descent through every page until the dates run out.
  * `?page=0..N` then walks that year, 30 rows to a page.

Two things make it more awkward:

  * The listing is `/news` but the documents are `/pressreleases/<slug>`.
    `/pressreleases` as an index returns 404, which is why the survey first
    recorded Interior as having no listing at all.
  * Row dates are `MM/DD/YYYY` in a `<div class="publication-info--date">`.
    Not ISO, not a `<time>` element. A first pass over this page using the
    usual ISO and month-name patterns reported Interior as carrying no dates
    whatsoever, which is the sort of quiet wrong answer `parse_date_text()`
    now exists to prevent.

Scope caveat, recorded rather than solved: this listing carries bureau output
(Fish and Wildlife, BLM, Reclamation) alongside departmental releases, and the
index gives no field to separate them. Everything is collected and the
separation is left downstream, where it is reversible, consistent with H-34.
"""

from __future__ import annotations

import re
from typing import Iterable, Iterator

from ..base import (DocumentRef, ListingIncomplete, RawDocument, SourceAdapter, parse_date_text,
                    slice_element)
from ..text import _clean_inline

BASE = "https://www.doi.gov"

MAX_PAGES = 60

_CARD = re.compile(
    r'<article\b[^>]*class="[^"]*node--type-press-release[^"]*"', re.I)
_LINK = re.compile(
    r'<h3\b[^>]*>\s*<a\b[^>]*href="(/pressreleases/[^"]+)"[^>]*>(.*?)</a>',
    re.I | re.S)
_DATE = re.compile(
    r'<div\b[^>]*class="[^"]*publication-info--date[^"]*"[^>]*>(.*?)</div>',
    re.I | re.S)

_BODY_ARTICLE = re.compile(
    r'<article\b[^>]*class="[^"]*node--type-press-release[^"]*"', re.I)
_H1 = re.compile(r"<h1\b[^>]*>(.*?)</h1>", re.I | re.S)


class InteriorAdapter(SourceAdapter):
    institution_id = "us-interior"
    agency = "Department of the Interior"
    tier = "listing"
    date_filter = "server"
    pagination = "page_param"
    newsroom_url = BASE + "/news"
    feed_url = ""

    label_map = {
        "Press Release": "press_release",
    }

    # -- listing -----------------------------------------------------------

    def list_documents(self, start_date: str, end_date: str) -> Iterable[DocumentRef]:
        seen: set[str] = set()
        for year in range(int(start_date[:4]), int(end_date[:4]) + 1):
            for ref in self._year_refs(year, start_date, end_date):
                if ref.url in seen:
                    continue
                seen.add(ref.url)
                yield ref

    def _year_refs(self, year: int, start_date: str,
                   end_date: str) -> Iterator[DocumentRef]:
        for page in range(MAX_PAGES):
            try:
                html = self.fetcher.get_text(
                    BASE + "/news", {"published_at": year, "page": page})
            except Exception as exc:  # noqa: BLE001
                raise ListingIncomplete(
                    "%s: index page unreachable: %s" % (self.institution_id, exc)
                ) from exc
            rows = self._rows(html)
            if not rows:
                return
            for ref in rows:
                if self.in_window(ref.date, start_date, end_date):
                    yield ref
            self.fetcher.rest()

    def _rows(self, html: str) -> list[DocumentRef]:
        out: list[DocumentRef] = []
        starts = [m.start() for m in _CARD.finditer(html)]
        for i, start in enumerate(starts):
            end = starts[i + 1] if i + 1 < len(starts) else len(html)
            row = html[start:end]
            link = _LINK.search(row)
            if not link:
                continue
            d = _DATE.search(row)
            date = parse_date_text(_clean_inline(d.group(1))) if d else ""
            out.append(DocumentRef(
                institution_id=self.institution_id,
                url=BASE + link.group(1),
                title=_clean_inline(link.group(2)),
                date=date,
                date_source="listing" if date else "inferred",
                source_document_type="Press Release",
                listing_url=BASE + "/news",
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

        body = slice_element(page, _BODY_ARTICLE, "article")
        if not body.strip():
            doc.status = "no_body"
            return doc
        doc.html = body

        h1 = _H1.search(page)
        if h1:
            doc.title = _clean_inline(h1.group(1)) or doc.title

        d = _DATE.search(page)
        if d:
            stamp = parse_date_text(_clean_inline(d.group(1)))
            if stamp:
                doc.date = stamp
                doc.date_source = "metadata"
        return doc
