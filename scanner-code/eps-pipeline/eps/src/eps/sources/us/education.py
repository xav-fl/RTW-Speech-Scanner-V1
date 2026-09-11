"""Department of Education -- the `tier: listing` reference adapter.

ed.gov publishes a Drupal view per content type, ten items to a page, newest
first, with no date parameter of any kind:

    /about/news/press-release?page=0
    /about/news/speech?page=0

So the date filter runs client-side. What makes that affordable is that the
listing rows carry a <time datetime=...> of their own: the window can be
applied from the index, and paging stops at the first page whose newest item
predates the window, without a single document body being fetched. That is the
distinction the interface exists to hold -- `list_documents` never fetches a
body, whatever the site makes it do to find the dates.

Two sections exist, `press-release` and `speech`. There is no statement,
testimony or op-ed section; a request for one returns 404. That is a fact about
the source, and it goes in the gate report rather than being papered over.
"""

from __future__ import annotations

import re
from typing import Iterable, Iterator

from ..base import DocumentRef, RawDocument, SourceAdapter, attr, slice_element
from ..text import _clean_inline

BASE = "https://www.ed.gov"

#: url path segment -> the label ed.gov prints on the listing row.
SECTIONS = {
    "press-release": "Press Release",
    "speech": "Speech",
}

#: ed.gov reports "Showing 1 - 10 of 403 items" and offers pages up to 40. The
#: cap is a runaway guard, not a real bound; paging normally stops on date.
MAX_PAGES = 60

_ROW_ANY = re.compile(r"<div\b[^>]*class\s*=\s*[\"']views-row[\"'][^>]*>", re.I)
_LINK = re.compile(
    r"views-field-title.*?<a\b[^>]*href\s*=\s*[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
    re.I | re.S,
)
_ROW_TYPE = re.compile(
    r"newsroom-content-type[^>]*>\s*<span[^>]*>([^<]*)</span>", re.I | re.S
)
_ROW_TIME = re.compile(r"<time\b[^>]*>", re.I)

_BODY = re.compile(
    r"<div\b[^>]*class\s*=\s*[\"']?[^\"'>]*field--name-body", re.I
)
_H1 = re.compile(r"<h1\b[^>]*>(.*?)</h1>", re.I | re.S)
_PUBLISHED = re.compile(
    r"<div\b[^>]*field--name-published-at[^>]*>(.*?)</div>", re.I | re.S
)


def _text(fragment: str) -> str:
    """Tags to spaces, entities unescaped -- the shared rule, not a local one."""
    return _clean_inline(fragment or "")


class EducationAdapter(SourceAdapter):
    institution_id = "us-education"
    agency = "Department of Education"
    tier = "listing"
    date_filter = "client"
    pagination = "page_param"
    newsroom_url = BASE + "/about/news/press-release"
    feed_url = ""

    label_map = {
        "Press Release": "press_release",
        "Speech": "speech",
    }

    # -- listing -----------------------------------------------------------

    def list_documents(self, start_date: str, end_date: str) -> Iterable[DocumentRef]:
        seen: set[str] = set()
        for section in SECTIONS:
            for ref in self._section_refs(section, start_date, end_date):
                if ref.url in seen:
                    continue
                seen.add(ref.url)
                yield ref

    def _section_refs(self, section: str, start_date: str,
                      end_date: str) -> Iterator[DocumentRef]:
        listing = BASE + "/about/news/" + section
        for page in range(MAX_PAGES):
            try:
                html = self.fetcher.get_text(listing, {"page": page})
            except Exception:
                return
            rows = self._rows(html)
            if not rows:
                return
            newest = max((r.date for r in rows if r.date), default="")
            for ref in rows:
                if self.in_window(ref.date, start_date, end_date):
                    yield ref
            # Rows are newest first. Once a whole page predates the window,
            # every later page does too.
            if newest and newest < start_date:
                return
            self.fetcher.rest()

    def _rows(self, html: str) -> list[DocumentRef]:
        out: list[DocumentRef] = []
        starts = [m.start() for m in _ROW_ANY.finditer(html)]
        for i, start in enumerate(starts):
            end = starts[i + 1] if i + 1 < len(starts) else len(html)
            row = html[start:end]
            link = _LINK.search(row)
            if not link:
                continue
            href = link.group(1)
            if not href.startswith("/about/news/"):
                continue
            t = _ROW_TIME.search(row)
            date = attr(t.group(0), "datetime")[:10] if t else ""
            label = _ROW_TYPE.search(row)
            out.append(DocumentRef(
                institution_id=self.institution_id,
                url=BASE + href,
                title=_text(link.group(2)),
                date=date,
                date_source="listing" if date else "inferred",
                source_document_type=_text(label.group(1)) if label else "",
                listing_url=BASE + href.rsplit("/", 1)[0],
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

        body = slice_element(page, _BODY, "div")
        if not body.strip():
            doc.status = "no_body"
            return doc
        doc.html = body

        h1 = _H1.search(page)
        if h1:
            doc.title = _text(h1.group(1)) or doc.title

        pub = _PUBLISHED.search(page)
        t = _ROW_TIME.search(pub.group(1)) if pub else None
        if t:
            stamp = attr(t.group(0), "datetime")[:10]
            if stamp:
                doc.date = stamp
                doc.date_source = "metadata"
        return doc
