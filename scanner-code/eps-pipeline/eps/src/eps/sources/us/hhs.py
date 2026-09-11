"""HHS -- a USWDS collection with the type printed on every row.

`?page=N` to about page 29. Each row carries a `<time datetime=...>` and a
`usa-collection__content-type` span, so both the date and the agency's own
label come from the index without fetching a body.

Two URL shapes have to be accepted: current items are `/press-room/<slug>.html`
and older ones `/about/news/YYYY/MM/DD/<slug>.html`.
"""

from __future__ import annotations

import re
from typing import Iterable

from ..base import (DocumentRef, ListingIncomplete, RawDocument, SourceAdapter,
                    attr, slice_element)
from ..text import _clean_inline

BASE = "https://www.hhs.gov"
LISTING = BASE + "/press-room/index.html"
MAX_PAGES = 60

_ROW = re.compile(r'<li\b[^>]*class="[^"]*usa-collection__item', re.I)
_LINK = re.compile(
    r'<h2\b[^>]*class="[^"]*usa-collection__heading[^"]*"[^>]*>\s*'
    r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S)
_TIME = re.compile(r"<time\b[^>]*>", re.I)
_TYPE = re.compile(
    r'<span\b[^>]*class="[^"]*usa-collection__content-type[^"]*"[^>]*>(.*?)</span>',
    re.I | re.S)
_URL_DATE = re.compile(r"/(20\d\d)/(\d{2})/(\d{2})/")

#: HHS names the article body `field--name-field-paragraph-body`, which is
#: neither Drupal's usual `field--name-body` nor `usa-prose`. Both of those DO
#: appear on the page -- on the site banner and the media-contact sidebar -- so
#: the obvious selectors return chrome. Verified against fetched prose (H-66).
_BODY = re.compile(
    r'<div\b[^>]*class="[^"]*field--name-field-paragraph-body', re.I)
#: The body follows the headline, so the search starts there.
_MAIN = re.compile(r"<h1\b", re.I)
_H1 = re.compile(r"<h1\b[^>]*>(.*?)</h1>", re.I | re.S)


class HhsAdapter(SourceAdapter):
    institution_id = "us-hhs"
    agency = "Department of Health and Human Services"
    tier = "listing"
    date_filter = "client"
    pagination = "page_param"
    newsroom_url = LISTING
    feed_url = ""

    label_map = {
        "Press Release": "press_release",
        "Statement": "statement",
        "Testimony": "testimony",
        "Speech": "speech",
        "Fact Sheet": "other",
        "Blog": "other",
    }

    def list_documents(self, start_date: str, end_date: str) -> Iterable[DocumentRef]:
        seen: set[str] = set()
        for page in range(MAX_PAGES):
            try:
                html = self.fetcher.get_text(LISTING, {"page": page})
            except Exception as exc:        # noqa: BLE001
                raise ListingIncomplete(
                    "%s: index page unreachable: %s"
                    % (self.institution_id, exc)) from exc
            rows = self._rows(html)
            if not rows:
                return
            for ref in rows:
                if ref.url in seen:
                    continue
                seen.add(ref.url)
                if self.in_window(ref.date, start_date, end_date):
                    yield ref
            newest = max((r.date for r in rows if r.date), default="")
            if newest and newest < start_date:
                return
            self.fetcher.rest()

    def _rows(self, html: str) -> list:
        out = []
        starts = [m.start() for m in _ROW.finditer(html)]
        for i, start in enumerate(starts):
            end = starts[i + 1] if i + 1 < len(starts) else len(html)
            row = html[start:end]
            link = _LINK.search(row)
            if not link:
                continue
            href = link.group(1)
            if not (href.startswith("/press-room/")
                    or href.startswith("/about/news/")):
                continue
            t = _TIME.search(row)
            date = attr(t.group(0), "datetime")[:10] if t else ""
            source = "listing"
            if not date:
                u = _URL_DATE.search(href)
                if u:
                    date, source = "%s-%s-%s" % u.groups(), "inferred"
            label = _TYPE.search(row)
            out.append(DocumentRef(
                institution_id=self.institution_id,
                url=BASE + href if href.startswith("/") else href,
                title=_clean_inline(link.group(2)),
                date=date,
                date_source=source if date else "inferred",
                source_document_type=_clean_inline(label.group(1)) if label else "",
                listing_url=LISTING,
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
