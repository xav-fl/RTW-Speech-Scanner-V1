"""Congressional hearings -- testimony the agencies do not publish themselves.

WHY THIS EXISTS, in one comparison. The eleven agency adapters together found
**15 testimony documents** in 2026-01-01..2026-07-31. GPO published **170
hearing transcripts** dated inside that same window, and 26 of them list a
witness whose title contains "Secretary". Agencies publish a fraction of their
head's testimony and there is no way to tell which fraction, so testimony
collected only from newsrooms is a biased sample of the most substantive
material this project has.

And it is substantive. The HUD oversight hearing of 2026-01-21
(CHRG-119hhrg63860) runs to 890 speaker turns across 46 people, of which
**389 turns and 13,502 words are Secretary Turner's own**. No press release in
the corpus carries anything close to that much of one officeholder's speech.

WHY THIS IS NOT A SourceAdapter
-------------------------------
`SourceAdapter` is one agency per class: `institution_id` is a class attribute
and the adapter walks that agency's newsroom. A hearing has no such owner. It
is published by Congress, and which agency it counts for is decided by *who
testified*. So the collector runs the join the other way round -- find the
hearing, read the witness list, match the witnesses against
`officeholders_2026.csv`, and emit one document per (hearing x matched
officeholder) with that officeholder's `institution_id`.

That also means a single hearing can legitimately produce two documents, if two
tracked officeholders appear on the same panel. They are separate rows because
they are separate speakers, and de-duplication is on (package_id, institution).

THREE THINGS TO KNOW BEFORE RUNNING IT
--------------------------------------
1. **Publication lag is real and must not be hidden.** Transcripts are printed
   months after the hearing. The window's monthly counts run 15, 17, 15, 14,
   15, 19, 5 -- July is not a quiet month, it is an incomplete one. A run today
   under-reports the end of any recent window, and re-running later will find
   more. `lag_warning()` returns the months at risk so the caller can record it
   rather than discover it in the data.

2. **Discovery needs an API key; content does not.** Searching govinfo requires
   an api.data.gov key, and the shared `DEMO_KEY` returns HTTP 429 after a
   handful of requests -- it is fine for a smoke test and useless for a run.
   Set `GOVINFO_API_KEY`. Transcripts and MODS come from the public content
   service with no key at all, so the expensive half of the work is unmetered.

3. **The transcript is kept whole.** Every turn becomes a block, including the
   committee's. Only the officeholder's turns are `quote` blocks with a
   speaker; everyone else's are `text` with none, so a member's question can
   never be attributed to the witness. That keeps the document verifiable
   against the published page, which anchor-phrase verification (E-08) needs.
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Iterable, Iterator, Optional

from .base import Fetcher, ListingIncomplete
from .blocks import Block, hearing_blocks, names_match, split_hearing_turns
from .text import _clean_inline

API = "https://api.govinfo.gov"
CONTENT = "https://www.govinfo.gov"

#: api.data.gov key. DEMO_KEY works for a smoke test and 429s almost at once.
API_KEY = os.environ.get("GOVINFO_API_KEY", "DEMO_KEY")

_WITNESS = re.compile(r"<witness>(.*?)</witness>", re.I | re.S)
_HELD = re.compile(r"<heldDate>(\d{4}-\d{2}-\d{2})</heldDate>", re.I)
_COMMITTEE = re.compile(
    r"<congCommittee[^>]*>.*?<name[^>]*type=\"authority-standard\"[^>]*>"
    r"(.*?)</name>", re.I | re.S)
_CHAMBER = re.compile(r"<chamber>(.*?)</chamber>", re.I)
_TITLE = re.compile(r"<searchTitle>(.*?)</searchTitle>", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")


@dataclass
class HearingRef:
    """One published hearing transcript, before any body is fetched."""

    package_id: str
    date: str = ""                 # heldDate, ISO
    title: str = ""
    committee: str = ""
    chamber: str = ""
    witnesses: list = field(default_factory=list)

    @property
    def url(self) -> str:
        return "%s/app/details/%s" % (CONTENT, self.package_id)

    @property
    def text_url(self) -> str:
        return "%s/content/pkg/%s/html/%s.htm" % (
            CONTENT, self.package_id, self.package_id)

    @property
    def mods_url(self) -> str:
        return "%s/metadata/pkg/%s/mods.xml" % (CONTENT, self.package_id)


@dataclass
class HearingDocument:
    """One officeholder's participation in one hearing."""

    ref: HearingRef
    institution_id: str
    officeholder: str
    witness_as_printed: str
    blocks: list = field(default_factory=list)
    text: str = ""
    turns: int = 0
    words: int = 0
    status: str = "ok"
    error: str = ""

    #: Always `testimony`. A hearing is not one of the ambiguous cases -- the
    #: source document type is settled by what the document is.
    normalised_document_type: str = "testimony"
    source_document_type: str = "Congressional Hearing"
    date_source: str = "metadata"


def _text_of(fragment: str) -> str:
    return _clean_inline(_TAG.sub(" ", fragment or ""))


def witness_name(line: str) -> str:
    """The personal name from a MODS witness line.

    GPO prints a witness as name-first, then office, then organisation:

        Hon. Scott Turner, Secretary, Department of Housing and Urban Development

    Only the first comma-clause is the person. Passing the whole line to
    `names_match` fails, and fails silently: `name_tokens` reads "Housing",
    "Urban" and "Development" as forenames, so the token sets conflict and a
    correct witness is rejected. That is how the first run of this collector
    produced zero documents from a hearing whose only witness was a tracked
    Secretary.
    """
    return (line or "").split(",")[0].strip()


def _field(row: dict, *names: str) -> str:
    """First non-empty value among `names`.

    Two officeholder files are in play and they do not agree on column names.
    `harvest-code/officeholders_2026.csv`, which H-43 made authoritative, uses
    `institution_id` and `officeholder`; `src/eps/reference/officeholders.csv`
    uses `institution` and `person`. Reading either is a two-line accessor and
    saves the caller from having to know which file it was handed.
    """
    for n in names:
        v = (row.get(n) or "").strip()
        if v:
            return v
    return ""


class CongressionalHearings:
    """Collector for GPO hearing transcripts. Not a `SourceAdapter`."""

    def __init__(self, fetcher: Optional[Fetcher] = None,
                 api_key: str = API_KEY):
        self.fetcher = fetcher or Fetcher()
        self.api_key = api_key
        #: Package ids whose MODS named a witness that matched nobody. Kept so
        #: the review gate can see who was passed over rather than guessing.
        self.unmatched_witnesses: dict = {}

    # -- discovery ---------------------------------------------------------

    def list_hearings(self, start_date: str, end_date: str,
                      page_size: int = 100) -> Iterator[HearingRef]:
        """Published hearing transcripts whose HEARING date is in the window.

        `/published` filters on `dateIssued`, which for CHRG is the date the
        hearing was held -- not the date the transcript was printed. That is the
        date this project wants, and it is why the collection endpoint is used
        rather than `/collections`, which filters on last-modified and returns
        packages from 2024 for a 2026 query.
        """
        offset = 0
        while True:
            url = ("%s/published/%s/%s?offset=%d&pageSize=%d&collection=CHRG"
                   "&api_key=%s" % (API, start_date, end_date, offset,
                                    page_size, self.api_key))
            try:
                page = self.fetcher.get_json(url)
            except Exception as exc:                 # noqa: BLE001
                raise ListingIncomplete(
                    "congress: hearing index unreachable at offset %d: %s "
                    "(set GOVINFO_API_KEY; DEMO_KEY is rate limited)"
                    % (offset, exc)) from exc
            packages = page.get("packages") or []
            if not packages:
                return
            for p in packages:
                pid = p.get("packageId") or ""
                if pid:
                    yield HearingRef(
                        package_id=pid,
                        date=(p.get("dateIssued") or "")[:10],
                        title=_clean_inline(p.get("title") or ""),
                    )
            offset += len(packages)
            if offset >= int(page.get("count") or 0):
                return
            self.fetcher.rest()

    # -- metadata ----------------------------------------------------------

    def load_metadata(self, ref: HearingRef) -> HearingRef:
        """Fill witnesses, committee and chamber from MODS. No API key needed."""
        try:
            mods = self.fetcher.get_text(ref.mods_url)
        except Exception:
            return ref
        ref.witnesses = [_text_of(w) for w in _WITNESS.findall(mods)]
        held = _HELD.search(mods)
        if held:
            ref.date = held.group(1)
        com = _COMMITTEE.search(mods)
        if com:
            ref.committee = _text_of(com.group(1))
        cham = _CHAMBER.search(mods)
        if cham:
            ref.chamber = _text_of(cham.group(1))
        if not ref.title:
            t = _TITLE.search(mods)
            if t:
                ref.title = _text_of(t.group(1))
        return ref

    # -- the join ----------------------------------------------------------

    def match_officeholders(self, ref: HearingRef, officeholders: list) -> list:
        """`[(institution_id, person, witness_as_printed)]` for this hearing.

        `officeholders` is the parsed `officeholders_2026.csv`: dicts carrying
        at least `institution`, `person`, `start_date`, `end_date`.

        A witness line reads "Hon. Scott Turner, Secretary, Department of
        Housing and Urban Development". Comparison is by `names_match`, the
        same surname-plus-no-forename-conflict rule used everywhere else, so
        the office words in the line do not have to be stripped first.

        Tenure is checked against the hearing date, so a predecessor who
        testified in January is not credited to the successor who took office
        in April.
        """
        out = []
        seen = set()
        for line in ref.witnesses:
            hit = False
            for row in officeholders:
                person = _field(row, "officeholder", "person")
                inst = _field(row, "institution_id", "institution")
                if not person or not inst:
                    continue
                if not self._in_tenure(row, ref.date):
                    continue
                if (names_match(witness_name(line), person)
                        and (inst, person) not in seen):
                    seen.add((inst, person))
                    out.append((inst, person, line))
                    hit = True
            if not hit and line:
                self.unmatched_witnesses[line] = \
                    self.unmatched_witnesses.get(line, 0) + 1
        return out

    @staticmethod
    def _in_tenure(row: dict, date: str) -> bool:
        """End date inclusive, matching H-14 and `harvest_us.eligible_on()`."""
        if not date:
            return True                 # undated: do not guess it away
        start = (row.get("start_date") or "").strip()
        end = (row.get("end_date") or "").strip()
        if start and date < start:
            return False
        if end and date > end:
            return False
        return True

    # -- the document ------------------------------------------------------

    def fetch_documents(self, ref: HearingRef,
                        officeholders: list) -> list:
        """Zero or more `HearingDocument`s for one hearing.

        Zero is the normal case: most hearings have no tracked officeholder on
        the panel, and that is not a fault.
        """
        matches = self.match_officeholders(ref, officeholders)
        if not matches:
            return []
        try:
            html = self.fetcher.get_text(ref.text_url)
        except Exception as exc:                     # noqa: BLE001
            return [HearingDocument(
                ref=ref, institution_id=inst, officeholder=person,
                witness_as_printed=line, status="fetch_failed",
                error="%s: %s" % (type(exc).__name__, exc))
                for inst, person, line in matches]

        body = _TAG.sub("", html)
        out = []
        for inst, person, line in matches:
            blocks = hearing_blocks(body, person)
            mine = [b for b in blocks if b.kind == "quote"]
            doc = HearingDocument(
                ref=ref, institution_id=inst, officeholder=person,
                witness_as_printed=line, blocks=blocks, text=body,
                turns=len(mine),
                words=sum(len(b.text.split()) for b in mine),
            )
            if not mine:
                # Named as a witness but no turn carries their name. Real
                # cause: the witness withdrew, or the transcript prints them
                # under a title the name rule does not reach. Recorded, not
                # dropped -- an empty testimony row is a finding.
                doc.status = "no_turns_attributed"
            out.append(doc)
        return out

    # -- honesty about coverage -------------------------------------------

    @staticmethod
    def lag_warning(by_month: dict, threshold: float = 0.6) -> list:
        """Months whose count is far below the window's median.

        Hearing transcripts appear months after the hearing, so the tail of any
        recent window is incomplete by construction. This turns that into a
        list the caller can put in the gate report instead of a surprise in the
        data.
        """
        if not by_month:
            return []
        counts = sorted(by_month.values())
        mid = counts[len(counts) // 2]
        if not mid:
            return []
        return sorted(m for m, n in by_month.items() if n < mid * threshold)
