"""Office of Personnel Management -- one page, no pager.

`/news/news-releases/` carries the full release list in a single USWDS
collection, so there is nothing to page through: `pagination` is `none` and the
window is applied by reading each row's date.

Dates are text only -- no `<time>` element anywhere -- and live inside the row
description rather than in a field of their own:

    <div class="usa-collection__description">
      <strong>Date:</strong><span> August 28, 2026</span>

so the date is read from the description text with `parse_date_text()` rather
than from markup.

The sibling sections `/news/from-the-director-s-desk/` and
`/news/secrets-of-opm/` are not press releases and are not collected.
"""

from __future__ import annotations

import re
from typing import Iterable

from ..base import (DocumentRef, ListingIncomplete, RawDocument, SourceAdapter, parse_date_text,
                    slice_element)
from ..text import _clean_inline

BASE = "https://www.opm.gov"
LISTING = BASE + "/news/news-releases/"

_ROW = re.compile(r'<li\b[^>]*class="[^"]*usa-collection__item', re.I)
_HEADING = re.compile(
    r'<h3\b[^>]*class="[^"]*usa-collection__heading[^"]*"[^>]*>\s*'
    r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S)
_DESCRIPTION = re.compile(
    r'<div\b[^>]*class="[^"]*usa-collection__description[^"]*"[^>]*>(.*?)</div>',
    re.I | re.S)

_BODY = re.compile(r'<section\b[^>]*class="[^"]*body-content', re.I)
_H1 = re.compile(r"<h1\b[^>]*>(.*?)</h1>", re.I | re.S)


class OpmAdapter(SourceAdapter):
    institution_id = "us-opm"
    agency = "Office of Personnel Management"
    tier = "listing"
    date_filter = "client"
    pagination = "none"
    newsroom_url = LISTING
    feed_url = ""

    label_map = {
        "News Release": "press_release",
        "From the Director's Desk": "other",
    }

    # -- listing -----------------------------------------------------------

    def list_documents(self, start_date: str, end_date: str) -> Iterable[DocumentRef]:
        try:
            html = self.fetcher.get_text(LISTING)
        except Exception as exc:  # noqa: BLE001
            raise ListingIncomplete(
                "%s: index page unreachable: %s" % (self.institution_id, exc)
            ) from exc
        seen: set[str] = set()
        starts = [m.start() for m in _ROW.finditer(html)]
        for i, start in enumerate(starts):
            end = starts[i + 1] if i + 1 < len(starts) else len(html)
            row = html[start:end]
            head = _HEADING.search(row)
            if not head:
                continue
            href = head.group(1)
            url = href if href.startswith("http") else BASE + href
            if url in seen or "/news-releases/" not in url:
                continue
            desc = _DESCRIPTION.search(row)
            date = parse_date_text(_clean_inline(desc.group(1))) if desc else ""
            if not self.in_window(date, start_date, end_date):
                continue
            seen.add(url)
            yield DocumentRef(
                institution_id=self.institution_id,
                url=url,
                title=_clean_inline(head.group(2)),
                date=date,
                date_source="listing" if date else "inferred",
                source_document_type="News Release",
                listing_url=LISTING,
            )

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

        body = slice_element(page, _BODY, "section")
        if not body.strip():
            doc.status = "no_body"
            return doc
        # The section opens with the page heading; drop it so the headline does
        # not arrive in the corpus as a sentence of the release.
        cut = re.search(r"</h1\s*>", body, re.I)
        if cut:
            body = body[cut.end():]
        doc.html = body

        h1 = _H1.search(page)
        if h1:
            doc.title = _clean_inline(h1.group(1)) or doc.title
        return doc
