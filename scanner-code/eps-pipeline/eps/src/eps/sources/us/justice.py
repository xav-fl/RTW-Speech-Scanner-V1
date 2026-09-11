"""Department of Justice -- past the interstitial by not needing the listing.

`/opa/pr` and `/news` return a 2.2KB Akamai `bm-verify` challenge page to every
HTTP client and to Chrome TLS impersonation. Individual releases do not:
`/opa/pr/<slug>` returns 92KB with a real `<h1>`, a `<time>` and a `usa-prose`
body. So Justice is another case of "the index is closed, the documents are
open", and it is collected the same way EPA is.

TWO THINGS THE SURVEY GOT WRONG ABOUT JUSTICE
---------------------------------------------
1. **The archive does hold the listing, under `/news` rather than `/opa/pr`.**
   A first check for captures of `justice.gov/opa/pr` returned zero and the
   agency was written off as unreachable. `justice.gov/news` has **196 captures**
   inside 2026-01-01..2026-07-31, each carrying about 11 release links with a
   `<time>` on each.
2. **`/opa/speeches` was not the ceiling.** It looked like the only reachable
   surface, capping Justice at roughly 11 documents. Archived captures of
   `/news` reach the press releases as well.

`robots.txt` sets `crawl-delay: 10`, the strictest of the 24. That governs
justice.gov, not the Archive, so enumeration is unaffected -- but the live body
fetches must honour it, which is why this adapter asks for a slower pace than
the default and says so here rather than leaving it to the caller.
"""

from __future__ import annotations

import re

from ..base import DocumentRef, RawDocument, attr, slice_element
from ..text import _clean_inline
from ._archived_index import ArchivedIndexAdapter

BASE = "https://www.justice.gov"

#: Release links as they appear on the listing. `/opa/pr/<slug>` is a press
#: release; `/opa/speech/<slug>` is a speech, and both are collected.
#: Anchored, not lazy. See the note in energy.py: a lazy prefix captures
#: /foo/opa/pr/bar as /opa/pr/bar and silently manufactures 404s.
_LINK = re.compile(
    r'href="(?:https?://web\.archive\.org/web/\d+(?:id_)?/?)?'
    r'(?:https?://(?:www\.)?justice\.gov)?'
    r'(/opa/(pr|speech)/[a-z0-9][a-z0-9\-]{8,})"', re.I)
_TIME_TAG = re.compile(r"<time\b[^>]*>", re.I)

#: The article body is "node-body".
#:
#: It is NOT "usa-prose". justice.gov puts that class on its MENUS -- the main
#: nav at about 7.7KB (id=doj-menu) and the news sidebar at about 59KB -- and
#: neither is an article. Slicing the first match returned 18KB of navigation,
#: and all 713 Justice documents came out as the same 64 words: "DOJ Menu /
#: About / The Attorney General / Organizational Chart / Budget & Performance
#: ...". Identical median, min and max word count across a whole agency is the
#: tell, and it is what the per-agency check caught (H-82).
_BODY = re.compile(r'<div\b[^>]*class="[^"]*\bnode-body\b', re.I)
_H1 = re.compile(r"<h1\b[^>]*>(.*?)</h1>", re.I | re.S)

#: Section slug -> the agency's own label.
_LABEL = {"pr": "Press Release", "speech": "Speech"}


class JusticeAdapter(ArchivedIndexAdapter):
    institution_id = "us-justice"
    agency = "Department of Justice"
    newsroom_url = BASE + "/news"
    feed_url = ""

    archive_url = "justice.gov/news"
    listing_url = BASE + "/news"
    exact_suffix = "/news"

    label_map = {
        "Press Release": "press_release",
        "Speech": "speech",
        "Testimony": "testimony",
    }

    def _rows(self, html: str) -> list:
        """Pair each release link with the `<time>` that follows it.

        The archived listing has no wrapper element the replay preserves
        reliably, so link and date are paired positionally: a link takes the
        first `<time>` between it and the next link.
        """
        out = []
        links = list(_LINK.finditer(html))
        for i, m in enumerate(links):
            path, section = m.group(1), m.group(2)
            end = links[i + 1].start() if i + 1 < len(links) else len(html)
            t = _TIME_TAG.search(html, m.end(), end)
            date = attr(t.group(0), "datetime")[:10] if t else ""
            out.append(DocumentRef(
                institution_id=self.institution_id,
                url=BASE + path,
                title="",                   # taken from the page, not the index
                date=date,
                date_source="listing" if date else "inferred",
                source_document_type=_LABEL.get(section, "Press Release"),
                listing_url=self.listing_url,
            ))
        return out

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

        # A challenge page is ~2.2KB and has no <h1>. Treat it as a fetch
        # failure rather than an empty document, so the log distinguishes
        # "blocked" from "published nothing".
        if len(page) < 6000 and "bm-verify" in page:
            doc.status = "fetch_failed"
            doc.error = "interstitial served instead of the document"
            return doc

        body = slice_element(page, _BODY, "div")
        if not body.strip():
            doc.status = "no_body"
            return doc
        doc.html = body

        h1 = _H1.search(page)
        if h1:
            doc.title = _clean_inline(h1.group(1)) or doc.title

        t = _TIME_TAG.search(page)
        if t:
            stamp = attr(t.group(0), "datetime")[:10]
            if stamp:
                doc.date = stamp
                doc.date_source = "metadata"
        return doc
