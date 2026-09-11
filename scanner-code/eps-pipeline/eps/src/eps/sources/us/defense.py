"""Department of War (formerly Defense) -- the Vue listing, solved by the archive.

TWO FACTS ABOUT THIS AGENCY THAT ARE EASY TO GET WRONG
------------------------------------------------------
1. **The domain changed.** `defense.gov` redirects to `war.gov`, and the
   department is now the Department of War. `officeholders_2026.csv` still keys
   it `us-defense`, which is correct -- the slug is an identifier, not a name --
   but every URL here is war.gov.
2. **The live listing is Vue-rendered.** `/News/Releases/` returns 201KB
   containing exactly **2** article links, where a browser shows 31. An adapter
   parsing the live page would collect 2 documents and report success, which is
   why H-67 refused to register the first version of this file. The archive
   captured the same listing server-rendered, with 13 links and AP-style dates
   per capture: **186 captures** inside 2026-01-01..2026-07-31.

DATES ARE AP TEXT, NOT MARKUP
-----------------------------
There is no `<time datetime=...>` anywhere on a war.gov listing. Dates appear
as `Sept. 3, 2026` and `Aug. 31, 2026`, including the AP four-letter "Sept."
that a three-letter month table misses. `parse_date_text()` handles both, which
is what it was extended for (H-63).

The listing markup does carry the date in an attribute that is easier to trust
than the prose -- `<time data-dateago="2026-09-04T17:02:39" data-dateap="Sept.
4, 2026">` -- so that is preferred where present.

SECTIONS
--------
War.gov splits its newsroom into Releases, Advisories, Transcripts, Speeches and
Contracts. Contracts is a daily list of procurement awards -- hundreds of
documents of no relevance to what the Secretary said -- and is excluded. The
rest are collected and the section is preserved in `source_document_type`, so
the exclusion is the only judgement baked in and it is reversible by editing
one tuple.
"""

from __future__ import annotations

import re

from ..base import DocumentRef, RawDocument, attr, parse_date_text, slice_element
from ..text import _clean_inline
from ._archived_index import ArchivedIndexAdapter

BASE = "https://www.war.gov"

#: Newsroom sections worth collecting, and the label each carries.
#:
#: `Contracts` is deliberately absent: it is a daily procurement list running to
#: hundreds of items a month, none of them a statement by the officeholder.
SECTIONS = {
    "Releases": "Release",
    "Advisories": "Advisory",
    "Transcripts": "Transcript",
    "Speeches": "Speech",
}

_LINK = re.compile(
    r'href="[^"]*?(/News/(\w+)/[\w\-]*/?Article/(\d+)/[a-z0-9][a-z0-9\-]*/?)"', re.I)
_TIME_TAG = re.compile(r"<time\b[^>]*>", re.I)

_BODY = re.compile(r'<div\b[^>]*class="[^"]*article-view', re.I)
_H1 = re.compile(r"<h1\b[^>]*>(.*?)</h1>", re.I | re.S)
#: war.gov prints the document type in a flag beside the headline.
_TYPE_FLAG = re.compile(
    r'class="[^"]*presenterinfoType[^"]*"[^>]*>\s*([^<]{3,40}?)\s*<', re.I)


class DefenseAdapter(ArchivedIndexAdapter):
    institution_id = "us-defense"
    agency = "Department of Defense"
    newsroom_url = BASE + "/News/Releases/"
    feed_url = ""

    archive_url = "war.gov/News/Releases/"
    listing_url = BASE + "/News/Releases/"
    exact_suffix = "/News/Releases"

    label_map = {
        "Release": "press_release",
        "News Release": "press_release",
        "Advisory": "press_release",
        "Transcript": "interview_transcript",
        "Speech": "speech",
        "Contract": "other",
    }

    def _rows(self, html: str) -> list:
        out = []
        links = list(_LINK.finditer(html))
        for i, m in enumerate(links):
            path, section, _id = m.group(1), m.group(2), m.group(3)
            if section not in SECTIONS:
                continue                    # Contracts and anything new
            end = links[i + 1].start() if i + 1 < len(links) else len(html)
            date = ""
            t = _TIME_TAG.search(html, m.end(), end)
            if not t:
                # The date usually precedes the overlay link in the figcaption.
                start = links[i - 1].end() if i else 0
                t = _TIME_TAG.search(html, start, m.start())
            if t:
                tag = t.group(0)
                # The machine attribute first; the AP string is the fallback.
                date = attr(tag, "data-dateago")[:10] or \
                    parse_date_text(attr(tag, "data-dateap"))
            out.append(DocumentRef(
                institution_id=self.institution_id,
                url=BASE + path,
                title="",
                date=date,
                date_source="listing" if date else "inferred",
                source_document_type=SECTIONS[section],
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
            title = _clean_inline(h1.group(1))
            # The listing template also emits <h1>Releases</h1>; a page that
            # returns the section name has not returned the article.
            if title and title not in SECTIONS:
                doc.title = title

        flag = _TYPE_FLAG.search(page)
        if flag:
            label = _clean_inline(flag.group(1))
            if label:
                doc.source_document_type = label

        t = _TIME_TAG.search(page)
        if t:
            stamp = attr(t.group(0), "data-dateago")[:10] or \
                parse_date_text(attr(t.group(0), "data-dateap"))
            if stamp:
                doc.date = stamp
                doc.date_source = "metadata"
        return doc
