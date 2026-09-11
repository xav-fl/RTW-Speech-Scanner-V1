"""The contract every agency fetcher satisfies.

Two methods, kept separate on purpose. Most US agencies publish far more than
UK departments do -- DoD, HHS and DOJ can each publish thousands of items in
seven months -- so listing must be cheap and must never pull document bodies.
Filter by date at the index stage wherever the site allows it; fall back to
fetch-then-filter only where it does not.

Every adapter also reports HOW it obtained the publication date. Several US
sites carry no machine-readable date at all, and a date read from prose is not
the same evidence as a date read from a <time> element. That difference has to
survive into the log, so it is a field on the record rather than a comment.

Standard library only, matching the standalone UK harvester.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Optional

#: Where a publication date came from, strongest evidence first.
#:   metadata  -- a machine-readable field on the document itself
#:                (<time datetime=...>, a data- attribute, a meta tag)
#:   listing   -- a machine-readable field on the index that led to it
#:   body      -- parsed out of the document's prose
#:   inferred  -- neither; derived from a URL, a filename or a neighbour
DATE_SOURCES = ("metadata", "listing", "body", "inferred")

#: The eight normalised labels. Same closed list the UK side uses.
NORMALISED_TYPES = (
    "speech",
    "statement",
    "press_release",
    "testimony",
    "letter",
    "op_ed",
    "interview_transcript",
    "other",
)

USER_AGENT = "eps-research/0.1 (academic research; contact via institution)"

#: Titles that announce congressional testimony, wherever the agency filed it.
#:
#: Applied to EVERY adapter, because agencies routinely file testimony under a
#: general heading and Section 7 of the brief is explicit that it must not be
#: folded into `statement` or `speech`. Treasury's window contains five items
#: titled "Statement from Secretary ... Before the United States Senate Finance
#: Committee" filed under Statements & Remarks, and Education's contains
#: "Secretary McMahon Testifies on ... Budget Request" filed under Speech.
#:
#: "Before the ..." on its own is far too loose to use: it is also Treasury's
#: normal phrasing for an audience -- before the Petroleum Club of Houston,
#: before the EXIM Annual Conference, before the Financial Literacy and
#: Education Commission. A congressional body has to be named.
_TESTIMONY_TITLE = re.compile(
    r"\btestimony\b|\btestif(?:ies|ied|y|ying)\b"
    r"|\bbefore the\b[^,;:]{0,60}?\b(?:Committee|Subcommittee)\b"
    r"|\bbefore the\b[^,;:]{0,60}?\bUnited States (?:Senate|House)\b",
    re.I,
)


def looks_like_testimony(title: str) -> bool:
    return bool(_TESTIMONY_TITLE.search(title or ""))


class ListingIncomplete(RuntimeError):
    """An index walk stopped early because a page could not be fetched.

    Raised rather than returning what was collected so far. `harvest_us.py`
    logs a raised listing as `listing_unreachable`, which is a different row
    from `no_documents_in_window`, and Section 5 of the RA guide requires those
    two to stay distinguishable.

    The failure mode this exists for is real and was hit while writing the
    State adapter: state.gov needs roughly forty pages to reach the far end of
    a seven-month window, and a transient failure on page two returned an empty
    list that looked exactly like an agency with nothing to report. `Fetcher`
    already retries four times with exponential backoff, so reaching this means
    the page is persistently unavailable, not briefly slow.
    """



@dataclass(frozen=True)
class DocumentRef:
    """One item seen on an index page. No body has been fetched yet."""

    institution_id: str
    url: str
    title: str = ""
    date: str = ""                    # ISO yyyy-mm-dd, or "" if the index had none
    date_source: str = "inferred"     # one of DATE_SOURCES
    source_document_type: str = ""    # the agency's own label, verbatim
    listing_url: str = ""             # the index this came off, for the audit trail


@dataclass
class RawDocument:
    """One document as fetched. HTML plus whatever metadata the page carries."""

    ref: DocumentRef
    html: str = ""                    # body HTML only, not the whole page
    title: str = ""
    date: str = ""
    date_source: str = "inferred"
    source_document_type: str = ""
    speaker_hints: list[str] = field(default_factory=list)
    fetched_at: str = ""
    status: str = "ok"                # ok | fetch_failed | no_body
    error: str = ""


# --------------------------------------------------------------------------
# Small HTML helpers
# --------------------------------------------------------------------------
# Deliberately not a parser. The two reference agencies both serve minified
# HTML with unquoted attribute values, which several tolerant parsers mangle,
# and adding lxml would put the standalone collector behind a build step the UK
# harvester never needed. What is needed is "give me this one element", which
# a depth counter does correctly as long as the tag name is matched exactly.


def slice_element(html: str, opener: "re.Pattern", tag: str = "div") -> str:
    """Return the outer HTML of the first element `opener` matches.

    `opener` must match that element's opening tag. Nested elements of the same
    tag are counted so the slice ends at the right close.
    """
    m = opener.search(html or "")
    if not m:
        return ""
    start = m.start()
    depth = 0
    pattern = re.compile(r"</?" + tag + r"\b[^>]*>", re.I)
    for t in pattern.finditer(html, start):
        depth += -1 if t.group(0).startswith("</") else 1
        if depth == 0:
            return html[start:t.end()]
    return html[start:]


def attr(tag_html: str, name: str) -> str:
    """Read one attribute out of an opening tag, quoted or not."""
    m = re.search(
        name + r"\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))",
        tag_html or "", re.I,
    )
    if not m:
        return ""
    return (m.group(1) or m.group(2) or m.group(3) or "").strip()


def first_datetime(html: str) -> str:
    """The first <time datetime=...> value on the page, as ISO yyyy-mm-dd."""
    m = re.search(r"<time\b[^>]*>", html or "", re.I)
    if not m:
        return ""
    return attr(m.group(0), "datetime")[:10]


#: Month names as US agencies write them, including the AP abbreviations.
#:
#: AP style is not optional here. Defense/War writes "Sept. 3, 2026" and
#: "Aug. 31, 2026" and carries no <time> element anywhere, so an adapter that
#: only understood full month names would date every Defense document as empty.
#: AP abbreviates all months except March, April, May, June and July, and uses
#: "Sept." rather than the three-letter "Sep.", so both spellings are accepted.
_MONTHS = {}
for _i, _full in enumerate(
        ["January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"], start=1):
    _MONTHS[_full.lower()] = _i
    _MONTHS[_full[:3].lower()] = _i
_MONTHS["sept"] = 9

_DATE_TEXT = re.compile(
    r"\b([A-Z][a-z]{2,8})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d\d)\b")
_DATE_SLASH = re.compile(r"\b(\d{1,2})/(\d{1,2})/(20\d\d)\b")
_DATE_ISO = re.compile(r"\b(20\d\d)-(\d{2})-(\d{2})\b")


def parse_date_text(text: str) -> str:
    """Best ISO date from a fragment of prose or markup, or "".

    Four formats, because the survey found all four in agency listings and no
    adapter should have to re-derive them:

        September 4, 2026   Education, HHS, OPM, SSA, NRC, State
        Sept. 4, 2026       Defense/War, AP style throughout
        09/04/2026          Interior, GSA
        2026-09-04          anything emitting ISO directly

    ISO is tried first because a page carrying both usually has the machine
    value in an attribute and the human value in prose; the machine one wins.
    Slash dates are read US-style, month first, which is what every agency
    using that format means by it.
    """
    if not text:
        return ""
    m = _DATE_ISO.search(text)
    if m:
        return "%s-%s-%s" % m.groups()
    m = _DATE_TEXT.search(text)
    if m:
        mon = _MONTHS.get(m.group(1).lower())
        if mon:
            return "%s-%02d-%02d" % (m.group(3), mon, int(m.group(2)))
    m = _DATE_SLASH.search(text)
    if m:
        mon, day, year = int(m.group(1)), int(m.group(2)), m.group(3)
        if 1 <= mon <= 12 and 1 <= day <= 31:
            return "%s-%02d-%02d" % (year, mon, day)
    return ""


class Fetcher:
    """Polite HTTP with retries. Shared so 24 adapters cannot each get it wrong."""

    def __init__(self, pause: float = 0.4, retries: int = 4, timeout: int = 45,
                 user_agent: Optional[str] = None):
        self.pause = pause
        self.retries = retries
        self.timeout = timeout
        self.user_agent = user_agent or USER_AGENT
        self.calls = 0

    def get_bytes(self, url: str, params: Optional[dict] = None) -> bytes:
        if params:
            url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        last: Optional[Exception] = None
        for attempt in range(self.retries):
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": self.user_agent})
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    self.calls += 1
                    return resp.read()
            except urllib.error.HTTPError as exc:
                # A 404 will not become a 200 on retry; stop paying for it.
                if exc.code in (404, 410):
                    raise
                last = exc
            except Exception as exc:            # noqa: BLE001 - network is broad
                last = exc
            if attempt < self.retries - 1:
                time.sleep(2 ** attempt)
        raise last if last else RuntimeError("fetch failed: " + url)

    def get_text(self, url: str, params: Optional[dict] = None) -> str:
        return self.get_bytes(url, params).decode("utf-8", "replace")

    def get_json(self, url: str, params: Optional[dict] = None):
        return json.loads(self.get_bytes(url, params))

    def rest(self) -> None:
        time.sleep(self.pause)


class SourceAdapter(ABC):
    """One agency. Subclasses fill in the class attributes and the two methods."""

    institution_id: str = ""
    agency: str = ""
    tier: str = "unknown"             # feed | listing | awkward | unknown
    date_filter: str = "unknown"      # server | client | unknown
    pagination: str = "unknown"       # page_param | offset | infinite | unknown
    newsroom_url: str = ""
    feed_url: str = ""
    label_map: dict = {}              # source label -> normalised type

    #: Per-agency User-Agent override. Empty means use the project default.
    #:
    #: Set this ONLY for an agency that refuses the default, and say why in the
    #: adapter's docstring. The default identifies the project on purpose and is
    #: not to be swapped for a browser string as a matter of course: an override
    #: must still name `eps-research` and still be honest about what it is.
    #: State is the only agency of the 24 that needs one.
    user_agent: str = ""

    def __init__(self, fetcher: Optional[Fetcher] = None,
                 label_map: Optional[dict] = None):
        self.fetcher = fetcher or Fetcher()
        if self.user_agent and self.fetcher.user_agent != self.user_agent:
            # A private Fetcher rather than mutating the shared one, so one
            # agency's override cannot leak into the other 23.
            self.fetcher = Fetcher(
                pause=self.fetcher.pause, retries=self.fetcher.retries,
                timeout=self.fetcher.timeout, user_agent=self.user_agent)
        if label_map:
            self.label_map = dict(label_map)
        #: Source labels met during a run that `label_map` had no entry for.
        #: Reported at the review gate rather than swallowed, because an
        #: unmapped label silently becomes `other` and disappears.
        self.unknown_labels: dict = {}

    # -- the contract ------------------------------------------------------

    @abstractmethod
    def list_documents(self, start_date: str, end_date: str) -> Iterable[DocumentRef]:
        """Index pages only. Must not fetch document bodies."""

    @abstractmethod
    def fetch_document(self, ref: DocumentRef) -> RawDocument:
        """One document. Returns HTML plus whatever metadata the page carries."""

    # -- shared behaviour --------------------------------------------------

    def normalise_type(self, source_label: str, title: str = "") -> str:
        """Map the agency's own label onto the eight normalised labels.

        An unmapped label becomes `other` AND is recorded, so the review gate
        can list every label the map did not cover. US agencies each use their
        own vocabulary -- Remarks, Readout, Fact Sheet, Statement, Testimony --
        so one global mapping was never going to work and the misses have to be
        visible.
        """
        key = (source_label or "").strip()
        mapped = self.label_map.get(key)
        if mapped is None:
            mapped = self.label_map.get(key.lower())
        if mapped is None:
            if key:
                self.unknown_labels[key] = self.unknown_labels.get(key, 0) + 1
            mapped = "other"
        else:
            mapped = self.refine_type(mapped, key, title)
        # Testimony overrides whatever the heading said. An unmapped label is
        # still counted above first, so upgrading it here does not hide the
        # gap in `label_map`.
        if mapped != "testimony" and looks_like_testimony(title):
            return "testimony"
        return mapped

    def refine_type(self, mapped: str, source_label: str, title: str) -> str:
        """Hook for agencies whose own label covers two normalised types.

        Default is identity. Overriding it is only legitimate when the source
        label is genuinely ambiguous; the raw label is kept in
        `source_document_type` either way, so any refinement is reversible
        without re-harvesting.
        """
        return mapped

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def in_window(date_iso: str, start_date: str, end_date: str) -> bool:
        """Undated documents are kept. Dropping them would hide the gap."""
        if not date_iso:
            return True
        return start_date <= date_iso <= end_date
