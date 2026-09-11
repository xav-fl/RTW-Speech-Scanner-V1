"""Department of the Treasury -- the `tier: feed` reference adapter.

Treasury's newsroom is a static site backed by a set of JSON indexes. Each
newsroom category has a manifest listing one shard per publication year:

    /news-data/<category>/manifest.json
    /news-data/<category>/search/<year>.json

So the date filter runs server-side in the only sense that matters here: a
seven-month window costs one shard fetch per category, not a walk through
fifteen years of listings. That is what `tier: feed` buys.

Two things the interface had to accommodate, both recorded at the review gate:

1. The categories are not nested. `readouts` is a subset of `press-releases`,
   but `statements-remarks` is NOT -- 34 items in 2026, several of which never
   appear in the press-releases index. Listing has to union the categories and
   de-duplicate on URL.

2. `sectionLabel` is "Press Releases" for every item regardless of what it is.
   The label that discriminates lives in `subcategory.title`, and even that is
   ambiguous: "Statements & Remarks" holds both delivered remarks and written
   statements. See `refine_type()`.
"""

from __future__ import annotations

import re
from typing import Iterable, Iterator

from ..base import DocumentRef, RawDocument, SourceAdapter, attr, slice_element
from ..text import _clean_inline

BASE = "https://home.treasury.gov"

#: Newsroom categories to union. `featured-stories` is included because it
#: carries a handful of substantive items a year that appear nowhere else.
CATEGORIES = (
    "press-releases",
    "statements-remarks",
    "readouts",
    "testimonies",
    "featured-stories",
)

_BODY = re.compile(
    r"<div\b[^>]*class\s*=\s*[\"']?[^\"'>]*field--name-field-news-body", re.I
)
# The page title, anchored to the page-title heading. `field--name-title` on
# its own is NOT specific enough: the mega-menu emits a span with that class for
# every navigation panel, and the first one on the page is "About Treasury".
_TITLE = re.compile(r"<h2\b[^>]*class\s*=\s*[\"']?[^\"'>]*uswds-page-title", re.I)
_ARTICLE = re.compile(r"<article\b[^>]*>", re.I)
_PUBDATE = re.compile(
    r"<div\b[^>]*field--name-field-news-publication-date[^>]*>(.*?)</div>", re.I | re.S
)
_TIME = re.compile(r"<time\b[^>]*>", re.I)

# Titles that announce a written statement rather than delivered remarks.
_STATEMENT = re.compile(r"\bstatement\b", re.I)
_REMARKS = re.compile(r"\bremarks\b|\bdelivers\b|\bspeech\b", re.I)


def _is_section_landing(item: dict) -> bool:
    """True for the three navigation pages the press-releases index carries.

    The 2026 index lists Readouts, Statements & Remarks and Testimonies as items
    in their own right, all stamped 2026-01-13, each pointing at its section
    landing page. Left in, they arrive as bodyless documents and -- worse -- the
    Testimonies one would be the only thing in the corpus labelled `testimony`
    for the window, which is precisely the count the study needs to be right.

    Identified by both halves at once: the title is the section label, and the
    URL is that section's own path.
    """
    slug = (item.get("sectionSlug") or "").strip()
    title = (item.get("title") or "").strip()
    label = (item.get("sectionLabel") or "").strip()
    url = (item.get("url") or "").rstrip("/")
    return bool(slug) and title == label and url.endswith("/" + slug)


class TreasuryAdapter(SourceAdapter):
    institution_id = "us-treasury"
    agency = "Department of the Treasury"
    tier = "feed"
    date_filter = "server"
    pagination = "offset"
    newsroom_url = BASE + "/news/press-releases"
    feed_url = BASE + "/news-data/press-releases/manifest.json"

    label_map = {
        "Press Releases": "press_release",
        "Statements & Remarks": "speech",
        "Secretary Statements & Remarks": "speech",
        "Readouts": "press_release",
        "Testimonies": "testimony",
        "Testimony": "testimony",
        "Featured Stories": "press_release",
    }

    # -- listing -----------------------------------------------------------

    def list_documents(self, start_date: str, end_date: str) -> Iterable[DocumentRef]:
        years = range(int(start_date[:4]), int(end_date[:4]) + 1)
        seen: set[str] = set()
        for category in CATEGORIES:
            for ref in self._category_refs(category, years, start_date, end_date):
                if ref.url in seen:
                    continue
                seen.add(ref.url)
                yield ref

    def _category_refs(self, category: str, years, start_date: str,
                       end_date: str) -> Iterator[DocumentRef]:
        try:
            manifest = self.fetcher.get_json(
                BASE + "/news-data/" + category + "/manifest.json")
        except Exception:
            # A category that has gone away is not a reason to lose the rest.
            return
        shards = {s.get("name"): s.get("path") for s in manifest.get("searchShards", [])}
        for year in years:
            path = shards.get(str(year))
            if not path:
                # No shard means the agency published nothing in that category
                # that year. Treasury's `testimonies` shards stop at 2024.
                continue
            self.fetcher.rest()
            try:
                shard = self.fetcher.get_json(BASE + path)
            except Exception:
                continue
            for item in shard.get("items", []):
                date = (item.get("date") or item.get("datetime") or "")[:10]
                if not self.in_window(date, start_date, end_date):
                    continue
                url = item.get("url") or ""
                if not url or _is_section_landing(item):
                    continue
                sub = item.get("subcategory") or {}
                label = (sub.get("title") or item.get("sectionLabel") or "").strip()
                yield DocumentRef(
                    institution_id=self.institution_id,
                    url=BASE + url if url.startswith("/") else url,
                    title=_clean_inline(item.get("title") or ""),
                    date=date,
                    date_source="listing",
                    source_document_type=label,
                    listing_url=BASE + "/news/" + category,
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
        doc.html = body

        # _clean_inline, not a bare tag strip: the title carries entities
        # ("S&amp;P") and non-breaking spaces that would otherwise survive
        # into the log and the filename.
        page_title = _clean_inline(slice_element(page, _TITLE, "h2"))
        if page_title:
            doc.title = page_title

        # The <article> element repeats the index metadata on the document
        # itself, which is stronger evidence than the index alone.
        art = _ARTICLE.search(page)
        if art:
            page_date = attr(art.group(0), "data-news-date")[:10]
            page_label = attr(art.group(0), "data-news-section-label")
            if page_date:
                doc.date = page_date
                doc.date_source = "metadata"
            if page_label and not doc.source_document_type:
                doc.source_document_type = page_label
        if doc.date_source != "metadata":
            block = _PUBDATE.search(page)
            t = _TIME.search(block.group(1)) if block else None
            if t:
                stamp = attr(t.group(0), "datetime")[:10]
                if stamp:
                    doc.date = stamp
                    doc.date_source = "metadata"
        return doc

    # -- typing ------------------------------------------------------------

    def refine_type(self, mapped: str, source_label: str, title: str) -> str:
        """Split Treasury's one ambiguous label using the document title.

        "Statements & Remarks" covers two different things: "Remarks from
        Secretary of the Treasury Scott Bessent at ..." is a speech, and
        "Secretary Bessent Issues Statement Welcoming ..." is a statement.

        Testimony is NOT handled here. Treasury files it under the same heading
        rather than under Testimonies, but so do other agencies under headings
        of their own, so that rule lives in `base.looks_like_testimony()` and
        runs for every adapter.

        The raw label stays in `source_document_type`, so this refinement can
        be revised or dropped without re-harvesting anything.
        """
        if mapped == "speech" and _STATEMENT.search(title or "") \
                and not _REMARKS.search(title or ""):
            return "statement"
        return mapped
