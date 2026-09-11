"""Housing and Urban Development -- a flowing index, not a card list.

`/press` redirects to `/news`, which is one page of prose rather than a view.
Items sit under two `<h2>` section headings, `Testimony` and `Press Releases`,
each broken into `<h3>` months, with one `<p>` per item:

    <p>Thursday, September 3, 2026<br><a href="/news/hud-no-26-065">Title</a></p>

That shape decides two things. There is no pager, so `pagination` is `none`.
And the section heading is the only statement of type the source makes, so it
is read positionally: everything between the Testimony heading and the Press
Releases heading is testimony. HUD is one of the few agencies that labels
testimony at the index at all, and H-39 requires it stay distinct rather than
being folded into statement, so that is worth the positional parse.

The document pages are the worst case found for body extraction. SIX divs carry
`field--name-body`; five are theme blocks whose content is a `<style>` payload.
The article is the one inside `<div class="content">`, so the slice is anchored
there rather than on the field class, which on its own would have produced a
corpus of CSS.

The date is taken from the index, not the page. HUD's document footer carries a
`<time>` for the node's own timestamp, which for hud-no-26-065 reads 2026-09-04
against the index's 3 September: that is a modification stamp, not a
publication date, so the index wins and `date_source` stays `listing`.
"""

from __future__ import annotations

import re
from typing import Iterable

from ..base import (DocumentRef, ListingIncomplete, RawDocument, SourceAdapter, parse_date_text,
                    slice_element)
from ..text import _clean_inline

BASE = "https://www.hud.gov"
LISTING = BASE + "/news"

#: Section heading text -> the agency's own label for what follows it.
_SECTION_H2 = re.compile(r'<h2\b[^>]*>(.*?)</h2>', re.I | re.S)
_ITEM = re.compile(
    r'<p\b[^>]*>\s*([^<]{6,60}?)\s*<br\s*/?>\s*'
    r'<a\b[^>]*href="(/news/[^"]+)"[^>]*>(.*?)</a>', re.I | re.S)

_CONTENT = re.compile(r'<div\b[^>]*class="[^"]*\bcontent\b', re.I)
_BODY = re.compile(r'<div\b[^>]*class="[^"]*field--name-body', re.I)
_H1 = re.compile(r"<h1\b[^>]*>(.*?)</h1>", re.I | re.S)


def _label_for(heading: str) -> str:
    h = (heading or "").lower()
    if "testimony" in h:
        return "Testimony"
    if "press release" in h:
        return "Press Releases"
    return ""


class HudAdapter(SourceAdapter):
    institution_id = "us-hud"
    agency = "Department of Housing and Urban Development"
    tier = "listing"
    date_filter = "client"
    pagination = "none"
    newsroom_url = LISTING
    feed_url = ""

    label_map = {
        "Press Releases": "press_release",
        "Testimony": "testimony",
    }

    # -- listing -----------------------------------------------------------

    def list_documents(self, start_date: str, end_date: str) -> Iterable[DocumentRef]:
        try:
            html = self.fetcher.get_text(LISTING)
        except Exception as exc:  # noqa: BLE001
            raise ListingIncomplete(
                "%s: index page unreachable: %s" % (self.institution_id, exc)
            ) from exc

        # Where each labelled section begins. An item's label is whichever
        # section heading most recently preceded it.
        marks = []
        for m in _SECTION_H2.finditer(html):
            label = _label_for(_clean_inline(m.group(1)))
            if label:
                marks.append((m.start(), label))
        marks.sort()

        def label_at(pos: int) -> str:
            found = ""
            for start, label in marks:
                if start <= pos:
                    found = label
                else:
                    break
            return found

        seen: set[str] = set()
        for m in _ITEM.finditer(html):
            date = parse_date_text(m.group(1))
            if not date:
                continue          # a <p><br><a> that is not a dated news item
            url = BASE + m.group(2)
            if url in seen:
                continue
            label = label_at(m.start())
            if not label:
                continue          # outside both sections: navigation, not news
            if not self.in_window(date, start_date, end_date):
                continue
            seen.add(url)
            yield DocumentRef(
                institution_id=self.institution_id,
                url=url,
                title=_clean_inline(m.group(3)),
                date=date,
                date_source="listing",
                source_document_type=label,
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

        # Anchor on <div class="content"> first. Five of the six
        # `field--name-body` divs on this page are theme blocks full of CSS.
        body = ""
        for m in _CONTENT.finditer(page):
            candidate = slice_element(page[m.start():], _BODY, "div")
            if len(candidate) > len(body):
                body = candidate
        if not body.strip():
            doc.status = "no_body"
            return doc
        doc.html = body

        h1 = _H1.search(page)
        if h1:
            title = _clean_inline(h1.group(1))
            if title:
                doc.title = title
        return doc
