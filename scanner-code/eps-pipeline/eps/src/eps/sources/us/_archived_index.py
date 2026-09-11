"""Enumerate from archived captures of a listing; fetch every body live.

FIVE AGENCIES NEED THIS, FOR FOUR DIFFERENT REASONS
---------------------------------------------------
    us-epa       the listing is behind a human-verification step
    us-nsf       the listing pages over AJAX; `?page=N` is ignored
    us-justice   the listing returns an Akamai interstitial
    us-defense   the listing is Vue-rendered: 2 links live, 13 in the archive
    us-energy    the listing renders client-side; `?page=N` is ignored

They looked like five separate problems during the survey and were recorded as
such. They are one problem: **the index cannot be walked, but the documents can
be fetched.** Every one of these agencies serves individual document pages to
an ordinary TLS-impersonating client; only the page that lists them is out of
reach. And for every one, the Internet Archive holds server-rendered captures
of that listing -- 77 to 196 of them inside a seven-month window.

THE SPLIT, AND WHY IT KEEPS THE GUARANTEE
-----------------------------------------
    enumeration    <- archived captures of the listing
    document text  <- the live page, fetched now

Nothing archival reaches the corpus text. Every `.txt` is verbatim against the
page the agency publishes today, which is what anchor-phrase verification
(E-08) depends on. What comes from the archive is a list of URLs, and a URL is
not evidence about what was said.

WHAT IT COSTS, AND THE HONEST CAVEAT
------------------------------------
Coverage is the union of what the captures happened to show. For EPA that was
measured at 415-423 documents, about 86% of the window's business days. The
defect is not the shortfall: it is that **this route cannot say which documents
are missing**. Any corpus built this way has to carry that caveat per agency
rather than be presented as complete. See H-52 and H-74.

Paging the archive would close the gap and is not available: the Archive
captures page 1 of a listing many times and deeper pages almost never.

SUBCLASS CONTRACT
-----------------
Set `archive_url` (the CDX lookup pattern), `listing_url` (the URL to replay)
and `exact_suffix` (to reject `?page=` variants the prefix match returns), then
implement `_rows(html)` and `fetch_document(ref)`.
"""

from __future__ import annotations

import gzip
import json
import re
import time
import urllib.parse
import urllib.request
from typing import Iterable

from ..base import DocumentRef, ListingIncomplete, SourceAdapter

CDX = "https://web.archive.org/cdx/search/cdx"
REPLAY = "https://web.archive.org/web/%sid_/%s"
UA = "eps-research/0.1 (academic research; contact via institution)"


def archive_get(url: str, timeout: int = 120, retries: int = 4) -> str:
    """Fetch from web.archive.org, with retries.

    Deliberately not the adapter's `fetcher`. That one is configured for the
    agency -- impersonation, pacing, sometimes a browser -- and the Archive
    should see the project's own User-Agent instead.

    The retries are not decoration. The CDX API returns HTTP 504 under load
    often enough that a single attempt is not a fair test of whether an agency
    can be enumerated; without them a busy minute at the Archive is
    indistinguishable from an agency having no captures at all.
    """
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
            raw = urllib.request.urlopen(req, timeout=timeout).read()
            if raw[:2] == b"\x1f\x8b":               # gzip magic
                raw = gzip.decompress(raw)
            return raw.decode("utf-8", "replace")
        except Exception as exc:                     # noqa: BLE001
            last = exc
            if attempt < retries - 1:
                time.sleep(3 * (attempt + 1))
    raise last if last else RuntimeError("archive fetch failed: " + url)


class ArchivedIndexAdapter(SourceAdapter):
    """Listing from the Archive, documents from the live site."""

    tier = "listing"
    date_filter = "client"
    #: Not `page_param`. The walk is over captures, not over pages.
    pagination = "none"

    #: Set by the subclass.
    archive_url = ""            # CDX pattern, e.g. "justice.gov/news"
    listing_url = ""            # the URL to replay, e.g. "https://www.justice.gov/news"
    exact_suffix = ""           # path suffix a capture must end with
    max_snapshots = 250

    # -- enumeration -------------------------------------------------------

    def _snapshots(self, start_date: str, end_date: str) -> list:
        """Capture timestamps of the listing, one per day, inside the window."""
        q = {
            "url": self.archive_url,
            "output": "json",
            "fl": "timestamp,original",
            "filter": "statuscode:200",
            "collapse": "timestamp:8",              # one capture per day
            "from": start_date.replace("-", ""),
            "to": end_date.replace("-", ""),
            "limit": str(self.max_snapshots),
        }
        try:
            rows = json.loads(archive_get(CDX + "?" + urllib.parse.urlencode(q)))
        except Exception as exc:                     # noqa: BLE001
            raise ListingIncomplete(
                "%s: archived listing index unreachable: %s"
                % (self.institution_id, exc)) from exc
        suffix = (self.exact_suffix or "").rstrip("/")
        out = []
        for row in rows[1:]:
            original = row[1].rstrip("/")
            # The CDX prefix match also returns `?page=N` and deeper paths.
            if not suffix or original.endswith(suffix):
                out.append(row[0])
        return out

    def list_documents(self, start_date: str, end_date: str) -> Iterable[DocumentRef]:
        snapshots = self._snapshots(start_date, end_date)
        if not snapshots:
            raise ListingIncomplete(
                "%s: no archived captures of %s in %s..%s"
                % (self.institution_id, self.listing_url, start_date, end_date))
        seen: set[str] = set()
        for ts in snapshots:
            try:
                html = archive_get(REPLAY % (ts, self.listing_url))
            except Exception:                        # noqa: BLE001
                # One bad capture is not a reason to lose the other 190. This
                # route is a documented partial already; failing hard here
                # would replace a measured majority with nothing.
                continue
            for ref in self._rows(html):
                if ref.url in seen:
                    continue
                seen.add(ref.url)
                if self.in_window(ref.date, start_date, end_date):
                    yield ref
            self.fetcher.rest()

    def _rows(self, html: str) -> list:              # pragma: no cover
        raise NotImplementedError

    # -- shared row helper -------------------------------------------------

    @staticmethod
    def real_path(href: str, pattern: str) -> str:
        """Strip the Archive's rewriting from a captured link.

        A replayed page carries `/web/20260421.../https://www.epa.gov/news...`.
        `id_` replay avoids most of this, but not all captures are clean, so
        the real path is recovered by matching the agency's own shape.
        """
        m = re.search(pattern + r"$", href)
        return m.group(1) if m else href
