"""Validation and quote reconstruction.

The model never supplies quote text. It supplies unit IDs (and optionally a
sub-sentence anchor phrase). This module turns those into a quote by copying
from the frozen document, which makes the quote verbatim by construction. Every
other rule here is a deterministic check that fails closed.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Iterable, Optional

from .models import Document, Observation, Unit
from .normalise import SPEAKER_ONLY_TYPES
from .jel import JELTaxonomy


#: One character in, one character out, so an index found in the folded text is
#: an index into the original.
_TYPOGRAPHY = str.maketrans({
    "‘": "'", "’": "'", "‛": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "″": '"',
    "–": "-", "—": "-", " ": " ",
})


def _fold_for_search(text: str) -> str:
    """Typography- and case-insensitive copy of `text`, the same length."""
    folded = text.translate(_TYPOGRAPHY)
    lowered = folded.lower()
    # A handful of characters change length when lower-cased; skip case-folding
    # for those rather than let positions drift.
    return lowered if len(lowered) == len(folded) else folded


class RejectReason:
    UNKNOWN_UNIT = "unit_id not found in document"
    NON_CONTIGUOUS = "unit_ids are not contiguous"
    CROSS_PARAGRAPH = "unit_ids span a paragraph boundary"
    NOT_ATTRIBUTABLE = "passage is not attributable to the speaker"
    ANCHOR_NOT_FOUND = "anchor phrase does not appear exactly in the units"
    NO_UNITS = "no unit_ids supplied"
    TOO_LONG = "quote exceeds maximum length"
    TOO_SHORT = "quote is too short to carry a policy claim"
    BAD_JEL = "JEL classification failed validation"
    NO_ELIGIBLE_SPEAKER = (
        "no speaker: not in the officeholder table for this date, and no "
        "speaker_hint in the manifest"
    )
    AMBIGUOUS_SPEAKER = (
        "no speaker: the officeholder table matches more than one spell for "
        "this date"
    )
    DUPLICATE = "duplicate of an earlier observation"


# Defaults, overridable per call and from the CLI. The lower bound exists to
# catch fragments, not to filter policy content: real commitments are often
# short ("We will cap fees at 9,000 pounds."), so keep it low.
MAX_QUOTE_CHARS = 1200
MIN_QUOTE_CHARS = 25

# Double-quote characters only. Apostrophes are excluded deliberately: single
# quotes are ambiguous with possessives and contractions, and a mis-trim would
# silently corrupt the quote.
_OPEN_Q = '"\u201c'
_CLOSE_Q = '"\u201d'


def trim_to_quoted_span(text: str) -> str:
    """Return the material inside the outermost double quotes, if any.

    Used for document types that mix institutional prose with quoted remarks.
    Returns the input unchanged when there is no balanced pair, so the caller
    still gets a verbatim substring of the source either way.
    """
    start = next((i for i, c in enumerate(text) if c in _OPEN_Q), None)
    if start is None:
        return text
    end = next(
        (i for i in range(len(text) - 1, start, -1) if text[i] in _CLOSE_Q), None
    )
    if end is None or end <= start + 1:
        return text
    inner = text[start + 1:end].strip()
    return inner or text


def reconstruct_quote(
    doc: Document,
    unit_ids: list[str],
    anchor: Optional[str] = None,
    min_chars: int = MIN_QUOTE_CHARS,
    max_chars: int = MAX_QUOTE_CHARS,
) -> tuple[str, str]:
    """Return (quote, reject_reason). Quote is empty when rejected.

    Units must be contiguous and within one paragraph — the guide asks for a
    contiguous passage and prefers separate observations over ellipses.
    """
    if not unit_ids:
        return "", RejectReason.NO_UNITS

    umap = doc.unit_map()
    units: list[Unit] = []
    for uid in unit_ids:
        u = umap.get(uid)
        if u is None:
            return "", RejectReason.UNKNOWN_UNIT
        units.append(u)

    units.sort(key=lambda u: (u.para_idx, u.sent_idx))

    # A speech is the speaker's own words throughout, so a claim running across
    # consecutive short paragraphs is one passage and may be quoted as one. The
    # guide asks for meaningful paragraph boundaries to be preserved, which
    # presupposes a quote may contain one.
    #
    # Press releases keep the stricter rule. There, two consecutive paragraphs
    # can each carry a separate quoted remark, both attributable, and
    # trim_to_quoted_span() takes the OUTERMOST quote marks - so a joined span
    # would silently return  A." She added: "B  with the department's
    # attribution frame inside the quotation.
    allow_cross_para = doc.doc_type in SPEAKER_ONLY_TYPES

    if not allow_cross_para and len({u.para_idx for u in units}) > 1:
        return "", RejectReason.CROSS_PARAGRAPH

    # sent_idx restarts inside each paragraph, so "the next sentence" means
    # either the next sentence of this paragraph, or the first sentence of the
    # next paragraph when this unit was the last of its own. Bounds are taken
    # from the whole document so a skipped sentence cannot masquerade as a
    # paragraph break.
    _bounds: dict[int, tuple[int, int]] = {}
    for _u in doc.units:
        _lo, _hi = _bounds.get(_u.para_idx, (_u.sent_idx, _u.sent_idx))
        _bounds[_u.para_idx] = (min(_lo, _u.sent_idx), max(_hi, _u.sent_idx))

    for a, b in zip(units, units[1:]):
        same_para = b.para_idx == a.para_idx and b.sent_idx == a.sent_idx + 1
        next_para = (
            b.para_idx == a.para_idx + 1
            and a.sent_idx == _bounds.get(a.para_idx, (0, 0))[1]
            and b.sent_idx == _bounds.get(b.para_idx, (0, 0))[0]
        )
        if not (same_para or next_para):
            return "", RejectReason.NON_CONTIGUOUS

    if not all(u.attributable for u in units):
        return "", RejectReason.NOT_ATTRIBUTABLE

    # Copy the exact span from the frozen text rather than joining unit texts,
    # so original inter-sentence spacing is preserved verbatim.
    quote = doc.text[units[0].char_start:units[-1].char_end]

    # In a press release the selectable sentence usually carries an attribution
    # frame ('The Secretary of State said: "..."'). That frame is the
    # department's words, not the speaker's, so trim to the quoted span.
    if doc.doc_type not in SPEAKER_ONLY_TYPES:
        quote = trim_to_quoted_span(quote)

    if anchor:
        anchor_norm = anchor.strip()
        idx = quote.find(anchor_norm)
        if idx == -1:
            # The model retypes the anchor rather than copying it, and
            # typography does not survive retyping. In the pilot, six of seven
            # anchor rejections were a curly apostrophe typed straight
            # ("they’re" -> "they're") and the seventh a capital letter at the
            # start of the phrase: the right passage, thrown away. The search is
            # repeated on a folded copy -- same length, so positions carry over
            # -- and the quote is still sliced from the ORIGINAL text, so the
            # dataset keeps the document's own characters. A changed word
            # ("50 per cent" -> "50%") still fails.
            idx = _fold_for_search(quote).find(_fold_for_search(anchor_norm))
        if idx == -1:
            return "", RejectReason.ANCHOR_NOT_FOUND
        quote = quote[idx:idx + len(anchor_norm)]

    if len(quote) > max_chars:
        return "", RejectReason.TOO_LONG
    if len(quote) < min_chars:
        return "", RejectReason.TOO_SHORT

    return quote, ""


def verify_quote_in_source(doc: Document, quote: str) -> bool:
    """Belt-and-braces: confirm the reconstructed quote really is a substring
    of the frozen document text. Should never fail; assert it anyway."""
    return quote in doc.text


# --- speaker eligibility ---------------------------------------------------


SPEAKER_FROM_TABLE = "officeholder_table"
SPEAKER_FROM_MANIFEST = "manifest"


def resolve_speaker(
    doc: Document, officeholders: "OfficeholderTable"
) -> tuple[Optional[str], str, str]:
    """Work out who was speaking, and record how we know.

    Two sources, in order:

    1. The officeholder table, matched on (institution, date). This also acts as
       an eligibility check: no match means the document is out of scope.
    2. The `speaker_hint` you put in the manifest. Use this when you have chosen
       the documents by hand and already know who spoke — it saves building the
       table, at the cost of the eligibility check.

    Returns (speaker, source, warning). A warning is raised when both sources
    exist and disagree, which usually means a wrong date somewhere, and when
    the table matches more than one spell, in which case there is no speaker.
    """
    from_table, table_warning = officeholders.eligible_speaker(
        doc.institution, doc.pub_date
    )
    from_manifest = (doc.speaker_hint or "").strip() or None

    # An ambiguous table is not resolved by falling back to the manifest hint.
    # The hint would usually name one of the candidates, so the document would
    # be kept, the overlap would stay in the table, and the attribution would
    # rest on a convenience field rather than on the eligibility join. Failing
    # closed costs one document, whereas the hint costs the guarantee.
    if table_warning:
        return None, "", table_warning

    if from_table and from_manifest:
        if from_table.strip().lower() != from_manifest.strip().lower():
            return (
                from_table, SPEAKER_FROM_TABLE,
                f"manifest says {from_manifest!r} but the officeholder table says "
                f"{from_table!r} for {doc.pub_date.isoformat()} — check the dates",
            )
        return from_table, SPEAKER_FROM_TABLE, ""

    if from_table:
        return from_table, SPEAKER_FROM_TABLE, ""
    if from_manifest:
        return from_manifest, SPEAKER_FROM_MANIFEST, ""
    return None, "", ""


class OfficeholderTable:
    """Eligibility is a join on (institution, date), not a model judgement."""

    def __init__(self, rows: Iterable[dict]):
        self.rows = list(rows)

    # Widening the return type was preferred to adding a second, warning-aware
    # method. A second method would leave the silent one callable, and the
    # failure it hides looks exactly like success; there is one call site, so
    # the cost of changing the type is a single line.
    def eligible_speaker(
        self, institution: str, on: date
    ) -> tuple[Optional[str], str]:
        """Return (speaker, warning). The join must be unique or it is not
        evidence, so a date matching two spells names nobody.

        Spells share their boundary dates — one ends on the day the next
        begins — so a document published on a handover date matches both rows.
        Returning the first match would make the attribution depend on row
        order in the CSV, which is not a fact about who held the office. An
        overlap is a defect in the table, so it is reported upward and the
        document is dropped rather than guessed at.
        """
        matches: list[dict] = []
        for r in self.rows:
            if r["institution"].strip().lower() != institution.strip().lower():
                continue
            start = r["start_date"]
            end = r["end_date"]
            if start and on < start:
                continue
            if end and on > end:
                continue
            matches.append(r)

        if not matches:
            return None, ""
        if len(matches) > 1:
            # Listed in table order, not sorted: the reader has to find these
            # rows in the CSV to fix them.
            people = ", ".join(repr(r["person"]) for r in matches)
            return None, (
                f"the officeholder table gives {len(matches)} eligible speakers "
                f"for {institution!r} on {on.isoformat()} ({people}) — fix the "
                f"overlapping spell dates in officeholders.csv"
            )
        return matches[0]["person"], ""


# --- JEL -------------------------------------------------------------------


def validate_jel(obs: Observation, tax: JELTaxonomy) -> str:
    """Return an empty string when valid, else a reason.

    `tax` is anything exposing `check(assignment)` — the dated active list in
    production, the hierarchical taxonomy where that is still what is being
    exercised.

    An observation the classifier declined to code arrives here with empty
    assignments and is rejected, so it lands in rejected.csv with the reason
    rather than being published with blank codes. The extractor thought the
    passage was economics and the classifier did not; the disagreement is
    recorded, and the row stays out of the release.
    """
    assignments = [obs.primary] + list(obs.secondary)
    if obs.primary.is_empty():
        return "no defensible economic object: classifier assigned no JEL code"
    if len(obs.secondary) > 2:
        return "more than two secondary classifications"
    for a in assignments:
        if a.is_empty():
            continue
        ok, why = tax.check(a)
        if not ok:
            return why
    return ""


# --- dedup -----------------------------------------------------------------

_NORM = re.compile(r"[^a-z0-9 ]+")


def _fingerprint(quote: str) -> str:
    s = _NORM.sub(" ", quote.lower())
    return " ".join(s.split())


def dedupe(observations: list[Observation]) -> list[Observation]:
    """Drop repeats of the same quote, e.g. a speech republished on several
    pages. Keeps the first occurrence in the order supplied."""
    seen: set[str] = set()
    out: list[Observation] = []
    for o in observations:
        fp = _fingerprint(o.quote)
        if not fp:
            out.append(o)
            continue
        if fp in seen:
            o.valid = False
            o.reject_reason = RejectReason.DUPLICATE
            out.append(o)
            continue
        seen.add(fp)
        out.append(o)
    return out


def validate_observations(
    doc: Document,
    observations: list[Observation],
    tax: JELTaxonomy,
    officeholders: OfficeholderTable,
    min_chars: int = MIN_QUOTE_CHARS,
    max_chars: int = MAX_QUOTE_CHARS,
) -> tuple[list[Observation], Optional[str], str, str]:
    """Run every check.

    Returns (observations, speaker, speaker_source, warning) with `valid` set.
    """
    speaker, speaker_source, warning = resolve_speaker(doc, officeholders)

    # An absent spell and an overlapping one both yield no speaker, but they
    # are different defects in the table and the reject log should say which.
    # resolve_speaker() returns a warning alongside a None speaker only in the
    # overlapping case, so the warning is the discriminator; widening its
    # return tuple to carry a reason would break a contract build() relies on.
    no_speaker_reason = (
        RejectReason.AMBIGUOUS_SPEAKER if warning else RejectReason.NO_ELIGIBLE_SPEAKER
    )

    for obs in observations:
        if speaker is None:
            obs.valid = False
            obs.reject_reason = no_speaker_reason
            continue

        quote, reason = reconstruct_quote(
            doc, obs.unit_ids, obs.anchor, min_chars, max_chars
        )
        if reason:
            obs.valid = False
            obs.reject_reason = reason
            continue
        obs.quote = quote

        if not verify_quote_in_source(doc, quote):  # pragma: no cover
            obs.valid = False
            obs.reject_reason = "quote not found in source (internal error)"
            continue

        jel_reason = validate_jel(obs, tax)
        if jel_reason:
            obs.valid = False
            obs.reject_reason = f"{RejectReason.BAD_JEL}: {jel_reason}"
            continue

        obs.valid = True
        obs.reject_reason = ""

    return dedupe(observations), speaker, speaker_source, warning
