"""Labor -- filter by URL path, because the agency facet does not work.

The survey recorded `?agency=osec` as a server-side filter isolating the Office
of the Secretary. It is not: requesting it returns a page with **zero** release
links, while the unfiltered listing returns twenty. `osec` is a path segment on
the document URL, not a valid value for that query parameter, and an adapter
built on the survey note would have collected nothing while looking healthy.

So the listing is walked unfiltered and the sub-agency is read from the URL:

    /newsroom/releases/osec/osec20260904     Office of the Secretary
    /newsroom/releases/whd/whd20260903       Wage and Hour Division
    /newsroom/releases/osha/osha20260826     OSHA

`OFFICE_OF_THE_SECRETARY_ONLY` decides whether the sub-agencies are collected.
It defaults to False -- everything is collected, with the sub-agency recorded in
`source_document_type` -- because H-34's rule is to record and let the scope
decision be made downstream where it stays reversible.

The date is in the document slug (`osec20260904`), which is the only date the
index offers: these rows carry no `<time>` element and no printed date.
"""

from __future__ import annotations

import re
from typing import Iterable

from ..base import (DocumentRef, ListingIncomplete, RawDocument, SourceAdapter,
                    parse_date_text, slice_element)
from ..text import _clean_inline

BASE = "https://www.dol.gov"
LISTING = BASE + "/newsroom/releases"
MAX_PAGES = 80

#: Collect only the Secretary's own office. False keeps everything, labelled.
OFFICE_OF_THE_SECRETARY_ONLY = False

#: NOTE the `\s*` inside the quotes. DOL emits `href=" /newsroom/releases/dol/
#: dol20260907 "` -- with a leading AND trailing space inside the attribute.
#: A pattern anchored on `href="/` matches nothing at all on this site, which
#: is why the first version of this adapter reported zero documents for an
#: agency publishing twenty to a page.
_LINK = re.compile(
    r'<a\b[^>]*href="\s*(/newsroom/releases/([a-z]+)/[a-z]+(20\d{6})[^"\s]*)\s*"'
    r'[^>]*>(.*?)</a>', re.I | re.S)

#: The printed date on the row. Preferred over the slug: it is what the agency
#: published, and the slug is only a filename convention.
_ROW_DATE = re.compile(
    r'<p\b[^>]*class="[^"]*dol-date-text[^"]*"[^>]*>(.*?)</p>', re.I | re.S)
_ROW_BLOCK = re.compile(r'<div\b[^>]*class="[^"]*dol-feed-block', re.I)

#: DOL's own class, verified against fetched prose.
_BODY = re.compile(r'<div\b[^>]*class="[^"]*field--name-field-press-body', re.I)
_MAIN = re.compile(r"<h1\b", re.I)
_H1 = re.compile(r"<h1\b[^>]*>(.*?)</h1>", re.I | re.S)
_TIME = re.compile(r'<time\b[^>]*datetime="([^"]{10})', re.I)

#: Sub-agency code -> label. Every one of these publishes press releases; the
#: code is kept so a scope filter can be applied downstream (H-34, H-57).
#: Observed in a two-month sample: ETA, OSHA, WHD, EBSA, MSHA, OWCP, ILAB.
AGENCIES = {
    "osec": "Office of the Secretary",
    "dol": "Department of Labor",
    "eta": "ETA", "osha": "OSHA", "whd": "WHD", "ebsa": "EBSA",
    "msha": "MSHA", "owcp": "OWCP", "ilab": "ILAB", "ofccp": "OFCCP",
    "vets": "VETS", "odep": "ODEP", "oig": "OIG", "bls": "BLS",
}


class LaborAdapter(SourceAdapter):
    institution_id = "us-labor"
    agency = "Department of Labor"
    tier = "listing"
    date_filter = "client"
    pagination = "page_param"
    newsroom_url = LISTING
    feed_url = ""

    #: Every sub-agency emits press releases; the label records WHICH office,
    #: not a different document type. Leaving them unmapped typed 168 of 180
    #: documents as `other`.
    label_map = dict(
        {v: "press_release" for v in
         ("Office of the Secretary", "Department of Labor", "News Release")},
        **{c.upper(): "press_release" for c in
           ("eta", "osha", "whd", "ebsa", "msha", "owcp", "ilab", "ofccp",
            "vets", "odep", "oig", "bls")})

    def list_documents(self, start_date: str, end_date: str) -> Iterable[DocumentRef]:
        seen: set[str] = set()
        for page in range(MAX_PAGES):
            try:
                html = self.fetcher.get_text(LISTING, {"page": page})
            except Exception as exc:        # noqa: BLE001
                raise ListingIncomplete(
                    "%s: index page unreachable: %s"
                    % (self.institution_id, exc)) from exc
            rows = self._rows(html)
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

    def _rows(self, html: str) -> list:
        # Split into feed blocks so a row's printed date is paired with that
        # row's link rather than with whichever date appeared first.
        starts = [m.start() for m in _ROW_BLOCK.finditer(html)]
        if not starts:
            starts = [0]
        out = []
        seen = set()
        for i, start in enumerate(starts):
            end = starts[i + 1] if i + 1 < len(starts) else len(html)
            block = html[start:end]
            printed = _ROW_DATE.search(block)
            printed_date = parse_date_text(_clean_inline(printed.group(1))) \
                if printed else ""
            for m in _LINK.finditer(block):
                href, code, stamp, title = m.groups()
                if OFFICE_OF_THE_SECRETARY_ONLY and code != "osec":
                    continue
                if href in seen:
                    continue
                seen.add(href)
                if printed_date:
                    date, source = printed_date, "listing"
                else:
                    # osec20260904 -> 2026-09-04, from the filename.
                    date = "%s-%s-%s" % (stamp[:4], stamp[4:6], stamp[6:8])
                    source = "inferred"
                out.append(DocumentRef(
                    institution_id=self.institution_id,
                    url=BASE + href,
                    title=_clean_inline(title),
                    date=date,
                    date_source=source,
                    source_document_type=AGENCIES.get(code, code.upper()),
                    listing_url=LISTING,
                ))
        return out

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
            doc.date, doc.date_source = t.group(1), "metadata"
        elif not doc.date:
            # LAST RESORT ONLY, and never an override.
            #
            # The first date in a DOL release is usually a date the release
            # talks ABOUT -- when an inspection happened, when a court ruled,
            # when a fund was established -- not when it was published. Letting
            # it overwrite the date already carried on the ref moved 25 of 169
            # Labor documents out of the window entirely, one to 2010 and one
            # to 2026-12-31, each time disagreeing with the publication date in
            # the document's own URL slug.
            #
            # The ref always arrives dated: the listing row's printed date, or
            # the yyyymmdd in the slug. So this branch should never fire, and
            # if it does the result is the weakest evidence there is.
            d = parse_date_text(_clean_inline(body[:800]))
            if d:
                doc.date, doc.date_source = d, "body"
        return doc
