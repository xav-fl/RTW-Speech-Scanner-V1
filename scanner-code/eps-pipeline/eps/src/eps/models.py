"""Core data structures.

A `Document` is a frozen, hashed snapshot of one source page. Its normalised
text is segmented into `Unit`s (sentences) with stable IDs. An `Observation`
never carries free-text produced by a model: it carries unit IDs, and the quote
is reconstructed from the frozen text. That is what makes quote fidelity a
property of the code rather than a metric to be checked afterwards.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Optional

# Normalised document-type labels, Section 4 of the field guide.
DOC_TYPES = (
    "speech",
    "statement",
    "press_release",
    "testimony",
    "letter",
    "op_ed",
    "interview_transcript",
    "other",
)

# Whether the text is what was said or what was written to be said. Recorded at
# harvest time because it cannot be reconstructed later.
DELIVERY_STATUS = ("as_delivered", "as_prepared", "unknown")


def sha256(text: str | bytes) -> str:
    if isinstance(text, str):
        text = text.encode("utf-8")
    return hashlib.sha256(text).hexdigest()


@dataclass(frozen=True)
class Unit:
    """One sentence of normalised text, with a stable ID and character offsets."""

    unit_id: str
    para_idx: int
    sent_idx: int
    text: str
    char_start: int
    char_end: int
    # False when the sentence is institutional prose rather than the speaker's
    # own words (see normalise.mark_attribution). Only meaningful for document
    # types where the two are mixed, e.g. press releases.
    attributable: bool = True


@dataclass
class Document:
    doc_id: str  # short hash prefix, used as the unit-ID namespace
    institution: str  # canonical name from institutions.csv
    country: str  # "US" | "UK"
    url: str  # canonical, tracking params stripped
    title: str
    doc_type: str  # one of DOC_TYPES
    pub_date: date
    delivery_status: str = "unknown"
    speaker_hint: Optional[str] = None  # from source metadata, if any
    raw_sha256: str = ""  # hash of the bytes as fetched
    text_sha256: str = ""  # hash of the normalised text
    segmenter_version: str = ""
    retrieved_at: Optional[datetime] = None
    source_index: str = ""  # which listing/API the doc was found through
    text: str = ""
    units: list[Unit] = field(default_factory=list)

    def unit_map(self) -> dict[str, Unit]:
        return {u.unit_id: u for u in self.units}

    def meta(self) -> dict:
        d = asdict(self)
        d.pop("units", None)
        d.pop("text", None)
        d["pub_date"] = self.pub_date.isoformat() if self.pub_date else ""
        d["retrieved_at"] = self.retrieved_at.isoformat() if self.retrieved_at else ""
        return d


@dataclass
class JELAssignment:
    """One JEL classification, code plus the AEA's exact title, at each level."""

    major_code: str = ""
    major_title: str = ""
    sub_code: str = ""
    sub_title: str = ""
    detailed_code: str = ""
    detailed_title: str = ""
    # How well the code fits this quote: 3 direct, 2 strong, 1 weak. A semantic
    # match score, not a probability and not model confidence -- and a different
    # quantity from the EPS relevance score. An observation the classifier
    # declines to code scores 0 and is rejected rather than published.
    match_strength: int = 0

    def is_empty(self) -> bool:
        return not (self.major_code or self.sub_code or self.detailed_code)

    def fmt(self, level: str) -> str:
        """Render as `J24 — Human Capital; Skills; ...` per the guide's format."""
        code = getattr(self, f"{level}_code")
        title = getattr(self, f"{level}_title")
        return f"{code} — {title}" if code else ""


@dataclass
class Observation:
    doc_id: str
    unit_ids: list[str]
    quote: str = ""  # reconstructed by code, never model-authored
    anchor: Optional[str] = None  # optional sub-sentence span, exact-matched
    primary: JELAssignment = field(default_factory=JELAssignment)
    secondary: list[JELAssignment] = field(default_factory=list)
    # The model's stated justification. Recorded for human review only:
    # it is generated after the selection, so it is a plausible account of the
    # choice, not evidence about how the choice was made.
    reason: str = ""
    # The specific mechanism, instrument, population or outcome the model named
    # in Stage 2 before choosing a code. Stated ahead of the code rather than
    # after it, but position within one response is not evidence of causation,
    # so this gets the same treatment as `reason`: recorded for human review,
    # never fed back into a prompt.
    mechanism: str = ""
    # provenance
    provider: str = ""          # "anthropic" | "mistral" | "fake"
    model_id: str = ""
    prompt_version: str = ""   # the label you set by hand
    prompt_sha: str = ""       # hash of the prompt text, set automatically
    run_id: str = ""
    identity_mode: str = ""  # "blind" | "full" — what the model was told
    # populated by validate.py
    valid: bool = False
    reject_reason: str = ""


@dataclass
class ScreeningRow:
    """One row per document inspected, so a genuine zero is distinguishable
    from an agency that was never reached (field guide, Section 6)."""

    doc_id: str
    institution: str
    country: str
    url: str
    title: str
    doc_type: str
    pub_date: str
    speaker: str
    speaker_source: str  # officeholder_table | manifest | ""
    eligible: bool
    exclusion_reason: str
    n_observations: int
    retrieved_at: str
    segmenter_version: str
    prompt_version: str
    model_id: str
