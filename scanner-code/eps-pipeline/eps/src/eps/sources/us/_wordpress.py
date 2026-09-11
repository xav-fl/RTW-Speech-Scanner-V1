"""Shared base for agencies running an open WordPress REST API.

Two agencies qualify -- NASA and VA -- and they differ only in host name and
post type, so the collection logic lives here once rather than twice.

Why this is `tier: feed` and not a paginated listing: the API honours a date
window server-side. `?after=...&before=...` cuts NASA's press-release type from
9,287 items to the 153 published in the window, and VA's from 4,492 to 46, both
returned in date order. That was verified with a control query rather than
assumed, and the verification is the point of this docstring.

The control query matters because a WordPress API answering HTTP 200 is not
evidence that it filtered anything. State.gov runs WordPress too, answers
`/wp-json/wp/v2/state_press_release` with 200, and returns the same newest ten
rows whatever `after`, `before`, `page`, `per_page` or `orderby` are sent,
because its CDN strips the query string. Taken at face value that API would
have produced a ten-document corpus with no error anywhere. So this class
re-checks at run time: `_verify_window()` asks the API for one item outside the
requested window and refuses to collect if it comes back, rather than silently
harvesting whatever the newest page happens to hold.
"""

from __future__ import annotations

import json
import urllib.parse
from typing import Iterable

from ..base import DocumentRef, RawDocument, SourceAdapter
from ..text import _clean_inline


class WordPressWindowError(RuntimeError):
    """The REST API accepted a date window and then ignored it."""


class WordPressAdapter(SourceAdapter):
    """Collect from `/wp-json/wp/v2/<post_type>` with a server-side window."""

    tier = "feed"
    date_filter = "server"
    pagination = "offset"

    #: Set by the subclass.
    base_url = ""
    post_type = ""
    #: Fields worth asking for. `_fields` keeps the payload small, which
    #: matters when a run pages through hundreds of items.
    list_fields = "id,date,link,title,type"
    per_page = 100
    #: Runaway guard. At 100 an item a page this is 5,000 documents.
    max_pages = 50

    # -- helpers -----------------------------------------------------------

    def _endpoint(self, **params) -> str:
        q = urllib.parse.urlencode(params)
        return "%s/wp-json/wp/v2/%s?%s" % (self.base_url, self.post_type, q)

    def _window(self, start_date: str, end_date: str) -> dict:
        # `before` is exclusive of the instant, not the day, so it is pushed to
        # the end of `end_date` to keep the window inclusive at both ends --
        # the same convention the UK harvest uses for tenure dates (H-14).
        return {"after": start_date + "T00:00:00",
                "before": end_date + "T23:59:59"}

    def _verify_window(self, start_date: str, end_date: str) -> None:
        """Refuse to collect from an API that ignores its own date filter.

        Asks for a single item dated strictly before the window. An API that
        filters returns nothing; one that discards the query string returns its
        newest item, which is inside the window and therefore proof the filter
        did not run.
        """
        url = self._endpoint(before=start_date + "T00:00:00", per_page=1,
                             _fields="date", orderby="date", order="desc")
        try:
            data = self.fetcher.get_json(url)
        except Exception:
            # A failure here is a network problem, not evidence of anything.
            return
        if not isinstance(data, list) or not data:
            return                      # filtered correctly: nothing older
        got = (data[0].get("date") or "")[:10]
        if got and got >= start_date:
            raise WordPressWindowError(
                "%s ignored `before=%s` and returned an item dated %s; the "
                "query string is probably being stripped by a CDN, so paging "
                "would silently collect only the newest page"
                % (self.institution_id, start_date, got))

    # -- listing -----------------------------------------------------------

    def list_documents(self, start_date: str, end_date: str) -> Iterable[DocumentRef]:
        self._verify_window(start_date, end_date)
        win = self._window(start_date, end_date)
        for page in range(1, self.max_pages + 1):
            url = self._endpoint(per_page=self.per_page, page=page,
                                 orderby="date", order="asc",
                                 _fields=self.list_fields, **win)
            try:
                items = self.fetcher.get_json(url)
            except Exception:
                # WordPress answers 400 past the last page rather than [].
                return
            if not isinstance(items, list) or not items:
                return
            for item in items:
                ref = self._ref(item)
                if ref is not None:
                    yield ref
            if len(items) < self.per_page:
                return
            self.fetcher.rest()

    def _ref(self, item: dict):
        link = item.get("link") or ""
        if not link:
            return None
        self._remember(item)
        title = (item.get("title") or {})
        return DocumentRef(
            institution_id=self.institution_id,
            url=link,
            title=_clean_inline(title.get("rendered") or ""),
            date=(item.get("date") or "")[:10],
            date_source="listing",
            source_document_type=item.get("type") or self.post_type,
            listing_url=self.newsroom_url,
        )

    # -- fetching ----------------------------------------------------------

    def fetch_document(self, ref: DocumentRef) -> RawDocument:
        """Take the body from the API, not from the rendered page.

        `content.rendered` is the article body without the site chrome, which
        is exactly what `slice_element` has to reconstruct by hand on the HTML
        agencies. Asking the API for it is both cheaper and less fragile, and
        it is the same bytes the page renders.
        """
        doc = RawDocument(
            ref=ref, title=ref.title, date=ref.date, date_source=ref.date_source,
            source_document_type=ref.source_document_type, fetched_at=self.now(),
        )
        url = "%s/wp-json/wp/v2/%s?%s" % (
            self.base_url, self.post_type,
            urllib.parse.urlencode({"include": self._post_id(ref),
                                    "_fields": "id,date,title,content,link,type"})
        ) if self._post_id(ref) else ""
        try:
            data = self.fetcher.get_json(url) if url else None
            if not data:
                raise ValueError("post id not resolvable from " + ref.url)
            item = data[0] if isinstance(data, list) else data
        except Exception as exc:                     # noqa: BLE001
            doc.status = "fetch_failed"
            doc.error = "%s: %s" % (type(exc).__name__, exc)
            return doc

        body = ((item.get("content") or {}).get("rendered") or "")
        if not body.strip():
            doc.status = "no_body"
            return doc
        doc.html = body

        title = ((item.get("title") or {}).get("rendered") or "")
        if title:
            doc.title = _clean_inline(title)
        stamp = (item.get("date") or "")[:10]
        if stamp:
            doc.date = stamp
            doc.date_source = "metadata"
        return doc

    # -- id resolution -----------------------------------------------------

    def _post_id(self, ref: DocumentRef) -> str:
        """The numeric post id for a document URL.

        Cached from the listing pass where there was one, and otherwise looked
        up by slug. The fallback is not an optimisation, it is a correctness
        fix: without it `fetch_document` silently depends on `list_documents`
        having run first in the same process, and every caller that rebuilds a
        ref from the screening log gets nothing.

        The audit is exactly such a caller, and it found this -- NASA reported
        `0/0 documents` while the other agencies reported `0/8`, because every
        refetch failed with "post id not resolvable". A re-run, a repair pass
        or any downstream tool would have hit the same wall.
        """
        cached = self._ids.get(ref.url, "")
        if cached:
            return cached
        slug = urllib.parse.urlsplit(ref.url).path.rstrip("/").rsplit("/", 1)[-1]
        if not slug:
            return ""
        try:
            data = self.fetcher.get_json(self._endpoint(
                slug=slug, _fields="id,link", per_page=1))
        except Exception:                            # noqa: BLE001
            return ""
        if isinstance(data, list) and data and data[0].get("id"):
            found = str(data[0]["id"])
            self._ids[ref.url] = found
            return found
        return ""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._ids: dict = {}

    def _remember(self, item: dict) -> None:
        link = item.get("link") or ""
        if link and item.get("id"):
            self._ids[link] = str(item["id"])
