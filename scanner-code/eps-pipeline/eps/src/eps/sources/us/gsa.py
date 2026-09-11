"""General Services Administration -- a whole year on one page.

GSA's `?year=YYYY` facet returns every release for that year in a single HTML
table, 71 rows for 2026, with no pagination at all. `?page=N` is accepted and
ignored, which is why `pagination` is `none` rather than `page_param`: asking
for page 2 returns page 1 again, and an adapter that trusted the pager would
collect the same 71 rows forever.

The table is the friendliest markup of the 24:

    <tr><td class="publish-date">09/03/2026</td>
        <td class="views-field views-field-title"><a href="...">Title</a></td></tr>

Speeches live in a separate section with the same year facet, so both are
unioned. Note the path is `/about-gsa/`, not the `/about-us/` the brief lists.
"""

from __future__ import annotations

import re
from typing import Iterable, Iterator

from ..base import (DocumentRef, ListingIncomplete, RawDocument, SourceAdapter, parse_date_text,
                    slice_element)
from ..text import _clean_inline

BASE = "https://www.gsa.gov"

#: section path -> the agency's own label for what it holds.
SECTIONS = {
    "/about-gsa/newsroom/news-releases": "News Release",
    "/about-gsa/newsroom/speeches-by-the-administrator": "Speech",
}

_ROW = re.compile(
    r'<tr\b[^>]*>\s*<td\b[^>]*class="[^"]*publish-date[^"]*"[^>]*>(.*?)</td>\s*'
    r'<td\b[^>]*>\s*<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S)

_BODY = re.compile(r'<div\b[^>]*id="gsa-body"', re.I)
_H1 = re.compile(r"<h1\b[^>]*>(.*?)</h1>", re.I | re.S)
_TIME = re.compile(r'<time\b[^>]*datetime="([^"]{10})', re.I)


class GsaAdapter(SourceAdapter):
    institution_id = "us-gsa"
    agency = "General Services Administration"
    tier = "listing"
    date_filter = "server"
    pagination = "none"
    newsroom_url = BASE + "/about-gsa/newsroom/news-releases"
    feed_url = ""

    label_map = {
        "News Release": "press_release",
        "Speech": "speech",
    }

    # -- listing -----------------------------------------------------------

    def list_documents(self, start_date: str, end_date: str) -> Iterable[DocumentRef]:
        seen: set[str] = set()
        for year in range(int(start_date[:4]), int(end_date[:4]) + 1):
            for path, label in SECTIONS.items():
                for ref in self._year_refs(path, label, year, start_date, end_date):
                    if ref.url in seen:
                        continue
                    seen.add(ref.url)
                    yield ref

    def _year_refs(self, path: str, label: str, year: int, start_date: str,
                   end_date: str) -> Iterator[DocumentRef]:
        try:
            html = self.fetcher.get_text(BASE + path, {"year": year})
        except Exception as exc:  # noqa: BLE001
            raise ListingIncomplete(
                "%s: index page unreachable: %s" % (self.institution_id, exc)
            ) from exc
        self.fetcher.rest()
        for m in _ROW.finditer(html):
            href = m.group(2)
            if not href.startswith("/about-gsa/newsroom/"):
                continue
            date = parse_date_text(_clean_inline(m.group(1)))
            if not self.in_window(date, start_date, end_date):
                continue
            yield DocumentRef(
                institution_id=self.institution_id,
                url=BASE + href,
                title=_clean_inline(m.group(3)),
                date=date,
                date_source="listing" if date else "inferred",
                source_document_type=label,
                listing_url=BASE + path,
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

        body = slice_element(page, _BODY, "div")
        if not body.strip():
            doc.status = "no_body"
            return doc
        # `#gsa-body` opens with the <time> stamp and the <h1>, so slicing it
        # whole puts "July 31, 2026" and the headline into the document text as
        # though the agency had written them as prose. Everything up to and
        # including the first </h1> is chrome, not body.
        cut = re.search(r"</h1\s*>", body, re.I)
        if cut:
            body = body[cut.end():]
        doc.html = body

        h1 = _H1.search(page)
        if h1:
            doc.title = _clean_inline(h1.group(1)) or doc.title

        t = _TIME.search(page)
        if t:
            doc.date = t.group(1)
            doc.date_source = "metadata"
        return doc
