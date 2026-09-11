"""Department of Commerce -- a server-side date filter behind a JS challenge.

Written from an archived copy of the listing, for the same reason as `epa.py`:
the live page is behind a Cloudflare JavaScript challenge that neither an HTTP
client nor headless Chromium clears. It loads normally in a desktop browser.

The listing is the best-equipped of the 24 once reached. It exposes a real
date-range filter as exposed Drupal form values:

    ?field_release_datetime_value[min]=2026-01-01
    &field_release_datetime_value[max]=2026-07-31

so the window is applied server-side and the walk is over the window rather
than over the whole archive. Rows are plain:

    <div class="views-row"><article data-history-node-id="7221">
      <h2><a href="/news/press-releases/2025/12/<slug>"><span>Title</span></a></h2>
      <div class="field--name-field-release-datetime"><time datetime="2025-12-...">

The document URL also carries year and month, which is a fallback for a row
whose `<time>` is missing but is never preferred over the element.

TRANSPORT
---------
Commerce is the hardest of the 24 and the only one that has hardened against
everything tried, including the Internet Archive: 115 blocked captures against
5 successes between June and September 2026, the last success 2026-07-20. So
there is no archive fallback here as there is for EPA -- replaying captures
recovers 4 in-window documents, because the captured page itself went stale in
February.

That leaves one route: a headed browser on a normal network.

    python scripts/desktop_harvest.py us-commerce

If that is ever unavailable, the honest alternative is a request to the
Commerce press office, and the fallback after that is a documented one-agency
gap. Both are recorded in H-52.

SCOPE NOTE
----------
`/news/` also carries `speeches`, `op-eds`, `fact-sheets` and `blog`. Only
press-releases and speeches are collected; the others are departmental
explainers rather than statements by the Secretary. The section is recorded in
`source_document_type` either way, so widening it later needs no re-harvest.
"""

from __future__ import annotations

import re
from typing import Iterable, Iterator

from ..base import (DocumentRef, ListingIncomplete, RawDocument, SourceAdapter,
                    attr, slice_element)
from ..text import _clean_inline

BASE = "https://www.commerce.gov"

#: section path -> the agency's own label.
SECTIONS = {
    "/news/press-releases": "Press Release",
    "/news/speeches": "Speech",
}

MAX_PAGES = 60

_ROW = re.compile(r'<div\b[^>]*class="[^"]*views-row', re.I)
_LINK = re.compile(
    r'<h2\b[^>]*>\s*<a\b[^>]*href="(/news/[a-z\-]+/(20\d\d)/(\d{2})/[^"]+)"'
    r'[^>]*>(.*?)</a>', re.I | re.S)
_TIME = re.compile(r"<time\b[^>]*>", re.I)

_BODY = re.compile(
    r'<div\b[^>]*class="[^"]*(?:field--name-body|node__content)', re.I)
_MAIN = re.compile(r'<(?:main|div)\b[^>]*id="(?:main-content|block-mainpagecontent)"',
                   re.I)
_H1 = re.compile(r"<h1\b[^>]*>(.*?)</h1>", re.I | re.S)


class CommerceAdapter(SourceAdapter):
    institution_id = "us-commerce"
    agency = "Department of Commerce"
    tier = "listing"
    date_filter = "server"
    pagination = "page_param"
    newsroom_url = BASE + "/news/press-releases"
    feed_url = ""

    label_map = {
        "Press Release": "press_release",
        "Speech": "speech",
        "Op-Ed": "op_ed",
        "Fact Sheet": "other",
        "Blog": "other",
    }

    # -- listing -----------------------------------------------------------

    def list_documents(self, start_date: str, end_date: str) -> Iterable[DocumentRef]:
        seen: set[str] = set()
        for path, label in SECTIONS.items():
            for ref in self._section_refs(path, label, start_date, end_date):
                if ref.url in seen:
                    continue
                seen.add(ref.url)
                yield ref

    def _section_refs(self, path: str, label: str, start_date: str,
                      end_date: str) -> Iterator[DocumentRef]:
        for page in range(MAX_PAGES):
            params = {
                "field_release_datetime_value[min]": start_date,
                "field_release_datetime_value[max]": end_date,
                "page": page,
            }
            try:
                html = self.fetcher.get_text(BASE + path, params)
            except Exception as exc:                 # noqa: BLE001
                raise ListingIncomplete(
                    "%s: index page unreachable: %s. Commerce needs a headed "
                    "browser session -- see scripts/desktop_harvest.py"
                    % (self.institution_id, exc)) from exc
            rows = self._rows(html, label, BASE + path)
            if not rows:
                return
            for ref in rows:
                if self.in_window(ref.date, start_date, end_date):
                    yield ref
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
            href, year, month, title = link.groups()
            t = _TIME.search(row)
            date = attr(t.group(0), "datetime")[:10] if t else ""
            source = "listing"
            if not date:
                # Month precision from the path; the day is not in the URL.
                date, source = "%s-%s-01" % (year, month), "inferred"
            out.append(DocumentRef(
                institution_id=self.institution_id,
                url=BASE + href,
                title=_clean_inline(title),
                date=date,
                date_source=source,
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
                doc.date = stamp
                doc.date_source = "metadata"
        return doc
