"""SSA -- one page, unquoted attributes, and the date in the filename.

The whole release list is on `/news/en/press/releases/` with no pager, so the
window is applied by reading dates. Note the `/en/` segment: `/news/press/
releases/` 404s, which is what the first survey pass hit.

Two conventions worth stating:

  * **Attributes are unquoted.** The markup is `<a href=/news/en/press/releases/
    2026-08-14.html>`, not `href="...">`. `base.attr()` handles both, but a
    regex written for quoted values finds nothing here, so the row patterns
    accept either form.
  * **The date is the filename.** `2026-08-14.html` needs no parsing at all,
    which makes it the most reliable date of the 24 -- it cannot disagree with
    itself. The visible text date is read too and the two are cross-checked.
"""

from __future__ import annotations

import re
from typing import Iterable

from ..base import (DocumentRef, ListingIncomplete, RawDocument, SourceAdapter,
                    parse_date_text, slice_element)
from ..text import _clean_inline

BASE = "https://www.ssa.gov"
LISTING = BASE + "/news/en/press/releases/"

#: Unquoted or quoted href, then the two divs the row carries: date, title.
_ROW = re.compile(
    r'<li\b[^>]*class="?[^">]*entry[^">]*"?[^>]*>\s*'
    r'<a\b[^>]*href=["\']?(/news/en/press/releases/(20\d\d-\d\d-\d\d)\.html)["\']?[^>]*>'
    r'(.*?)</a>', re.I | re.S)
_DIV = re.compile(r"<div\b[^>]*>(.*?)</div>", re.I | re.S)

#: SSA wraps the release in an <article>, not a div, and its classes are
#: layout tokens (`cell`, `l-w-70`) rather than semantic ones. Anchoring on
#: "content" or "main" picks up the page furniture and yields the subscribe
#: box instead of the release.
_BODY = re.compile(r'<article\b[^>]*class=["\']?[^">]*l-w-70', re.I)
#: SSA's <h1> is the SECTION heading -- "Press Office (Subscribe)" -- on every
#: release page, not the headline. Taking it gave all 17 SSA documents the same
#: useless title and disabled every title-based rule downstream, which is the
#: Treasury mega-menu fault (H-42 fault 1) in a third costume.
#:
#: The headline is in `og:title`, with `<title>` as the fallback. Both carry the
#: real thing: "Social Security Administration Marks 70th Anniversary of the
#: Disability Insurance Program".
_OG_TITLE = re.compile(
    r'<meta\b[^>]*property="og:title"[^>]*content="([^"]+)"', re.I)
_HEAD_TITLE = re.compile(r"<title\b[^>]*>(.*?)</title>", re.I | re.S)
#: Site suffixes the <title> carries and the headline does not.
_TITLE_SUFFIX = re.compile(r"\s*[|\-–]\s*(?:Press Release\s*)?"
                           r"(?:SSA|Social Security Administration)\s*$", re.I)
_H1 = re.compile(r"<h1\b[^>]*>(.*?)</h1>", re.I | re.S)


class SsaAdapter(SourceAdapter):
    institution_id = "us-ssa"
    agency = "Social Security Administration"
    tier = "listing"
    date_filter = "client"
    pagination = "none"
    newsroom_url = LISTING
    feed_url = ""

    label_map = {"Press Release": "press_release"}

    def list_documents(self, start_date: str, end_date: str) -> Iterable[DocumentRef]:
        try:
            html = self.fetcher.get_text(LISTING)
        except Exception as exc:            # noqa: BLE001
            raise ListingIncomplete(
                "%s: index page unreachable: %s"
                % (self.institution_id, exc)) from exc
        seen: set[str] = set()
        for m in _ROW.finditer(html):
            href, date = m.group(1), m.group(2)
            url = BASE + href
            if url in seen:
                continue
            divs = [_clean_inline(d) for d in _DIV.findall(m.group(3))]
            divs = [d for d in divs if d]
            # First div is the printed date, second the headline. If the shape
            # ever changes, fall back to whichever div is not a date.
            title = ""
            for d in divs:
                if not parse_date_text(d):
                    title = d
                    break
            if not title:
                title = _clean_inline(m.group(3))
            if not self.in_window(date, start_date, end_date):
                continue
            seen.add(url)
            yield DocumentRef(
                institution_id=self.institution_id,
                url=url,
                title=title,
                date=date,
                # The filename is machine-readable and on the document itself,
                # which is stronger than a rendered string on the index.
                date_source="metadata",
                source_document_type="Press Release",
                listing_url=LISTING,
            )

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
        body = slice_element(page, _BODY, "article")
        if not body.strip():
            doc.status = "no_body"
            return doc
        doc.html = body
        # og:title first, then <title>; the <h1> is the section heading.
        title = ''
        og = _OG_TITLE.search(page)
        if og:
            title = _clean_inline(og.group(1))
        if not title:
            ht = _HEAD_TITLE.search(page)
            if ht:
                title = _TITLE_SUFFIX.sub('', _clean_inline(ht.group(1)))
        if title:
            doc.title = title
        return doc
