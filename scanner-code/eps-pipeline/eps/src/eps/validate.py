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

    if len({u.para_idx for u in units}) > 1:
        return "", RejectReason.CROSS_PARAGRAPH

    for a, b in zip(units, units[1:]):
        if b.sent_idx != a.sent_idx + 1:
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
    exist and disagree, which usually means a wrong date somewhere.
    """
    from_table = officeholders.eligible_speaker(doc.institution, doc.pub_date)
    from_manifest = (doc.speaker_hint or "").strip() or None

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

    def eligible_speaker(self, institution: str, on: date) -> Optional[str]:
        for r in self.rows:
            if r["institution"].strip().lower() != institution.strip().lower():
                continue
            start = r["start_date"]
            end = r["end_date"]
            if start and on < start:
                continue
            if end and on > end:
                continue
            return r["person"]
        return None


# --- JEL -------------------------------------------------------------------


def validate_jel(obs: Observation, tax: JELTaxonomy) -> str:
    """Return an empty string when valid, else a reason."""
    assignments = [obs.primary] + list(obs.secondary)
    if obs.primary.is_empty():
        return "no primary JEL classification"
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

    for obs in observations:
        if speaker is None:
            obs.valid = False
            obs.reject_reason = RejectReason.NO_ELIGIBLE_SPEAKER
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
