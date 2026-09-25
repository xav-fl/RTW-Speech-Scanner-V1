"""Editorial context: naming the referents a quote leaves implicit.

Some quotes cannot be read on their own. "Today's action not only reduces
government bureaucracy" is a complete sentence and a verbatim one, but nothing
in it says what the action was. The document title does: *USDA Strengthens
National Security ... by Standardizing Grant and Cooperative Agreement
Requirements*. This stage adds that missing noun in brackets and nothing else.

Three properties make the addition auditable:

1. `direct_quote` is never touched. This stage only ever writes a new column,
   and the bracketed string round-trips: strip the ` [...]` spans back out and
   what remains is the original, character for character. That check runs on
   every row, so the guarantee is enforced rather than asserted.
2. The model returns *insertions*, never a rewritten quote — an anchor phrase
   copied from the quote, the words to add after it, and the verbatim passage
   from the document that licenses them. Code does the splicing. A model that
   tries to paraphrase the speaker fails the anchor check and is dropped.
3. Every quote in leaves with exactly one final status. A quote nobody reached
   is distinguishable from one judged self-contained, which is the same reason
   the screening log exists for documents.

Two model steps and one code step: triage reads quotes without their documents
and says which look unresolvable; contextualisation reads one document and
resolves the quotes flagged in it; assembly splices and checks. Failure at any
check means the row keeps its plain quote and the reason is logged.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Mapping, Optional, Sequence

from .models import ContextRow, Document, Insertion
from .providers import AnthropicProvider, ModelProvider

# The cache and the fence-stripping JSON reader are extraction's, reused rather
# than reimplemented: a second copy would be a second thing to keep in step.
from .extract import ResponseCache, _parse_json  # noqa: F401  (_parse_json: see _parse_json_list)

#: v2 (2026-09-24), after reviewing the first trial run:
#:  - v1 exempted a referent named in the document title, so "This interim
#:    contract" under the headline "GSA Awards Interim Leasing Support Services
#:    Contract" was judged self-contained. The released quote is read on its
#:    own, so the title no longer resolves anything.
#:  - v1 had no rule for a quote that opens mid-argument ("That's why we
#:    stepped in to save British steel"). What is missing there is not a noun
#:    inside the quote but the reasoning before it, so v2 adds an opening
#:    frame, placed before the first word instead of after an anchor.
TRIAGE_PROMPT_VERSION = "CTX-TRIAGE-v3"
RESOLVE_PROMPT_VERSION = "CTX-RESOLVE-v2"
DEFAULT_MODEL = "claude-sonnet-4-6"

#: Quotes per triage call. Triage sends no document text, so the limit is about
#: keeping one bad response from spoiling many rows, not about context length.
DEFAULT_TRIAGE_BATCH = 25

#: A document longer than this is refused rather than truncated: a referent
#: resolved from a document the model only half saw is not evidence of anything.
#: The longest document in the US corpus is ~18.7k tokens, so this is headroom,
#: not a working constraint.
DEFAULT_MAX_DOC_TOKENS = 60_000

#: At most this many insertions per quote, per the brief. A quote needing four
#: is a quote that should be re-extracted, not annotated.
MAX_INSERTIONS = 3
MAX_INSERTION_WORDS = 12


class Status:
    """The one final status every row carries out of this stage."""

    NOT_NEEDED_TRIAGE = "not_needed_triage"
    NOT_NEEDED_RESOLVE = "not_needed_resolve"
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    MANUAL_REVIEW_EXISTING_BRACKETS = "manual_review_existing_brackets"
    # triage
    FAILED_TRIAGE_PARSE = "failed_triage_parse"
    FAILED_TRIAGE_MISSING_ID = "failed_triage_missing_id"
    FAILED_TRIAGE_NO_EXPRESSIONS = "failed_triage_no_expressions"
    # contextualisation
    FAILED_RESOLVE_PARSE = "failed_resolve_parse"
    FAILED_RESOLVE_MISSING_ID = "failed_resolve_missing_id"
    FAILED_DOCUMENT_TOO_LONG = "failed_document_too_long"
    # assembly
    FAILED_ANCHOR_NOT_FOUND = "failed_anchor_not_found"
    FAILED_ANCHOR_NOT_UNIQUE = "failed_anchor_not_unique"
    FAILED_EVIDENCE_NOT_FOUND = "failed_evidence_not_found"
    FAILED_INSERTION_FORMAT = "failed_insertion_format"
    FAILED_TOO_MANY_INSERTIONS = "failed_too_many_insertions"
    FAILED_OVERLAPPING_ANCHORS = "failed_overlapping_anchors"
    FAILED_ROUNDTRIP = "failed_roundtrip"


#: Logged but not fatal: the model anchored somewhere triage did not point at.
#: That is often correct — triage flags "today's action", the model anchors the
#: whole noun phrase — so it is a review signal rather than a rejection.
WARN_ANCHOR_NOT_FROM_TRIAGE = "warn_anchor_not_from_triage"

TRIAGE_SYSTEM = """\
You are screening direct quotations to decide whether each can be understood
on its own. You will receive a list of quotations, each with its agency,
speaker and date. You are not given the document or its title.

The quotation will be read ON ITS OWN, beside its agency, speaker and date but
NOT beside the document or its title. So a referent named only in the title is
still missing: judge the quotation by what its own words say.

A quotation NEEDS CONTEXT if either applies.

1. AN UNRESOLVED REFERENCE. It contains an expression referring to a specific
policy, action, programme, contract, investment, agreement, place, or group
that is not named anywhere in the quotation itself, such that a reader cannot
tell what is meant. Typical cases: "today's action", "this policy", "this
interim contract", "this new investment", "these innovations", "the program",
"this payment", "it" or "they" with no referent in the quotation.

2. IT OPENS MID-ARGUMENT. The quotation begins with a connective or pronoun
pointing back at something said before it — "That's why...", "That is why...",
"So, from now on...", "This is why...", "And that's why...", or an opening
"They", "It", "That" with no referent — so a reader meets a conclusion without
its premise. Flag the opening words as the expression.

A quotation does NOT need context if:
- the referent is named elsewhere in the quotation itself (e.g. "it" referring
  back to a programme named earlier in the same quotation);
- the reference is to something identifiable from the speaker, agency, or date
  alone (e.g. "this administration", "our farmers", "this country");
- the policy is broad but clearly stated, even if details are missing.
  Missing detail is not a missing referent.

When unsure, mark NEEDS CONTEXT.

Copy each expression exactly as it appears in the quotation.

Return only JSON: a list with one object per quotation, in this form:
{"quote_id": "...", "needs_context": true | false,
 "expressions": ["exact phrase(s) needing a referent"]}
Return an empty expressions list when needs_context is false.
"""

RESOLVE_SYSTEM = """\
You are adding minimal editorial context to verified direct quotations so that
each quotation can be understood on its own. You will receive one source
document (title and text) and one or more quotations from it. Each quotation
comes with the expressions a screener flagged as needing a referent.

TASK
For each flagged expression, identify what it refers to, using the source
document. Return an insertion that names the referent.

The quotation will be read on its own, without this document or its title
beside it. A referent named only in the title therefore still needs naming
inside the quotation.

RULES
1. Never rewrite, shorten, or reproduce the quotation. Return insertions only.
2. Each insertion has a "position".
   - "after" (the normal case) places it immediately after an anchor: an exact
     phrase from the quotation that occurs only once in it. The anchor should
     normally be the flagged expression.
   - "before" places it at the very start of the quotation, and takes no
     anchor. Use it, at most once, when the quotation opens mid-argument
     ("That's why...", "So, from now on...", an opening "They" or "It") and
     what is missing is the preceding subject rather than a noun inside the
     quotation. Write it as a short topic frame naming what is being discussed
     — "on the steel industry", "on locally led development" — not as a
     summary of the speaker's reasoning.
3. Insertions add information; they never replace or delete the speaker's words.
4. Resolve only references needed to identify what the quotation is about.
   Do not add background, explanation, evaluation, statistics, or
   interpretation of the speaker's intent.
5. Every insertion must be supported by the source document (title and body
   text both count). Supply the exact verbatim passage from the document that
   identifies the referent as "evidence". Copy it character for character.
6. Keep each insertion to at most 12 words and use at most 3 insertions per
   quotation. Prefer the document's own wording for the referent. Do not use
   square brackets inside an insertion.
7. If the referent cannot be identified with confidence from the document,
   do not guess. Return status "unresolved" and explain briefly in "note".
8. If, on reading the document, the quotation is already understandable on
   its own, return status "not_needed" with no insertions.

Escape any double quote that appears inside a JSON string value, so that a
passage containing quoted words stays valid JSON.

Return only JSON: a list with one object per quotation, in this form:
{
  "quote_id": "...",
  "status": "resolved" | "not_needed" | "unresolved",
  "insertions": [
    {"position": "after", "anchor": "...", "insertion": "...",
     "evidence": "..."},
    {"position": "before", "anchor": "", "insertion": "...",
     "evidence": "..."}
  ],
  "note": "..."
}
"""


# --- text handling ---------------------------------------------------------

#: Line-initial rendering markers the harvester's renderer added: blockquote
#: `> ` and Markdown headings. 3,154 of 4,470 stored US documents carry a
#: blockquote marker (11,884 lines), always line-initial and never inline, so
#: an `x > y` published by the agency is untouched.
_MARKER_RE = re.compile(r"^(?:>[ \t]|#{1,6}[ \t])+", re.M)
_WS_RE = re.compile(r"\s+")

#: Typographic variants folded to one shape for the evidence check. A model
#: copying a passage reliably retypes a curly apostrophe as a straight one, and
#: in the first trial run that alone sank 8 of 14 evidence failures — all of
#: them passages the document really did contain. Shape is not wording, so
#: folding it tests what the check is for. The six genuine failures in that run
#: — a quote stitched across an interviewer's interruption, two passages spliced
#: together with an ellipsis, three not in the document at all — still fail.
#: Strictly one character to one character, so an offset into the folded string
#: is the same offset in the original. Anchor positions are found in folded text
#: and then used to splice the untouched quote, which only holds if this stays
#: 1:1 — do not add a multi-character mapping here.
_PUNCT_1TO1 = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "–": "-", "—": "-", "−": "-", "‐": "-", "‑": "-",
    " ": " ", " ": " ", " ": " ",
})

#: For the evidence check, which collapses whitespace anyway and so has no
#: offsets to preserve. An ellipsis character and three periods are the same
#: mark, and a model picks whichever it likes when copying.
_PUNCT_FOLD = {**_PUNCT_1TO1, ord("…"): "..."}


def clean_document_text(text: str) -> str:
    """Strip the renderer's own markers from stored document text.

    `Document.text` never had the marker fix that `Unit.text` got, so it still
    carries them. The same cleaned string is both what the model is shown and
    what evidence is checked against: matching a verbatim passage against text
    the model never saw would fail for a reason that has nothing to do with the
    passage being right.
    """
    return _MARKER_RE.sub("", text)


def _comparable(text: str) -> str:
    """Cleaned form for the evidence check only: markers stripped, whitespace
    collapsed, typographic punctuation folded to one shape.

    Nothing beyond that is normalised. Case, wording and word order must still
    match exactly, so a model that paraphrases its own evidence, joins two
    passages with an ellipsis, or quotes across an interruption is still caught.
    """
    text = clean_document_text(text).translate(_PUNCT_FOLD)
    return _WS_RE.sub(" ", text).strip()


def fold_punctuation(text: str) -> str:
    """Typographic variants folded to one shape, whitespace left alone.

    Used wherever model-supplied text is matched against the corpus. A model
    retypes a curly apostrophe straight far more often than not, and in the
    first trial run that sank the brief's own worked example: triage returned
    "Today's action", the quote held "Today’s action", the expression was
    dropped as not occurring, and the row failed with no expressions.
    """
    return text.translate(_PUNCT_1TO1)


#: Punctuation a model wraps round an insertion when it imagines it is writing
#: the surrounding sentence rather than the bracketed phrase. Stripped before
#: the insertion is validated, so `[, Contracts for Difference AR7,]` reads as
#: `[Contracts for Difference AR7]`.
_EDGE_PUNCT = " \t,;:.—–-()‘’“”\"'"


def tidy_insertion(body: str) -> str:
    """An insertion is a noun phrase, not a clause: trim its edge punctuation."""
    return body.strip().strip(_EDGE_PUNCT).strip()


def approx_tokens(text: str) -> int:
    """Rough token count. Four characters per token is close enough to decide
    whether a document is refused, and needs no tokeniser dependency."""
    return len(text) // 4


def quote_id(row: Mapping[str, object]) -> str:
    """A stable ID for one extracted quote.

    Keyed on what defines the observation — the document and the units selected
    from it — rather than on the quote text, so the ID survives the quote being
    re-derived from the same units. Unique across the current dataset (447/447).
    """
    parts = "|".join(
        str(row.get(k, "") or "") for k in ("doc_id", "unit_ids", "anchor")
    )
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()[:16]


def _parse_json_list(text: str) -> list:
    """Read a JSON array from a model response, tolerating markdown fences.

    `extract._parse_json` looks for an object; both prompts here specify a
    top-level list, so the brackets differ. Everything else matches.
    """
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON array in response: {text[:200]!r}")
    import json

    block = text[start : end + 1]
    try:
        data = json.loads(block)
    except json.JSONDecodeError:
        # One malformed entry should not cost the whole document. A quotation
        # containing a double quote — a speech announcing "project reset" —
        # gets copied into "evidence" unescaped, breaking that one object and,
        # with a whole-array parse, every other quotation in the same call.
        # Salvaging object by object loses only the entry that is actually
        # broken; its quote_id then comes back missing and is logged as such.
        data = _salvage_objects(block)
        if not data:
            raise
    if not isinstance(data, list):
        raise ValueError("response is not a JSON array")
    return data


def _salvage_objects(block: str) -> list:
    """Read whatever top-level `{...}` objects parse, skipping those that do not."""
    import json

    out, depth, start = [], 0, None
    for i, ch in enumerate(block):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    out.append(json.loads(block[start : i + 1]))
                except json.JSONDecodeError:
                    pass
                start = None
    return out


# --- assembly and validation (no model) ------------------------------------


@dataclass
class Assembled:
    """Outcome of splicing one quote's insertions.

    `insertions` carries the tidied bodies actually spliced in, not what the
    model sent, so the validation log and the dataset agree on what was added.
    """

    text: str
    status: str
    warnings: list[str]
    insertions: list[Insertion] = field(default_factory=list)


def build_quote_in_context(
    direct_quote: str,
    insertions: Sequence[Insertion],
    document_text: str,
    title: str = "",
    triage_expressions: Sequence[str] = (),
) -> Assembled:
    """Splice insertions into a quote, refusing anything that fails a check.

    A failure on any one insertion fails the whole quote: a partly annotated
    quote would be harder to review than an unannotated one, because nothing
    on the row would say which half was checked.
    """
    warnings: list[str] = []
    tidied: list[Insertion] = []

    if len(insertions) > MAX_INSERTIONS:
        return Assembled(direct_quote, Status.FAILED_TOO_MANY_INSERTIONS, warnings)

    haystack = _comparable(document_text)
    title_hay = _comparable(title)
    folded_quote = fold_punctuation(direct_quote)
    spans: list[tuple[int, int, str, str]] = []

    if sum(1 for i in insertions if i.position == "before") > 1:
        # Two opening frames would read as a competing pair of summaries.
        return Assembled(direct_quote, Status.FAILED_TOO_MANY_INSERTIONS, warnings)

    for ins in insertions:
        # -- insertion format
        body = tidy_insertion(ins.insertion or "")
        if not body or "[" in body or "]" in body:
            return Assembled(direct_quote, Status.FAILED_INSERTION_FORMAT, warnings)
        if len(body.split()) > MAX_INSERTION_WORDS:
            return Assembled(direct_quote, Status.FAILED_INSERTION_FORMAT, warnings)

        # -- evidence is verbatim in the document or the title
        needle = _comparable(ins.evidence or "")
        if not needle or (needle not in haystack and needle not in title_hay):
            return Assembled(direct_quote, Status.FAILED_EVIDENCE_NOT_FOUND, warnings)

        if ins.position == "before":
            # An opening frame has no anchor: it sits at the very start, so
            # there is no phrase to locate and nothing to check for uniqueness.
            spans.append((0, 0, body, "before"))
            tidied.append(Insertion(anchor="", insertion=body,
                                    evidence=ins.evidence, position="before"))
            continue

        # -- anchor occurs exactly once. Matched on folded punctuation, which
        # is 1:1, so the offset found here indexes the untouched quote.
        anchor = ins.anchor or ""
        if not anchor:
            return Assembled(direct_quote, Status.FAILED_ANCHOR_NOT_FOUND, warnings)
        folded_anchor = fold_punctuation(anchor)
        hits = folded_quote.count(folded_anchor)
        if hits == 0:
            return Assembled(direct_quote, Status.FAILED_ANCHOR_NOT_FOUND, warnings)
        if hits > 1:
            return Assembled(direct_quote, Status.FAILED_ANCHOR_NOT_UNIQUE, warnings)

        if triage_expressions and not any(
            e and (fold_punctuation(e) in folded_anchor
                   or folded_anchor in fold_punctuation(e))
            for e in triage_expressions
        ):
            warnings.append(f"{WARN_ANCHOR_NOT_FROM_TRIAGE}: {anchor!r}")

        start = folded_quote.find(folded_anchor)
        spans.append((start, start + len(folded_anchor), body, "after"))
        tidied.append(Insertion(anchor=anchor, insertion=body,
                                evidence=ins.evidence, position="after"))

    if not spans:
        return Assembled(direct_quote, Status.UNRESOLVED, warnings)

    # -- anchors must not overlap one another. The opening frame occupies the
    # empty span (0, 0), which cannot overlap anything.
    ordered = sorted((s for s in spans if s[3] == "after"), key=lambda s: s[0])
    for (_, prev_end, _, _), (next_start, _, _, _) in zip(ordered, ordered[1:]):
        if next_start < prev_end:
            return Assembled(direct_quote, Status.FAILED_OVERLAPPING_ANCHORS, warnings)

    # -- splice from the back so earlier offsets stay valid. The opening frame
    # sorts last on end == 0, so it is prepended once everything else is in.
    out = direct_quote
    for _, end, body, pos in sorted(spans, key=lambda s: s[1], reverse=True):
        if pos == "before":
            out = f"[{body}] {out}"
        else:
            out = f"{out[:end]} [{body}]{out[end:]}"

    # -- round-trip: stripping the brackets must give the original back.
    # Checked by removing the spans afresh rather than by reusing the offsets
    # above, so an error in the splicing arithmetic cannot cancel itself out.
    stripped = re.sub(r"^\[[^\[\]]*\] ", "", out)
    if re.sub(r" \[[^\[\]]*\]", "", stripped) != direct_quote:
        return Assembled(direct_quote, Status.FAILED_ROUNDTRIP, warnings)

    return Assembled(out, Status.RESOLVED, warnings, tidied)


# --- the stage -------------------------------------------------------------


class Contextualiser:
    """Provider-agnostic, like `Extractor`: the provider is the only seam."""

    def __init__(
        self,
        provider: Optional[ModelProvider] = None,
        client=None,
        model: str = DEFAULT_MODEL,
        cache: Optional[ResponseCache] = None,
        triage_batch_size: int = DEFAULT_TRIAGE_BATCH,
        max_doc_tokens: int = DEFAULT_MAX_DOC_TOKENS,
        triage_prompt_version: str = TRIAGE_PROMPT_VERSION,
        resolve_prompt_version: str = RESOLVE_PROMPT_VERSION,
    ):
        self.provider = provider or AnthropicProvider(model=model, client=client)
        self.model = getattr(self.provider, "model", model)
        self.cache = cache
        self.triage_batch_size = max(1, triage_batch_size)
        self.max_doc_tokens = max_doc_tokens
        self.triage_prompt_version = triage_prompt_version
        self.resolve_prompt_version = resolve_prompt_version

    def _call(self, system: str, user: str, prompt_version: str,
              max_tokens: int = 4000) -> str:
        """Cached model call, keyed exactly as extraction keys its own.

        The key covers the full system and user text, so it already includes
        the quote IDs, the document and the prompt wording: changing the prompt
        version, the model or any input invalidates it, and a re-run with none
        of those changed makes no API call.
        """
        key = None
        if self.cache is not None:
            key = ResponseCache.key(
                provider=self.provider.name, model=self.model,
                system=system, user=user, prompt_version=prompt_version,
            )
            hit = self.cache.get(key)
            if hit is not None:
                return hit["text"]

        text = self.provider.call(system, user, max_tokens, cache_system=False)

        if self.cache is not None and key is not None:
            self.cache.put(
                key, {"text": text, "model": self.model, "provider": self.provider.name}
            )
        return text

    # -- step 1: triage ----------------------------------------------------

    def triage(self, items: Sequence[dict]) -> dict[str, dict]:
        """Which quotes contain an unresolvable reference.

        `items` are row dicts. Returns quote_id -> {"needs_context",
        "expressions", "status"}; `status` is set only on failure. A quote_id
        that comes back missing, duplicated or unknown is a logged failure for
        the whole batch it was in, never a silent drop.
        """
        out: dict[str, dict] = {}
        for i in range(0, len(items), self.triage_batch_size):
            batch = items[i : i + self.triage_batch_size]
            out.update(self._triage_batch(batch))
        return out

    def _triage_batch(self, batch: Sequence[dict]) -> dict[str, dict]:
        # The title is deliberately withheld. v2 told the model in words that a
        # referent named only in the title is still missing, and it went on
        # judging "This interim contract" self-contained under the headline
        # "GSA Awards Interim Leasing Support Services Contract". Not showing
        # the title removes the cue instead of arguing with it; resolve still
        # gets the title, which is where it is needed as evidence.
        lines = []
        for row in batch:
            lines.append(
                f"quote_id: {row['quote_id']}\n"
                f"agency: {row.get('agency', '')}\n"
                f"speaker: {row.get('speaker', '')}\n"
                f"date: {row.get('date', '')}\n"
                f"quotation: {row['direct_quote']}"
            )
        user = "\n\n---\n\n".join(lines)
        sent = {row["quote_id"] for row in batch}

        try:
            raw = self._call(TRIAGE_SYSTEM, user, self.triage_prompt_version)
            data = _parse_json_list(raw)
        except Exception:
            return {qid: {"status": Status.FAILED_TRIAGE_PARSE} for qid in sent}

        seen: dict[str, dict] = {}
        duplicated: set[str] = set()
        for entry in data:
            if not isinstance(entry, dict):
                continue
            qid = str(entry.get("quote_id") or "").strip()
            if qid not in sent:
                continue  # unknown id: it belongs to no row, so it fails below
            if qid in seen:
                duplicated.add(qid)
                continue
            seen[qid] = entry

        result: dict[str, dict] = {}
        for qid in sent:
            if qid in duplicated or qid not in seen:
                result[qid] = {"status": Status.FAILED_TRIAGE_MISSING_ID}
                continue
            entry = seen[qid]
            needs = bool(entry.get("needs_context"))
            quote = next(r["direct_quote"] for r in batch if r["quote_id"] == qid)
            # An expression the model did not copy is dropped: it cannot anchor
            # anything, and keeping it would put a phrase in the log that never
            # appears in the quote. Matched on folded punctuation, since an
            # apostrophe retyped straight is a copy, not a different phrase.
            folded_quote = fold_punctuation(quote)
            exprs = [
                str(e) for e in (entry.get("expressions") or [])
                if str(e) and fold_punctuation(str(e)) in folded_quote
            ]
            result[qid] = {"needs_context": needs, "expressions": exprs}
            if needs and not exprs:
                result[qid]["status"] = Status.FAILED_TRIAGE_NO_EXPRESSIONS
        return result

    # -- step 2: contextualisation -----------------------------------------

    def resolve(self, doc: Document, items: Sequence[dict]) -> dict[str, dict]:
        """Resolve one document's flagged quotes. One call per document."""
        sent = {row["quote_id"] for row in items}

        text = clean_document_text(doc.text)
        if approx_tokens(text) > self.max_doc_tokens:
            # Refused whole. Truncating here would produce insertions supported
            # by a document nobody can reproduce.
            return {qid: {"status": Status.FAILED_DOCUMENT_TOO_LONG} for qid in sent}

        blocks = []
        for row in items:
            exprs = "; ".join(row.get("expressions") or [])
            blocks.append(
                f"quote_id: {row['quote_id']}\n"
                f"quotation: {row['direct_quote']}\n"
                f"flagged expressions: {exprs}"
            )
        user = (
            f"DOCUMENT TITLE: {doc.title}\n\n"
            f"DOCUMENT TEXT:\n{text}\n\n"
            f"QUOTATIONS:\n\n" + "\n\n---\n\n".join(blocks) + "\n"
        )

        try:
            raw = self._call(RESOLVE_SYSTEM, user, self.resolve_prompt_version)
            data = _parse_json_list(raw)
        except Exception:
            return {qid: {"status": Status.FAILED_RESOLVE_PARSE} for qid in sent}

        seen: dict[str, dict] = {}
        duplicated: set[str] = set()
        for entry in data:
            if not isinstance(entry, dict):
                continue
            qid = str(entry.get("quote_id") or "").strip()
            if qid not in sent:
                continue
            if qid in seen:
                duplicated.add(qid)
                continue
            seen[qid] = entry

        result: dict[str, dict] = {}
        for qid in sent:
            if qid in duplicated or qid not in seen:
                result[qid] = {"status": Status.FAILED_RESOLVE_MISSING_ID}
                continue
            entry = seen[qid]
            insertions = []
            for raw_ins in entry.get("insertions") or []:
                if not isinstance(raw_ins, dict):
                    continue
                pos = str(raw_ins.get("position") or "after").strip().lower()
                insertions.append(
                    Insertion(
                        anchor=str(raw_ins.get("anchor") or ""),
                        insertion=str(raw_ins.get("insertion") or ""),
                        evidence=str(raw_ins.get("evidence") or ""),
                        position="before" if pos == "before" else "after",
                    )
                )
            result[qid] = {
                "status": str(entry.get("status") or "").strip(),
                "insertions": insertions,
                "note": str(entry.get("note") or "").strip()[:300],
            }
        return result

    # -- orchestration ------------------------------------------------------

    def run(
        self,
        rows: Iterable[Mapping],
        documents: Iterable[Document],
        run_timestamp: str = "",
    ) -> list[ContextRow]:
        """Run the whole stage. One ContextRow out per row in, same order."""
        ts = run_timestamp or datetime.now(timezone.utc).isoformat()
        docs = {d.doc_id: d for d in documents}
        rows = [dict(r) for r in rows]  # materialised: iterated more than once

        out: list[ContextRow] = []
        for row in rows:
            quote = str(row.get("direct_quote", "") or "")
            out.append(
                ContextRow(
                    quote_id=quote_id(row),
                    doc_id=str(row.get("doc_id", "") or ""),
                    url=str(row.get("url", "") or ""),
                    direct_quote=quote,
                    quote_in_context=quote,
                    final_status="",
                    triage_prompt_version=self.triage_prompt_version,
                    provider=self.provider.name,
                    model=self.model,
                    run_timestamp=ts,
                )
            )

        # A quote_id can in principle repeat; the model work is done once and
        # the outcome applied to every row that shares it.
        positions: dict[str, list[int]] = defaultdict(list)
        source: dict[str, dict] = {}
        for i, (r, row) in enumerate(zip(out, rows)):
            positions[r.quote_id].append(i)
            source.setdefault(r.quote_id, dict(row))

        # Quotes that already contain brackets never reach the model: bracketed
        # insertions would make the round-trip check ambiguous. The brief puts
        # this check in the contextualisation step; doing it before triage is
        # the same outcome for fewer calls.
        pending: list[dict] = []
        for qid, idxs in positions.items():
            r = out[idxs[0]]
            if "[" in r.direct_quote or "]" in r.direct_quote:
                _settle(out, idxs, Status.MANUAL_REVIEW_EXISTING_BRACKETS)
                continue
            src = source[qid]
            src.update({"quote_id": qid, "direct_quote": r.direct_quote})
            pending.append(src)

        if pending:
            self._apply_triage(out, positions, pending, docs)
        _finalise(out)
        return out

    def _apply_triage(self, out, positions, pending, docs) -> None:
        triaged = self.triage(pending)
        flagged: list[dict] = []
        for item in pending:
            qid = item["quote_id"]
            res = triaged.get(qid) or {"status": Status.FAILED_TRIAGE_MISSING_ID}
            idxs = positions[qid]
            exprs = res.get("expressions") or []
            _set_expressions(out, idxs, exprs)
            if res.get("status"):
                _settle(out, idxs, res["status"])
            elif not res.get("needs_context"):
                _settle(out, idxs, Status.NOT_NEEDED_TRIAGE)
            else:
                flagged.append({**item, "expressions": exprs})

        if flagged:
            self._apply_resolve(out, positions, flagged, docs)

    def _apply_resolve(self, out, positions, flagged, docs) -> None:
        by_doc: dict[str, list[dict]] = defaultdict(list)
        for item in flagged:
            by_doc[str(item.get("doc_id", "") or "")].append(item)

        # Stamped on everything that reaches this step, including the rows that
        # fail in it: the log should say which prompt was in force.
        for item in flagged:
            for i in positions[item["quote_id"]]:
                out[i].resolve_prompt_version = self.resolve_prompt_version

        for doc_id, items in by_doc.items():
            doc = docs.get(doc_id)
            if doc is None:
                for item in items:
                    _settle(out, positions[item["quote_id"]],
                            Status.FAILED_RESOLVE_MISSING_ID)
                continue
            resolved = self.resolve(doc, items)
            for item in items:
                qid = item["quote_id"]
                idxs = positions[qid]
                res = resolved.get(qid) or {"status": Status.FAILED_RESOLVE_MISSING_ID}
                self._apply_one(out, idxs, doc, item, res)

    def _apply_one(self, out, idxs, doc, item, res) -> None:
        status = res.get("status", "")
        note = res.get("note", "")
        if status.startswith("failed_"):
            _settle(out, idxs, status, note=note)
        elif status == "not_needed":
            _settle(out, idxs, Status.NOT_NEEDED_RESOLVE, note=note)
        elif status == "unresolved":
            _settle(out, idxs, Status.UNRESOLVED, note=note)
        elif status == "resolved":
            built = build_quote_in_context(
                out[idxs[0]].direct_quote,
                res.get("insertions") or [],
                doc.text,
                doc.title,
                item.get("expressions") or [],
            )
            # On success the log records what was actually spliced in; on
            # failure, what the model sent, since that is what needs reviewing.
            _settle(out, idxs, built.status, note=note,
                    text=built.text,
                    insertions=built.insertions or res.get("insertions") or [],
                    warnings=built.warnings)
        else:
            _settle(out, idxs, Status.FAILED_RESOLVE_PARSE, note=note)


def _settle(out, idxs, status, note="", text=None, insertions=(), warnings=()) -> None:
    for i in idxs:
        r = out[i]
        r.final_status = status
        r.model_note = note or r.model_note
        if text is not None:
            r.quote_in_context = text
        if insertions:
            r.insertions = list(insertions)
        if warnings:
            r.warnings = list(warnings)


def _set_expressions(out, idxs, exprs) -> None:
    for i in idxs:
        out[i].triage_expressions = list(exprs)


def _finalise(out) -> None:
    """No row leaves without a status, and none leaves with an empty column."""
    for r in out:
        if not r.final_status:
            r.final_status = Status.FAILED_TRIAGE_MISSING_ID
        if not r.quote_in_context:
            r.quote_in_context = r.direct_quote


def summarise(rows: Sequence[ContextRow]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.final_status] = counts.get(r.final_status, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))
