"""Small Business Administration -- the richest type vocabulary of the 24.

SBA is the only agency whose index states the document type as a facet rather
than leaving it to be guessed from a heading or a title. `article_type` is a
numeric taxonomy and it maps straight onto the normalised labels:

    137  News release            283  (see below)
    279  Archived news release
    383  OIG news release
    134  Disaster news release
    133  Congressional testimony   <- testimony, stated by the source
    253  Memo
    136  Op-ed                     <- the only op_ed any agency labels
    138  Speech

That means SBA needs none of the title heuristics Treasury required (H-42
fault 3): where the source states the type, the source is used.

Two collection facts, both from the survey:

  * The content moved. `www.sba.gov` was redesigned and its newsroom is now a
    hub that links out; every document lives on `legacy.sba.gov`, and the
    usable listing is `legacy.sba.gov/articles`. Pointing an adapter at
    www.sba.gov would collect nothing.
  * Document URLs are `/article/YYYY/MM/DD/<slug>`, so the date is in the path
    as well as in a `<time datetime=...>` on the row. The row element wins;
    the path is the fallback.

Only the four release types, testimony, op-ed and speech are collected.
`Memo` is internal administrative guidance rather than public statement, and
`Disaster news release` and `OIG news release` are collected but map to
`press_release` and can be filtered downstream on the raw label, which is
preserved.
"""

from __future__ import annotations

import re
from typing import Iterable, Iterator

from ..base import (DocumentRef, ListingIncomplete, RawDocument,
                    SourceAdapter, slice_element)
from ..text import _clean_inline

BASE = "https://legacy.sba.gov"

#: article_type id -> the agency's own label. Collected in this order.
ARTICLE_TYPES = {
    "137": "News release",
    "279": "Archived news release",
    "383": "OIG news release",
    "134": "Disaster news release",
    "133": "Congressional testimony",
    "138": "Speech",
    "136": "Op-ed",
}

MAX_PAGES = 60

_CARD = re.compile(r'<article\b[^>]*class="[^"]*article-card', re.I)
_TAG = re.compile(
    r'<div\b[^>]*class="[^"]*usa-tag[^"]*"[^>]*>(.*?)</div>', re.I | re.S)
_LINK = re.compile(
    r'<h3\b[^>]*class="[^"]*article-card__title[^"]*"[^>]*>\s*'
    r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S)
_TIME = re.compile(r'<time\b[^>]*datetime="([^"]{10})', re.I)
_URL_DATE = re.compile(r"/article/(20\d\d)/(\d{2})/(\d{2})/")

_BODY = re.compile(r'<div\b[^>]*class="[^"]*sba-article__content', re.I)
_H1 = re.compile(r"<h1\b[^>]*>(.*?)</h1>", re.I | re.S)
_CLASSIFICATION = re.compile(
    r'<div\b[^>]*class="[^"]*sba-article__classification[^"]*"[^>]*>(.*?)</div>',
    re.I | re.S)


class SbaAdapter(SourceAdapter):
    institution_id = "us-sba"
    agency = "Small Business Administration"
    tier = "listing"
    date_filter = "client"
    pagination = "page_param"
    newsroom_url = BASE + "/articles?keyword=&article_type=137&langcode=en"
    feed_url = ""

    label_map = {
        "News release": "press_release",
        "Archived news release": "press_release",
        "OIG news release": "press_release",
        "Disaster news release": "press_release",
        "Congressional testimony": "testimony",
        "Speech": "speech",
        "Op-ed": "op_ed",
        "Memo": "other",
    }

    # -- listing -----------------------------------------------------------

    def list_documents(self, start_date: str, end_date: str) -> Iterable[DocumentRef]:
        seen: set[str] = set()
        for type_id, label in ARTICLE_TYPES.items():
            for ref in self._type_refs(type_id, label, start_date, end_date):
                if ref.url in seen:
                    continue
                seen.add(ref.url)
                yield ref

    def _type_refs(self, type_id: str, label: str, start_date: str,
                   end_date: str) -> Iterator[DocumentRef]:
        for page in range(MAX_PAGES):
            try:
                html = self.fetcher.get_text(
                    BASE + "/articles",
                    {"keyword": "", "article_type": type_id,
                     "langcode": "en", "page": page})
            except Exception as exc:  # noqa: BLE001
                raise ListingIncomplete(
                    "%s: index page unreachable: %s" % (self.institution_id, exc)
                ) from exc
            rows = self._rows(html, label)
            if not rows:
                return
            for ref in rows:
                if self.in_window(ref.date, start_date, end_date):
                    yield ref
            # Rows are newest first, so a page entirely older than the window
            # means every later page is too.
            newest = max((r.date for r in rows if r.date), default="")
            if newest and newest < start_date:
                return
            self.fetcher.rest()

    def _rows(self, html: str, default_label: str) -> list[DocumentRef]:
        out: list[DocumentRef] = []
        starts = [m.start() for m in _CARD.finditer(html)]
        for i, start in enumerate(starts):
            end = starts[i + 1] if i + 1 < len(starts) else len(html)
            row = html[start:end]
            link = _LINK.search(row)
            if not link:
                continue
            href = link.group(1)
            t = _TIME.search(row)
            date = t.group(1) if t else ""
            source = "listing"
            if not date:
                u = _URL_DATE.search(href)
                if u:
                    date = "%s-%s-%s" % u.groups()
                    source = "inferred"
            tag = _TAG.search(row)
            # The row's own tag is the authority; the facet label is a fallback
            # for a row that does not carry one.
            label = _clean_inline(tag.group(1)) if tag else default_label
            out.append(DocumentRef(
                institution_id=self.institution_id,
                url=href if href.startswith("http") else BASE + href,
                title=_clean_inline(link.group(2)),
                date=date,
                date_source=source if date else "inferred",
                source_document_type=label or default_label,
                listing_url=BASE + "/articles",
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
            doc.title = _clean_inline(h1.group(1)) or doc.title

        t = _TIME.search(page)
        if t:
            doc.date = t.group(1)
            doc.date_source = "metadata"

        # "News release 26-89" -- the release number, which also confirms the
        # type on the document itself rather than only on the index.
        #
        # The number has to be stripped HARD. Disaster releases are classified
        # "Disaster news release OK-20026-05 (21092)", and a rule that only
        # removed a trailing run of digits left the identifier attached. Every
        # such document then carried a unique `source_document_type`, matched
        # no `label_map` entry, and was typed `other`: 512 of 2,687 documents
        # in the first full harvest, nearly all of them SBA disaster releases.
        # Only the leading words are the type; anything from the first
        # state-code or digit onward is an identifier.
        cls = _CLASSIFICATION.search(page)
        if cls:
            text = _clean_inline(cls.group(1))
            # Strip a trailing state-code stub ("... WA-"), then everything
            # from the first token containing a digit. Identifiers take several
            # shapes -- "26-89", "OK-20026-05 (21092)", "WI20005-01" -- and a
            # rule keyed on any one of them leaves the others attached.
            trimmed = re.sub(r"\s+\S*\d.*$", "",
                             re.sub(r"\s+[A-Z]{2}-\s*$", "", text)).strip()
            if trimmed:
                doc.source_document_type = trimmed
        return doc
