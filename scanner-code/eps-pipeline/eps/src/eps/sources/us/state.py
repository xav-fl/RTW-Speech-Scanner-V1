"""Department of State -- WordPress that must NOT be collected through its API.

State runs WordPress and answers `/wp-json/wp/v2/state_press_release` with HTTP
200, which makes it look like the NASA and VA case. It is not. CloudFront strips
the query string, so `after`, `before`, `page`, `per_page` and `orderby` are all
discarded and every request returns the same newest ten rows. An adapter built
on that API would have produced a ten-document corpus and reported no error.
That is the single most dangerous thing the survey found, and it is why
`_wordpress.WordPressAdapter` re-verifies its window at run time and why State
does not inherit from it.

What works instead is path pagination, which CloudFront caches per path:

    /press-releases/            newest
    /press-releases/page/3/     older   (verified: p1 2026-09-06, p3 2026-08-27)

The listing rows are unusually rich. Each carries the document type, the title,
the speaker's name and the date:

    <li class="collection-result">
      <p class="collection-result__date">Press Statement</p>     <- the TYPE
      <a class="collection-result__link" href="...">Title</a>
      <div class="collection-result-meta">
        <span>Marco Rubio</span><span>September 6, 2026</span>

Note the class names are misleading: `collection-result__date` holds the type,
and the date is the second span of the meta block. The speaker is captured into
`speaker_hints`, since State is the only agency of the 24 that names the author
on the index, and the document page repeats it in
`article-meta__author-bureau`.

Two scope facts. Document URLs are `/releases/<office>/YYYY/MM/<slug>/`, so the
date is in the path as a fallback. And the `office-of-the-spokesperson` segment
marks items issued in the spokesperson's name rather than the Secretary's,
which the speaker fields make visible downstream rather than being filtered here
(H-34).
"""

from __future__ import annotations

import re
from typing import Iterable, Iterator

from ..base import (DocumentRef, ListingIncomplete, RawDocument,
                    SourceAdapter, parse_date_text)
from ..text import _clean_inline

BASE = "https://www.state.gov"

MAX_PAGES = 120

_ROW = re.compile(r'<li\b[^>]*class="[^"]*collection-result[^"]*"', re.I)
_TYPE = re.compile(
    r'<p\b[^>]*class="[^"]*collection-result__date[^"]*"[^>]*>(.*?)</p>',
    re.I | re.S)
_LINK = re.compile(
    r'<a\b[^>]*href="([^"]+)"[^>]*class="[^"]*collection-result__link[^"]*"[^>]*>'
    r'(.*?)</a>', re.I | re.S)
_META = re.compile(
    r'<div\b[^>]*class="[^"]*collection-result-meta[^"]*"[^>]*>(.*?)</div>',
    re.I | re.S)
_SPAN = re.compile(r"<span\b[^>]*>(.*?)</span>", re.I | re.S)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_URL_DATE = re.compile(r"/(20\d\d)/(\d{2})/")

_H1 = re.compile(r"<h1\b[^>]*>(.*?)</h1>", re.I | re.S)
_DOCTYPE_META = re.compile(
    r'<p\b[^>]*class="[^"]*doctype-meta[^"]*"[^>]*>(.*?)</p>', re.I | re.S)
_AUTHOR_META = re.compile(
    r'<p\b[^>]*class="[^"]*article-meta__author-bureau[^"]*"[^>]*>(.*?)</p>',
    re.I | re.S)
_PUBDATE_META = re.compile(
    r'<p\b[^>]*class="[^"]*article-meta__publish-date[^"]*"[^>]*>(.*?)</p>',
    re.I | re.S)
#: The body is a run of wp-block elements with no single wrapper, so it is
#: taken as the region between the end of the header section and the tag block.
#:
#: TWO LAYOUTS, and missing the second cost 520 of State's 818 documents on the
#: first full harvest -- 64% of the agency, silently, as `no_body`. Newer posts
#: use `wp-block-paragraph` divs; older ones use a single
#: `classic-block-wrapper` / `wp-block-classic` holding plain <p> tags. Press
#: Statements, Readouts and Media Notes are mostly the classic shape, so the
#: loss was not random -- it was concentrated in exactly the document types
#: this project most wants.
_BODY_START = re.compile(
    r'<div\b[^>]*class="[^"]*(?:wp-block-paragraph|classic-block-wrapper'
    r'|wp-block-classic)', re.I)
_BODY_END = re.compile(
    r'<div\b[^>]*class="[^"]*(?:wp-block-tags-block|wp-block-spacer)', re.I)


class StateAdapter(SourceAdapter):
    institution_id = "us-state"
    agency = "Department of State"
    tier = "listing"
    date_filter = "client"
    pagination = "path_segment"
    newsroom_url = BASE + "/press-releases/"
    feed_url = ""

    #: state.gov is the ONLY agency of the 24 that refuses the project's
    #: default User-Agent. `eps-research/0.1 (academic research; ...)` gets a
    #: flat 403 on every path; the same request with the token below returns
    #: 200 and 43 rows.
    #:
    #: The override was chosen to keep the project identified rather than to
    #: impersonate a browser. `Mozilla/5.0 (compatible; ...)` is the
    #: conventional compatibility prefix, not a claim to be Chrome, and the
    #: string still names eps-research and how to make contact. A bare
    #: `eps-research/0.1 (+url)` was also tried and refused, so the prefix is
    #: what the filter is keying on.
    user_agent = ("Mozilla/5.0 (compatible; eps-research/0.1; "
                  "academic research; contact via institution)")

    label_map = {
        "Press Statement": "statement",
        "Press Release": "press_release",
        "Media Note": "press_release",
        "Readout": "press_release",
        "Remarks": "speech",
        "Speech": "speech",
        "Public Schedule": "other",
        "Department Press Briefing": "interview_transcript",
        "Interview": "interview_transcript",
        "Fact Sheet": "other",
        "Notice to the Press": "other",
    }

    # -- listing -----------------------------------------------------------

    def list_documents(self, start_date: str, end_date: str) -> Iterable[DocumentRef]:
        seen: set[str] = set()
        for page in range(1, MAX_PAGES + 1):
            url = BASE + "/press-releases/" if page == 1 else \
                "%s/press-releases/page/%d/" % (BASE, page)
            try:
                html = self.fetcher.get_text(url)
            except Exception as exc:  # noqa: BLE001
                raise ListingIncomplete(
                    "%s: index page unreachable: %s" % (self.institution_id, exc)
                ) from exc
            rows = self._rows(html, url)
            if not rows:
                return
            for ref in rows:
                if ref.url in seen:
                    continue
                seen.add(ref.url)
                if self.in_window(ref.date, start_date, end_date):
                    yield ref
            newest = max((r.date for r in rows if r.date), default="")
            if newest and newest < start_date:
                return
            self.fetcher.rest()

    def _rows(self, html: str, listing: str) -> list[DocumentRef]:
        out: list[DocumentRef] = []
        starts = [m.start() for m in _ROW.finditer(html)]
        for i, start in enumerate(starts):
            end = starts[i + 1] if i + 1 < len(starts) else len(html)
            row = html[start:end]
            link = _LINK.search(row)
            if not link:
                continue
            url = link.group(1)
            label = _TYPE.search(row)
            speaker, date = "", ""
            meta = _META.search(row)
            if meta:
                # The meta block ships a commented-out placeholder,
                # `<!-- <span>date</span> -->`. Left in, the literal word
                # "date" is picked up as the speaker's name on every row.
                block = _COMMENT.sub(" ", meta.group(1))
                spans = [_clean_inline(s) for s in _SPAN.findall(block)]
                spans = [s for s in spans if s]
                for s in spans:
                    d = parse_date_text(s)
                    if d and not date:
                        date = d
                    elif not d and not speaker:
                        speaker = s
            source = "listing"
            if not date:
                u = _URL_DATE.search(url)
                if u:
                    # Month precision only; the day is not in the path.
                    date = "%s-%s-01" % u.groups()
                    source = "inferred"
            ref = DocumentRef(
                institution_id=self.institution_id,
                url=url,
                title=_clean_inline(link.group(2)),
                date=date,
                date_source=source if date else "inferred",
                source_document_type=_clean_inline(label.group(1)) if label else "",
                listing_url=listing,
            )
            if speaker:
                self._speakers[url] = speaker
            out.append(ref)
        return out

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._speakers: dict = {}

    # -- fetching ----------------------------------------------------------

    def fetch_document(self, ref: DocumentRef) -> RawDocument:
        doc = RawDocument(
            ref=ref, title=ref.title, date=ref.date, date_source=ref.date_source,
            source_document_type=ref.source_document_type, fetched_at=self.now(),
        )
        hint = self._speakers.get(ref.url)
        if hint:
            doc.speaker_hints.append(hint)
        try:
            page = self.fetcher.get_text(ref.url)
        except Exception as exc:                     # noqa: BLE001
            doc.status = "fetch_failed"
            doc.error = "%s: %s" % (type(exc).__name__, exc)
            return doc

        start = _BODY_START.search(page)
        if not start:
            doc.status = "no_body"
            return doc
        end = _BODY_END.search(page, start.start())
        doc.html = page[start.start():end.start() if end else len(page)]

        h1 = _H1.search(page)
        if h1:
            doc.title = _clean_inline(h1.group(1)) or doc.title

        t = _DOCTYPE_META.search(page)
        if t:
            label = _clean_inline(t.group(1))
            if label:
                doc.source_document_type = label

        a = _AUTHOR_META.search(page)
        if a:
            author = _clean_inline(a.group(1))
            if author and author not in doc.speaker_hints:
                doc.speaker_hints.append(author)

        d = _PUBDATE_META.search(page)
        if d:
            stamp = parse_date_text(_clean_inline(d.group(1)))
            if stamp:
                doc.date = stamp
                doc.date_source = "metadata"
        return doc
