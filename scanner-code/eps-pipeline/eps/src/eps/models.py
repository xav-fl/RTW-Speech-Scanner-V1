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


@dataclass(frozen=True)
class Insertion:
    """One bracketed editorial addition to a quote.

    `anchor` is an exact phrase from the quote; the insertion is placed
    immediately after it. `evidence` is the verbatim passage from the source
    document (title or body) that identifies the referent, and is what makes
    the addition checkable without re-reading the document by hand.
    """

    anchor: str
    insertion: str
    evidence: str
    # "after" places the insertion immediately after `anchor`, the ordinary
    # case. "before" places it at the very start of the quote and ignores
    # `anchor`: it is for a quote that opens mid-argument ("That's why we
    # stepped in to save British steel"), where what is missing is not a noun
    # inside the quote but the reasoning that preceded it.
    position: str = "after"


@dataclass
class ContextRow:
    """One row of the context stage's validation log — one per quote in.

    Every quote that enters the stage leaves with exactly one `final_status`,
    so a quote that was never reached is distinguishable from one the model
    judged self-contained. `quote_in_context` always holds a usable string: it
    falls back to the unmodified quote whenever context was not added.
    """

    quote_id: str
    doc_id: str
    url: str
    direct_quote: str
    quote_in_context: str
    final_status: str
    triage_expressions: list[str] = field(default_factory=list)
    insertions: list[Insertion] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    model_note: str = ""
    triage_prompt_version: str = ""
    resolve_prompt_version: str = ""
    provider: str = ""
    model: str = ""
    run_timestamp: str = ""


class IntentionBroad:
    """What the speaker is doing with a quote. INTENTION_CODEBOOK.md, Section 4.

    The codes are fixed by the brief: do not rename, merge or add.
    """

    COMMITS_TO_ACTION = "commits_to_action"
    REPORTS_EXISTING_ACTION = "reports_existing_action"
    CONSIDERS_OPEN_OPTION = "considers_open_option"
    RULES_OUT_OPTION = "rules_out_option"
    CALLS_ON_OTHERS = "calls_on_others"
    STATES_VIEW_WITHOUT_ACTION = "states_view_without_action"
    UNCLEAR = "unclear"


class IntentionSub:
    ANNOUNCES_DECISION = "announces_decision"
    PLEDGES_FUTURE_ACTION = "pledges_future_action"
    MAKES_CONDITIONAL_COMMITMENT = "makes_conditional_commitment"
    COMPLETED_ACTION = "completed_action"
    OUTCOME = "outcome"
    ONGOING_IMPLEMENTATION = "ongoing_implementation"
    PREFERRED_OPTION = "preferred_option"
    NO_STATED_PREFERENCE = "no_stated_preference"
    EVIDENCE = "evidence"
    OTHER_STATES = "other_states"
    PRIVATE_ACTORS = "private_actors"
    DESCRIBES_PROBLEM = "describes_problem"
    VALUE_JUDGEMENT = "value_judgement"
    # Added in I2 by the project lead: a cause-and-effect claim with no action
    # had nowhere to go but value_judgement.
    CAUSAL_BELIEF = "causal_belief"


#: The sub codes valid under each broad code, in codebook order. An empty tuple
#: means the broad code takes no sub code at all.
INTENTION_SUBS: dict[str, tuple[str, ...]] = {
    IntentionBroad.COMMITS_TO_ACTION: (
        IntentionSub.ANNOUNCES_DECISION,
        IntentionSub.PLEDGES_FUTURE_ACTION,
        IntentionSub.MAKES_CONDITIONAL_COMMITMENT,
    ),
    IntentionBroad.REPORTS_EXISTING_ACTION: (
        IntentionSub.COMPLETED_ACTION,
        IntentionSub.OUTCOME,
        IntentionSub.ONGOING_IMPLEMENTATION,
    ),
    IntentionBroad.CONSIDERS_OPEN_OPTION: (
        IntentionSub.PREFERRED_OPTION,
        IntentionSub.NO_STATED_PREFERENCE,
    ),
    IntentionBroad.RULES_OUT_OPTION: (),
    IntentionBroad.CALLS_ON_OTHERS: (
        IntentionSub.EVIDENCE,
        IntentionSub.OTHER_STATES,
        IntentionSub.PRIVATE_ACTORS,
    ),
    IntentionBroad.STATES_VIEW_WITHOUT_ACTION: (
        IntentionSub.DESCRIBES_PROBLEM,
        IntentionSub.VALUE_JUDGEMENT,
        IntentionSub.CAUSAL_BELIEF,
    ),
    IntentionBroad.UNCLEAR: (),
}
BROAD_CODES = tuple(INTENTION_SUBS)
SUB_CODES = tuple(s for subs in INTENTION_SUBS.values() for s in subs)

#: Required when sub is `evidence`, and must be null otherwise.
EVIDENCE_TYPES = ("public_consultation", "expert_referral", "research_or_data")


class IntentionFailure:
    """The named reasons a quote can fail tagging. INTENTION_TAG_BRIEF_v1, 6.3."""

    INVALID_JSON = "invalid_json"
    TRUNCATED_OUTPUT = "truncated_output"
    INVALID_LABEL = "invalid_label"
    INVALID_SUB_FOR_BROAD = "invalid_sub_for_broad"
    EVIDENCE_TYPE_MISMATCH = "evidence_type_mismatch"
    CUE_NOT_IN_INPUT = "cue_not_in_input"
    # I2: the label must rest on the quote's own words; context settles tense
    # and actor but cannot supply the label. Kept apart from cue_not_in_input
    # so the cost of the rule shows up by name in the failure counts.
    LABEL_CUE_NOT_IN_QUOTE = "label_cue_not_in_quote"
    MISSING_FLAG_CUE = "missing_flag_cue"
    PROVIDER_ERROR = "provider_error"


FAILURE_REASONS = tuple(
    v for k, v in vars(IntentionFailure).items() if not k.startswith("_")
)


class IntentionInvalid(ValueError):
    """A tag broke a codebook rule. `reason` is one of FAILURE_REASONS."""

    def __init__(self, reason: str, detail: str):
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


def valid_pair(broad: Optional[str], sub: Optional[str]) -> bool:
    return broad in INTENTION_SUBS and (
        sub in INTENTION_SUBS[broad] if INTENTION_SUBS[broad] else sub is None
    )


@dataclass
class IntentionResult:
    """One quote's intention tag, or the named reason it has none.

    Validated on construction, so a tag that breaks a codebook rule cannot
    exist: the tagger turns the exception into a `failed` result instead. A
    failed result carries no label at all — it is never defaulted to a real one.
    """

    quote_id: str
    status: str  # "tagged" | "failed"
    broad: Optional[str] = None
    sub: Optional[str] = None
    secondary_broad: Optional[str] = None
    secondary_sub: Optional[str] = None
    evidence_type: Optional[str] = None
    has_quantified_target: Optional[bool] = None
    target_cue: Optional[str] = None
    claims_causal_effect: Optional[bool] = None
    causal_cue: Optional[str] = None
    cue: Optional[str] = None  # the words that determined the label
    rationale: Optional[str] = None  # one sentence, for review only
    failure_reason: Optional[str] = None
    context_source: str = ""  # "units" | "quote_only"
    prompt_version: str = ""
    prompt_fingerprint: str = ""
    model: str = ""
    timestamp: str = ""

    def __post_init__(self) -> None:
        if self.status == "failed":
            if self.failure_reason not in FAILURE_REASONS:
                raise ValueError(f"unknown failure_reason {self.failure_reason!r}")
            return
        if self.status != "tagged":
            raise ValueError(f"unknown status {self.status!r}")
        if self.failure_reason is not None:
            raise ValueError("a tagged result has no failure_reason")
        self._check_labels()

    def _check_labels(self) -> None:
        # Unknown codes first, so a misspelt label is reported as a misspelling
        # rather than as a pairing error.
        for code, allowed in ((self.broad, BROAD_CODES), (self.sub, SUB_CODES + (None,)),
                              (self.secondary_broad, BROAD_CODES + (None,)),
                              (self.secondary_sub, SUB_CODES + (None,))):
            if code not in allowed:
                raise IntentionInvalid(IntentionFailure.INVALID_LABEL,
                                       f"{code!r} is not a permitted code")
        if self.secondary_broad == IntentionBroad.UNCLEAR:
            raise IntentionInvalid(IntentionFailure.INVALID_LABEL,
                                   "unclear cannot be a secondary label")

        if not valid_pair(self.broad, self.sub):
            raise IntentionInvalid(IntentionFailure.INVALID_SUB_FOR_BROAD,
                                   f"{self.sub!r} is not valid under {self.broad!r}")
        both_null = self.secondary_broad is None and self.secondary_sub is None
        if not both_null and not valid_pair(self.secondary_broad, self.secondary_sub):
            raise IntentionInvalid(
                IntentionFailure.INVALID_SUB_FOR_BROAD,
                f"secondary {self.secondary_sub!r} is not valid under "
                f"{self.secondary_broad!r}")

        if (self.evidence_type is not None
                and self.evidence_type not in EVIDENCE_TYPES):
            raise IntentionInvalid(IntentionFailure.EVIDENCE_TYPE_MISMATCH,
                                   f"{self.evidence_type!r} is not an evidence type")
        if (self.sub == IntentionSub.EVIDENCE) != (self.evidence_type is not None):
            raise IntentionInvalid(
                IntentionFailure.EVIDENCE_TYPE_MISMATCH,
                "evidence_type must be set for sub=evidence and only for it")

        for flag, cue in (("has_quantified_target", self.target_cue),
                          ("claims_causal_effect", self.causal_cue)):
            value = getattr(self, flag)
            if not isinstance(value, bool):
                raise IntentionInvalid(IntentionFailure.INVALID_JSON,
                                       f"{flag} must be true or false")
            if value and not (cue or "").strip():
                raise IntentionInvalid(IntentionFailure.MISSING_FLAG_CUE,
                                       f"{flag} is true with no cue")
            if not value and cue is not None:
                raise IntentionInvalid(IntentionFailure.MISSING_FLAG_CUE,
                                       f"{flag} is false but has a cue")

        # Only `unclear` may leave the label cue empty: it has, by definition,
        # no words that settled the label.
        if self.broad != IntentionBroad.UNCLEAR and not (self.cue or "").strip():
            raise IntentionInvalid(IntentionFailure.CUE_NOT_IN_INPUT,
                                   "no cue given for the label")


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
