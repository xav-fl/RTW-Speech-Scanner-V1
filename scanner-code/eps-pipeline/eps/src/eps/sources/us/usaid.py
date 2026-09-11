"""USAID -- an adapter that is expected to return nothing.

The agency was dissolved in 2025 and its functions moved to the State
Department. `officeholders_2026.csv` carries a vacant row for this slug, and the
newsroom is a 4.9KB static stub whose newest item is dated 2025-02-23.

So the expected yield for a 2026 window is ZERO, and the adapter exists to make
that zero explicit. `harvest_us.py` distinguishes three states in the screening
log -- an agency with no adapter, an agency whose listing failed, and an agency
that was read and had nothing in the window -- and only the third is a true
finding. Without this file USAID would be logged as `adapter_not_implemented`
and be indistinguishable from the 403-blocked agencies, which would misreport a
known historical fact as a collection failure.

As of 2026-09-07 the newsroom path stopped resolving altogether -- 403 to the
project and compatibility User-Agents, 302 to a browser one, while usaid.gov/
itself still answers 200. So the adapter now normally raises
`ListingIncomplete` rather than returning an empty list. Both outcomes are
correct and they are deliberately different rows in the screening log:
`listing_unreachable` says the index could not be read, `no_documents_in_window`
says it was read and held nothing. Neither is a fault to be fixed.

If the path is ever restored the adapter will pick it up without changes.
"""

from __future__ import annotations

import re
from typing import Iterable

from ..base import (DocumentRef, ListingIncomplete, RawDocument, SourceAdapter, parse_date_text,
                    slice_element)
from ..text import _clean_inline

BASE = "https://www.usaid.gov"
LISTING = BASE + "/news-information/press-releases"

_LINK = re.compile(
    r'<a\b[^>]*href="(/news-information/press-releases/[^"]+)"[^>]*>(.*?)</a>',
    re.I | re.S)
_BODY = re.compile(r'<div\b[^>]*class="[^"]*field--name-body', re.I)
_H1 = re.compile(r"<h1\b[^>]*>(.*?)</h1>", re.I | re.S)


class UsaidAdapter(SourceAdapter):
    institution_id = "us-usaid"
    agency = "U.S. Agency for International Development"
    tier = "listing"
    date_filter = "client"
    pagination = "none"
    newsroom_url = LISTING
    feed_url = ""

    label_map = {
        "Press Release": "press_release",
    }

    def list_documents(self, start_date: str, end_date: str) -> Iterable[DocumentRef]:
        try:
            html = self.fetcher.get_text(LISTING)
        except Exception as exc:  # noqa: BLE001
            raise ListingIncomplete(
                "%s: index page unreachable: %s" % (self.institution_id, exc)
            ) from exc
        seen: set[str] = set()
        for m in _LINK.finditer(html):
            url = BASE + m.group(1)
            title = _clean_inline(m.group(2))
            if url in seen or not title:
                continue
            seen.add(url)
            # The stub carries no per-row date, so anything found here is
            # undated at the index. `in_window` keeps undated documents rather
            # than dropping them, which is what makes the zero honest.
            date = parse_date_text(title)
            if not self.in_window(date, start_date, end_date):
                continue
            yield DocumentRef(
                institution_id=self.institution_id,
                url=url,
                title=title,
                date=date,
                date_source="listing" if date else "inferred",
                source_document_type="Press Release",
                listing_url=LISTING,
            )

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
        h1 = _H1.search(page)
        if h1:
            doc.title = _clean_inline(h1.group(1)) or doc.title
        return doc
