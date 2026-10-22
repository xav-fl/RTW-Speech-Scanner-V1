"""Editorial context: naming the referents a quote leaves implicit.

Some quotes cannot be read on their own. "Today's action not only reduces
government bureaucracy" is a complete, verbatim sentence, but nothing in it
says what the action was. The source document does. This tool adds that
missing noun in square brackets and nothing else:

    Today's action [standardizing grant and cooperative agreement
    requirements] not only reduces government bureaucracy ...

Extracted from the EPS (economic policy statements) pipeline so it can run on
any set of quotes that each come from a known source document. Standalone:
standard library only, plus the `anthropic` or `openai` SDK for the model.

Three properties make the addition auditable:

1. `direct_quote` is never touched. Output goes to a new column,
   `quote_in_context`, and the bracketed string round-trips: strip the
   ` [...]` spans back out and what remains is the original, character for
   character. That check runs on every row.
2. The model returns *insertions*, never a rewritten quote: an anchor phrase
   copied from the quote, the words to add after it, and the verbatim passage
   from the document that licenses them. Code does the splicing. A model that
   paraphrases the speaker fails the anchor check and the row is left plain.
3. Every quote leaves with exactly one `final_status`, so a quote nobody
   reached is distinguishable from one judged self-contained.

Two model steps and one code step:
  triage   - reads quotes WITHOUT their documents, flags unresolvable phrases
  resolve  - reads one document, names the referent for each flagged quote
  assembly - splices insertions in and checks anchor, evidence and round-trip
Failure at any check means the row keeps its plain quote and the reason is
logged in `final_status`.

Usage:
    python quote_context.py --quotes quotes.csv --documents docs.jsonl \
        --out quotes_in_context.csv [--provider anthropic|openai] [--model M]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional, Protocol, Sequence

TRIAGE_PROMPT_VERSION = "CTX-TRIAGE-v3"
RESOLVE_PROMPT_VERSION = "CTX-RESOLVE-v2"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"  # the model EPS was validated on

#: Quotes per triage call. Triage sends no document text, so the limit is about
#: keeping one bad response from spoiling many rows, not about context length.
DEFAULT_TRIAGE_BATCH = 25

#: A document longer than this is refused rather than truncated: a referent
#: resolved from a document the model only half saw is not evidence of anything.
DEFAULT_MAX_DOC_TOKENS = 60_000

#: A quote needing more than three insertions should be re-extracted, not
#: annotated.
MAX_INSERTIONS = 3
MAX_INSERTION_WORDS = 12


class Status:
    """The one final status every row carries out."""

    NOT_NEEDED_TRIAGE = "not_needed_triage"
    NOT_NEEDED_RESOLVE = "not_needed_resolve"
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    MANUAL_REVIEW_EXISTING_BRACKETS = "manual_review_existing_brackets"
    # triage
    FAILED_TRIAGE_PARSE = "failed_triage_parse"
    FAILED_TRIAGE_MISSING_ID = "failed_triage_missing_id"
    FAILED_TRIAGE_NO_EXPRESSIONS = "failed_triage_no_expressions"
    # resolve
    FAILED_RESOLVE_PARSE = "failed_resolve_parse"
    FAILED_RESOLVE_MISSING_ID = "failed_resolve_missing_id"
    FAILED_DOCUMENT_MISSING = "failed_document_missing"
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
#: Often correct (triage flags "today's action", the model anchors the whole
#: noun phrase), so it is a review signal rather than a rejection.
WARN_ANCHOR_NOT_FROM_TRIAGE = "warn_anchor_not_from_triage"


# --- prompts ---------------------------------------------------------------
# The "typical cases" and "does NOT need context" lists are tuned to policy
# statements by government officials. Adapt them to your corpus, and bump the
# prompt version when you do so cached responses are not reused.

TRIAGE_SYSTEM = """\
You are screening direct quotations to decide whether each can be understood
on its own. You will receive a list of quotations, each with its organisation,
speaker and date. You are not given the document or its title.

The quotation will be read ON ITS OWN, beside its organisation, speaker and
date but NOT beside the document or its title. So a referent named only in the
title is still missing: judge the quotation by what its own words say.

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
- the reference is to something identifiable from the speaker, organisation,
  or date alone (e.g. "this administration", "our farmers", "this country");
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


# --- data ------------------------------------------------------------------


@dataclass
class Document:
    doc_id: str
    title: str
    text: str


@dataclass
class Insertion:
    """One bracketed addition. `anchor` is an exact phrase from the quote and
    the insertion goes immediately after it ("after"), or at the very start of
    the quote with no anchor ("before"). `evidence` is the verbatim passage
    from the document that identifies the referent."""

    anchor: str
    insertion: str
    evidence: str
    position: str = "after"


@dataclass
class ContextRow:
    """One output row per quote in. `quote_in_context` always holds a usable
    string: it falls back to the plain quote whenever context was not added."""

    quote_id: str
    doc_id: str
    direct_quote: str
    quote_in_context: str
    final_status: str = ""
    triage_expressions: list[str] = field(default_factory=list)
    insertions: list[Insertion] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    model_note: str = ""
    triage_prompt_version: str = ""
    resolve_prompt_version: str = ""
    provider: str = ""
    model: str = ""
    run_timestamp: str = ""


# --- model providers -------------------------------------------------------


class ModelProvider(Protocol):
    name: str
    model: str

    def call(self, system: str, user: str, max_tokens: int) -> str: ...


class AnthropicProvider:
    """Needs ANTHROPIC_API_KEY and `pip install anthropic`."""

    name = "anthropic"

    def __init__(self, model: str = DEFAULT_ANTHROPIC_MODEL):
        from anthropic import Anthropic

        self.model = model
        self.client = Anthropic(max_retries=5)

    def call(self, system: str, user: str, max_tokens: int) -> str:
        resp = self.client.messages.create(
            model=self.model, max_tokens=max_tokens, temperature=0,
            system=system, messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


class OpenAIProvider:
    """Needs OPENAI_API_KEY and `pip install openai`."""

    name = "openai"

    def __init__(self, model: str):
        from openai import OpenAI

        self.model = model
        self.client = OpenAI(max_retries=5)

    def call(self, system: str, user: str, max_tokens: int) -> str:
        resp = self.client.chat.completions.create(
            model=self.model, max_completion_tokens=max_tokens,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
        )
        return resp.choices[0].message.content or ""


class ResponseCache:
    """Content-addressed cache of model responses. A re-run with the same
    prompts, model and inputs makes no API call, and committing the cache makes
    a third party's re-run byte-identical."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(**parts) -> str:
        blob = json.dumps(parts, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def get(self, key: str) -> Optional[dict]:
        p = self.root / key[:2] / f"{key}.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def put(self, key: str, value: dict) -> None:
        p = self.root / key[:2] / f"{key}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


# --- text handling ---------------------------------------------------------

#: Line-initial Markdown markers (blockquote `> `, headings) a renderer may add
#: to stored document text. Only line-initial, so an inline `x > y` survives.
_MARKER_RE = re.compile(r"^(?:>[ \t]|#{1,6}[ \t])+", re.M)
_WS_RE = re.compile(r"\s+")

#: Typographic variants folded to one shape. A model copying a passage
#: reliably retypes a curly apostrophe as a straight one; in the EPS trial that
#: alone sank 8 of 14 evidence failures, all of them passages the document
#: really did contain. Strictly one character to one character, so an offset
#: into the folded string is the same offset in the original: anchors are found
#: in folded text and then used to splice the untouched quote. Do not add a
#: multi-character mapping here.
_PUNCT_1TO1 = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "–": "-", "—": "-", "−": "-", "‐": "-", "‑": "-",
    " ": " ", " ": " ", " ": " ",
})

#: For the evidence check only, which collapses whitespace and so has no
#: offsets to preserve: an ellipsis character and three periods are one mark.
_PUNCT_FOLD = {**_PUNCT_1TO1, ord("…"): "..."}

#: Punctuation a model wraps round an insertion when it imagines it is writing
#: the surrounding sentence, so `[, Contracts for Difference AR7,]` reads as
#: `[Contracts for Difference AR7]`.
_EDGE_PUNCT = " \t,;:.—–-()‘’“”\"'"


def clean_document_text(text: str) -> str:
    """Strip renderer markers. The same cleaned string is what the model sees
    and what evidence is checked against."""
    return _MARKER_RE.sub("", text)


def _comparable(text: str) -> str:
    """For the evidence check: markers stripped, whitespace collapsed,
    typographic punctuation folded. Case, wording and word order must still
    match exactly, so a paraphrased or ellipsis-spliced passage is caught."""
    text = clean_document_text(text).translate(_PUNCT_FOLD)
    return _WS_RE.sub(" ", text).strip()


def fold_punctuation(text: str) -> str:
    return text.translate(_PUNCT_1TO1)


def tidy_insertion(body: str) -> str:
    return body.strip().strip(_EDGE_PUNCT).strip()


def approx_tokens(text: str) -> int:
    return len(text) // 4


def make_quote_id(row: Mapping[str, object]) -> str:
    """Used when the input has no quote_id column."""
    parts = f"{row.get('doc_id', '')}|{row.get('direct_quote', '')}"
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()[:16]


def _parse_json_list(text: str) -> list:
    """Read a JSON array from a model response, tolerating markdown fences and
    salvaging object by object if one entry is malformed (typically an
    unescaped double quote copied into "evidence")."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON array in response: {text[:200]!r}")
    block = text[start : end + 1]
    try:
        data = json.loads(block)
    except json.JSONDecodeError:
        data = _salvage_objects(block)
        if not data:
            raise
    if not isinstance(data, list):
        raise ValueError("response is not a JSON array")
    return data


def _salvage_objects(block: str) -> list:
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
    quote is harder to review than an unannotated one.
    """
    warnings: list[str] = []
    tidied: list[Insertion] = []

    if len(insertions) > MAX_INSERTIONS:
        return Assembled(direct_quote, Status.FAILED_TOO_MANY_INSERTIONS, warnings)
    if sum(1 for i in insertions if i.position == "before") > 1:
        return Assembled(direct_quote, Status.FAILED_TOO_MANY_INSERTIONS, warnings)

    haystack = _comparable(document_text)
    title_hay = _comparable(title)
    folded_quote = fold_punctuation(direct_quote)
    spans: list[tuple[int, int, str, str]] = []

    for ins in insertions:
        body = tidy_insertion(ins.insertion or "")
        if not body or "[" in body or "]" in body:
            return Assembled(direct_quote, Status.FAILED_INSERTION_FORMAT, warnings)
        if len(body.split()) > MAX_INSERTION_WORDS:
            return Assembled(direct_quote, Status.FAILED_INSERTION_FORMAT, warnings)

        # evidence is verbatim in the document or the title
        needle = _comparable(ins.evidence or "")
        if not needle or (needle not in haystack and needle not in title_hay):
            return Assembled(direct_quote, Status.FAILED_EVIDENCE_NOT_FOUND, warnings)

        if ins.position == "before":
            spans.append((0, 0, body, "before"))
            tidied.append(Insertion("", body, ins.evidence, "before"))
            continue

        # anchor occurs exactly once (matched on 1:1 folded punctuation, so the
        # offset found here indexes the untouched quote)
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
        tidied.append(Insertion(anchor, body, ins.evidence, "after"))

    if not spans:
        return Assembled(direct_quote, Status.UNRESOLVED, warnings)

    ordered = sorted((s for s in spans if s[3] == "after"), key=lambda s: s[0])
    for (_, prev_end, _, _), (next_start, _, _, _) in zip(ordered, ordered[1:]):
        if next_start < prev_end:
            return Assembled(direct_quote, Status.FAILED_OVERLAPPING_ANCHORS, warnings)

    # splice from the back so earlier offsets stay valid; the opening frame
    # sorts last on end == 0 and is prepended once everything else is in
    out = direct_quote
    for _, end, body, pos in sorted(spans, key=lambda s: s[1], reverse=True):
        out = f"[{body}] {out}" if pos == "before" else f"{out[:end]} [{body}]{out[end:]}"

    # round-trip: stripping the brackets afresh must give the original back
    stripped = re.sub(r"^\[[^\[\]]*\] ", "", out)
    if re.sub(r" \[[^\[\]]*\]", "", stripped) != direct_quote:
        return Assembled(direct_quote, Status.FAILED_ROUNDTRIP, warnings)

    return Assembled(out, Status.RESOLVED, warnings, tidied)


# --- the stage -------------------------------------------------------------


class Contextualiser:
    def __init__(
        self,
        provider: ModelProvider,
        cache: Optional[ResponseCache] = None,
        triage_batch_size: int = DEFAULT_TRIAGE_BATCH,
        max_doc_tokens: int = DEFAULT_MAX_DOC_TOKENS,
    ):
        self.provider = provider
        self.model = getattr(provider, "model", "")
        self.cache = cache
        self.triage_batch_size = max(1, triage_batch_size)
        self.max_doc_tokens = max_doc_tokens

    def _call(self, system: str, user: str, prompt_version: str,
              max_tokens: int = 4000) -> str:
        key = None
        if self.cache is not None:
            key = ResponseCache.key(provider=self.provider.name, model=self.model,
                                    system=system, user=user,
                                    prompt_version=prompt_version)
            hit = self.cache.get(key)
            if hit is not None:
                return hit["text"]
        text = self.provider.call(system, user, max_tokens)
        if key is not None:
            self.cache.put(key, {"text": text, "model": self.model,
                                 "provider": self.provider.name})
        return text

    @staticmethod
    def _index(data: list, sent: set[str]) -> tuple[dict[str, dict], set[str]]:
        """Response entries by quote_id. Unknown ids are ignored; missing and
        duplicated ids become logged failures, never silent drops."""
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
        return seen, duplicated

    # -- step 1: triage ----------------------------------------------------

    def triage(self, items: Sequence[dict]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for i in range(0, len(items), self.triage_batch_size):
            out.update(self._triage_batch(items[i : i + self.triage_batch_size]))
        return out

    def _triage_batch(self, batch: Sequence[dict]) -> dict[str, dict]:
        # The title is deliberately withheld. Told in words that a referent
        # named only in the title is still missing, the model went on judging
        # "This interim contract" self-contained under a headline naming the
        # contract. Not showing the title removes the cue instead of arguing
        # with it; resolve still gets the title, where it serves as evidence.
        user = "\n\n---\n\n".join(
            f"quote_id: {row['quote_id']}\n"
            f"organisation: {row.get('organisation', '')}\n"
            f"speaker: {row.get('speaker', '')}\n"
            f"date: {row.get('date', '')}\n"
            f"quotation: {row['direct_quote']}"
            for row in batch
        )
        sent = {row["quote_id"] for row in batch}
        try:
            data = _parse_json_list(self._call(TRIAGE_SYSTEM, user, TRIAGE_PROMPT_VERSION))
        except Exception:
            return {qid: {"status": Status.FAILED_TRIAGE_PARSE} for qid in sent}

        seen, duplicated = self._index(data, sent)
        quotes = {row["quote_id"]: row["direct_quote"] for row in batch}
        result: dict[str, dict] = {}
        for qid in sent:
            if qid in duplicated or qid not in seen:
                result[qid] = {"status": Status.FAILED_TRIAGE_MISSING_ID}
                continue
            entry = seen[qid]
            needs = bool(entry.get("needs_context"))
            # an expression the model did not actually copy from the quote
            # cannot anchor anything, so it is dropped
            folded_quote = fold_punctuation(quotes[qid])
            exprs = [str(e) for e in (entry.get("expressions") or [])
                     if str(e) and fold_punctuation(str(e)) in folded_quote]
            result[qid] = {"needs_context": needs, "expressions": exprs}
            if needs and not exprs:
                result[qid]["status"] = Status.FAILED_TRIAGE_NO_EXPRESSIONS
        return result

    # -- step 2: resolve ---------------------------------------------------

    def resolve(self, doc: Document, items: Sequence[dict]) -> dict[str, dict]:
        """Resolve one document's flagged quotes. One call per document."""
        sent = {row["quote_id"] for row in items}
        text = clean_document_text(doc.text)
        if approx_tokens(text) > self.max_doc_tokens:
            return {qid: {"status": Status.FAILED_DOCUMENT_TOO_LONG} for qid in sent}

        blocks = "\n\n---\n\n".join(
            f"quote_id: {row['quote_id']}\n"
            f"quotation: {row['direct_quote']}\n"
            f"flagged expressions: {'; '.join(row.get('expressions') or [])}"
            for row in items
        )
        user = (f"DOCUMENT TITLE: {doc.title}\n\n"
                f"DOCUMENT TEXT:\n{text}\n\n"
                f"QUOTATIONS:\n\n{blocks}\n")
        try:
            data = _parse_json_list(self._call(RESOLVE_SYSTEM, user, RESOLVE_PROMPT_VERSION))
        except Exception:
            return {qid: {"status": Status.FAILED_RESOLVE_PARSE} for qid in sent}

        seen, duplicated = self._index(data, sent)
        result: dict[str, dict] = {}
        for qid in sent:
            if qid in duplicated or qid not in seen:
                result[qid] = {"status": Status.FAILED_RESOLVE_MISSING_ID}
                continue
            entry = seen[qid]
            insertions = []
            for raw in entry.get("insertions") or []:
                if not isinstance(raw, dict):
                    continue
                pos = str(raw.get("position") or "after").strip().lower()
                insertions.append(Insertion(
                    anchor=str(raw.get("anchor") or ""),
                    insertion=str(raw.get("insertion") or ""),
                    evidence=str(raw.get("evidence") or ""),
                    position="before" if pos == "before" else "after",
                ))
            result[qid] = {"status": str(entry.get("status") or "").strip(),
                           "insertions": insertions,
                           "note": str(entry.get("note") or "").strip()[:300]}
        return result

    # -- orchestration ------------------------------------------------------

    def run(self, rows: Sequence[Mapping], documents: Sequence[Document]) -> list[ContextRow]:
        """One ContextRow out per row in, same order."""
        ts = datetime.now(timezone.utc).isoformat()
        docs = {d.doc_id: d for d in documents}
        rows = [dict(r) for r in rows]
        out = [
            ContextRow(
                quote_id=str(r.get("quote_id") or "") or make_quote_id(r),
                doc_id=str(r.get("doc_id") or ""),
                direct_quote=str(r.get("direct_quote") or ""),
                quote_in_context=str(r.get("direct_quote") or ""),
                triage_prompt_version=TRIAGE_PROMPT_VERSION,
                provider=self.provider.name, model=self.model, run_timestamp=ts,
            )
            for r in rows
        ]

        # A repeated quote_id is worked once and applied to every row sharing it.
        positions: dict[str, list[int]] = defaultdict(list)
        source: dict[str, dict] = {}
        for i, (r, row) in enumerate(zip(out, rows)):
            positions[r.quote_id].append(i)
            source.setdefault(r.quote_id, row)

        # Quotes that already contain brackets would make the round-trip check
        # ambiguous, so they go to manual review without a model call.
        pending: list[dict] = []
        for qid, idxs in positions.items():
            r = out[idxs[0]]
            if "[" in r.direct_quote or "]" in r.direct_quote:
                _settle(out, idxs, Status.MANUAL_REVIEW_EXISTING_BRACKETS)
                continue
            pending.append({**source[qid], "quote_id": qid, "direct_quote": r.direct_quote})

        if pending:
            self._apply_triage(out, positions, pending, docs)
        for r in out:
            r.final_status = r.final_status or Status.FAILED_TRIAGE_MISSING_ID
        return out

    def _apply_triage(self, out, positions, pending, docs) -> None:
        triaged = self.triage(pending)
        flagged: list[dict] = []
        for item in pending:
            qid = item["quote_id"]
            res = triaged.get(qid) or {"status": Status.FAILED_TRIAGE_MISSING_ID}
            idxs = positions[qid]
            exprs = res.get("expressions") or []
            for i in idxs:
                out[i].triage_expressions = list(exprs)
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
            by_doc[str(item.get("doc_id") or "")].append(item)
            for i in positions[item["quote_id"]]:
                out[i].resolve_prompt_version = RESOLVE_PROMPT_VERSION

        for doc_id, items in by_doc.items():
            doc = docs.get(doc_id)
            if doc is None:
                for item in items:
                    _settle(out, positions[item["quote_id"]], Status.FAILED_DOCUMENT_MISSING)
                continue
            resolved = self.resolve(doc, items)
            for item in items:
                idxs = positions[item["quote_id"]]
                res = resolved.get(item["quote_id"]) or {"status": Status.FAILED_RESOLVE_MISSING_ID}
                self._apply_one(out, idxs, doc, item, res)

    def _apply_one(self, out, idxs, doc, item, res) -> None:
        status, note = res.get("status", ""), res.get("note", "")
        if status.startswith("failed_"):
            _settle(out, idxs, status, note=note)
        elif status == "not_needed":
            _settle(out, idxs, Status.NOT_NEEDED_RESOLVE, note=note)
        elif status == "unresolved":
            _settle(out, idxs, Status.UNRESOLVED, note=note)
        elif status == "resolved":
            built = build_quote_in_context(
                out[idxs[0]].direct_quote, res.get("insertions") or [],
                doc.text, doc.title, item.get("expressions") or [],
            )
            # on success log what was spliced; on failure, what the model sent
            _settle(out, idxs, built.status, note=note, text=built.text,
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


def summarise(rows: Sequence[ContextRow]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for r in rows:
        counts[r.final_status] += 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


# --- I/O and CLI -----------------------------------------------------------


def load_quotes(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    missing = {"doc_id", "direct_quote"} - set(rows[0] if rows else {})
    if missing:
        sys.exit(f"{path}: missing required column(s): {', '.join(sorted(missing))}")
    return rows


def load_documents(path: Path) -> list[Document]:
    """JSONL (one {"doc_id","title","text"} per line) or CSV with those columns."""
    if path.suffix.lower() == ".csv":
        csv.field_size_limit(min(sys.maxsize, 2**31 - 1))
        with path.open(encoding="utf-8-sig", newline="") as f:
            recs = list(csv.DictReader(f))
    else:
        recs = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()]
    return [Document(str(r["doc_id"]), str(r.get("title") or ""), str(r.get("text") or ""))
            for r in recs]


def write_output(path: Path, inputs: Sequence[dict], results: Sequence[ContextRow]) -> None:
    """Input columns first, untouched, then the context columns."""
    added = ["quote_id", "quote_in_context", "final_status", "triage_expressions",
             "insertions", "warnings", "model_note", "triage_prompt_version",
             "resolve_prompt_version", "provider", "model", "run_timestamp"]
    in_cols = [c for c in (inputs[0].keys() if inputs else []) if c not in added]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=in_cols + added)
        w.writeheader()
        for row, r in zip(inputs, results):
            w.writerow({
                **{c: row.get(c, "") for c in in_cols},
                "quote_id": r.quote_id,
                "quote_in_context": r.quote_in_context,
                "final_status": r.final_status,
                "triage_expressions": json.dumps(r.triage_expressions, ensure_ascii=False),
                "insertions": json.dumps([asdict(i) for i in r.insertions], ensure_ascii=False),
                "warnings": json.dumps(r.warnings, ensure_ascii=False),
                "model_note": r.model_note,
                "triage_prompt_version": r.triage_prompt_version,
                "resolve_prompt_version": r.resolve_prompt_version,
                "provider": r.provider, "model": r.model, "run_timestamp": r.run_timestamp,
            })


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Add bracketed context to quotes that lack it.")
    p.add_argument("--quotes", type=Path, required=True,
                   help="CSV: doc_id, direct_quote required; quote_id, speaker, "
                        "organisation, date optional; other columns passed through")
    p.add_argument("--documents", type=Path, required=True,
                   help="JSONL or CSV with doc_id, title, text")
    p.add_argument("--out", type=Path, required=True, help="output CSV")
    p.add_argument("--provider", choices=["anthropic", "openai"], default="anthropic")
    p.add_argument("--model", help=f"default for anthropic: {DEFAULT_ANTHROPIC_MODEL}; "
                                   "required for openai")
    p.add_argument("--cache-dir", type=Path, default=Path(".context_cache"),
                   help="response cache; re-runs with unchanged inputs make no API calls")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--triage-batch", type=int, default=DEFAULT_TRIAGE_BATCH)
    p.add_argument("--max-doc-tokens", type=int, default=DEFAULT_MAX_DOC_TOKENS)
    args = p.parse_args(argv)

    if args.provider == "openai":
        if not args.model:
            p.error("--model is required with --provider openai")
        provider: ModelProvider = OpenAIProvider(args.model)
    else:
        provider = AnthropicProvider(args.model or DEFAULT_ANTHROPIC_MODEL)

    quotes = load_quotes(args.quotes)
    documents = load_documents(args.documents)
    ctx = Contextualiser(provider,
                         cache=None if args.no_cache else ResponseCache(args.cache_dir),
                         triage_batch_size=args.triage_batch,
                         max_doc_tokens=args.max_doc_tokens)
    results = ctx.run(quotes, documents)
    write_output(args.out, quotes, results)

    print(f"Wrote {len(results)} rows to {args.out}")
    for status, n in summarise(results).items():
        print(f"  {status:36s} {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
