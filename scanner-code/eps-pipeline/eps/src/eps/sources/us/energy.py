"""Department of Energy -- a faceted search that ignores its own pager.

`/search?f[0]=article_type:1&...` accepts `?page=N` and returns byte-identical
results for 0, 1 and 4: the facet results are rendered client-side, so a plain
fetch sees only the first screen however many pages it asks for. `/articles` is
server-rendered but carries almost no dates.

So Energy joins the archived-index group. `energy.gov/newsroom` has **170
captures** inside 2026-01-01..2026-07-31, each server-rendered with about 14
article links.

ONE TRAP WORTH NAMING
---------------------
An Energy article page carries a `<time>` element that reads TODAY's date --
2026-09-08 on a document published in April. It is a "last reviewed" stamp, not
a publication date. Taking it would have dated the entire Energy corpus to the
day of the run, which is the kind of fault that looks like data rather than an
error.

So Energy is the one agency in this group where the LISTING date wins and the
page date is ignored. `date_source` therefore stays `listing`, never upgrading
to `metadata`, and that is deliberate rather than an oversight.

Energy is also reachable in headless Chromium, unlike the rest of this group.
That is not used: a browser is heavier, and the archive route is already proven
and needs no desktop session.
"""

from __future__ import annotations

import re

from ..base import DocumentRef, RawDocument, attr, parse_date_text, slice_element
from ..text import _clean_inline
from ._archived_index import ArchivedIndexAdapter

BASE = "https://www.energy.gov"

#: The href must START with the article path, allowing only the Archive's
#: replay prefix and the agency's own origin in front of it.
#:
#: A lazy `[^"]*?` prefix instead of this anchoring is a real fault, not a
#: style point: energy.gov links to `/cio/articles/vulnerability-disclosure-
#: policy` and other per-office paths, and a lazy prefix captures those as
#: `/articles/vulnerability-disclosure-policy`, which 404s. That accounted for
#: all 20 of Energy's failed fetches on the first two runs -- documents that
#: were enumerated, counted, requested and lost, with the log recording
#: `fetch_failed` as though the site were at fault.
_LINK = re.compile(
    r'href="(?:https?://web\.archive\.org/web/\d+(?:id_)?/?)?'
    r'(?:https?://(?:www\.)?energy\.gov)?'
    r'(/articles/[a-z0-9][a-z0-9\-]{10,})"', re.I)
_TIME_TAG = re.compile(r"<time\b[^>]*>", re.I)
_TEXT_DATE = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2},\s+20\d\d\b")

#: The article body is `field--name-field-text`, and it exists ONLY in the
#: browser-rendered DOM.
#:
#: Two separate faults were stacked here and each hid the other:
#:
#: 1. Over plain HTTP the article prose is not in the page at all. It appears
#:    only inside `<meta name=description>`, `og:description` and
#:    `twitter:description`. The body is assembled client-side.
#: 2. `field--name-body` -- the obvious Drupal class, and the one used by four
#:    other agencies here -- matches a 288-byte sidebar promo reading "Funding
#:    Opportunities". So the selector returned something plausible rather than
#:    nothing, and 102 documents were collected containing those two words.
#:
#: Fixing (1) alone still yields the promo; fixing (2) alone still yields
#: nothing, because the container is absent from the raw HTML. The container
#: was found by asking the rendered DOM which element holds the prose, rather
#: than by pattern-matching the markup.
_BODY = re.compile(r'<div\b[^>]*class="[^"]*field--name-field-text', re.I)
_H1 = re.compile(r"<h1\b[^>]*>(.*?)</h1>", re.I | re.S)


class EnergyAdapter(ArchivedIndexAdapter):
    institution_id = "us-energy"
    agency = "Department of Energy"
    newsroom_url = BASE + "/newsroom"
    feed_url = ""

    archive_url = "energy.gov/newsroom"
    listing_url = BASE + "/newsroom"
    exact_suffix = "/newsroom"

    label_map = {
        "Article": "press_release",
        "Press Release": "press_release",
        "Speeches and Remarks": "speech",
        "Testimony": "testimony",
    }

    def _rows(self, html: str) -> list:
        out = []
        links = list(_LINK.finditer(html))
        for i, m in enumerate(links):
            path = m.group(1)
            end = links[i + 1].start() if i + 1 < len(links) else len(html)
            window = html[m.end():end]
            date = ""
            t = _TIME_TAG.search(window)
            if t:
                date = attr(t.group(0), "datetime")[:10]
            if not date:
                d = _TEXT_DATE.search(window)
                if d:
                    date = parse_date_text(d.group(0))
            out.append(DocumentRef(
                institution_id=self.institution_id,
                url=BASE + path,
                title="",
                date=date,
                date_source="listing" if date else "inferred",
                source_document_type="Article",
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

        body = slice_element(page, _BODY, "div")
        if not body.strip():
            doc.status = "no_body"
            return doc
        doc.html = body

        h1 = _H1.search(page)
        if h1:
            doc.title = _clean_inline(h1.group(1)) or doc.title

        # NO date read from the page. See the module docstring: energy.gov's
        # <time> is a "last reviewed" stamp carrying the current date, and
        # trusting it would date every Energy document to the day of the run.
        return doc
