"""Extraction: the one stage where a model is involved.

Two things make this stage auditable:

1. The model returns *unit IDs*, never quote text. The quote is reconstructed
   from the frozen document in validate.py, so it is verbatim by construction.
2. JEL classification is a two-stage selection from the frozen taxonomy — pick
   a major category from the full list, then a code from that branch only. The
   model can never emit a code that does not exist.

The document is supplied in full; the model does no searching. Every call is
cached by a hash of its inputs so a re-run replays rather than re-queries.
"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Optional
import inspect

from .models import Document, JELAssignment, Observation
from .jel import JELTaxonomy
from .providers import AnthropicProvider, ModelProvider

PROMPT_VERSION = "P6-units-blind"
DEFAULT_MODEL = "claude-sonnet-4-6"

# What the model is told about who is speaking.
#   "blind" (default) — document text, type and date only. There is published
#     evidence that LLMs use party cues when evaluating political statements,
#     and the pipeline already knows the speaker from the officeholder join, so
#     the model does not need to be told.
#   "full" — includes institution, title and speaker name. Use this to run the
#     paired robustness test: same corpus, both modes, compare selections.
IDENTITY_MODES = ("blind", "full")

def prompt_fingerprint() -> str:
    """A short hash of the actual prompt text.

    PROMPT_VERSION is a label you set by hand and may forget to change. This is
    computed from the prompts themselves, so every output row records exactly
    which wording produced it whether or not you remembered to relabel.

    Both system prompts are hashed, and so is the source of the three methods
    that build user messages: build_user_message(), classify() and _refine().
    Those methods contain prompt wording too — the residual-code guidance in
    _refine() is prompt text by any reasonable definition — and hashing only the
    system constants leaves changes to it invisible in the provenance columns.

    Method source is hashed wholesale, so editing a comment or renaming a local
    variable inside those methods also moves the fingerprint. That is the safe
    direction: a fingerprint that moves without a wording change is noise, but a
    fingerprint that holds still despite one is a false provenance record.
    """
    parts = [EXTRACT_SYSTEM, JEL_SYSTEM]
    for fn in (
        Extractor.build_user_message,
        Extractor.classify,
        Extractor._refine,
    ):
        parts.append(inspect.getsource(fn))
    return hashlib.sha256("".join(parts).encode("utf-8")).hexdigest()[:12]

EXTRACT_SYSTEM = """\
You identify economics-relevant policy statements in documents published by \
government agencies, for an academic research dataset.

You will be given a document split into numbered sentence units. Your job is to \
return the unit IDs of passages that qualify. You never quote text: the quote is \
reconstructed from the unit IDs by the calling program.

A passage QUALIFIES when the eligible speaker expresses a policy position, \
priority, proposal, commitment, target, implementation choice, or causal belief \
with a substantive connection to economic behaviour, institutions, markets, \
incentives, resource allocation, distribution, government activity, or \
measurable economic outcomes.

It does NOT qualify when it is:
- ceremonial: condolences, congratulations, thanks, event logistics;
- a general value or aspiration with no policy or mechanism ("opportunity matters");
- a passing mention of growth, jobs, investment, cost, efficiency or opportunity \
with no policy position, mechanism, intended outcome, target, trade-off or causal claim;
- partisan criticism that does not state the speaker's own position;
- a description of a policy the speaker opposes, unless they also state their \
own alternative;
- purely legal, diplomatic or security content with no clear economic dimension;
- spoken by an interviewer, host, or quoted third party rather than the speaker.

SELECTION RULES
- Units must be contiguous and within a single paragraph.
- Select the minimum span that carries the policy claim, with enough context to \
understand it. Prefer one or two units.
- If a paragraph contains two genuinely distinct policy claims, return two \
observations. If several sentences express one claim, return one.
- Only select units marked selectable.
- If nothing qualifies, return an empty list. Documents that produce nothing are \
expected and useful; do not stretch to find something.

OPTIONAL ANCHOR
If the qualifying claim is a clause rather than a whole sentence, you may supply \
"anchor": an exact substring copied character-for-character from the selected \
units. It is checked by exact match and the observation is dropped if it does not \
match. Omit it if unsure.

Return ONLY JSON, no preamble, no markdown fences:
{"observations": [{"unit_ids": ["D....P003.S002"], "anchor": null, "reason": "<10 words>"}]}
"""

JEL_SYSTEM = """\
You assign JEL classifications to a quoted policy statement for an academic \
economics dataset.

Classify the economic content of the QUOTATION, not the identity of the agency \
that produced it. Choose from the supplied list only. Do not invent codes.

Rules:
- When a passage names both a policy area and a policy instrument, classify by \
the area, not the instrument (a tax change to fund schools is education, not \
taxation), unless the instrument itself is the substance of the claim.
- Do not assign C codes unless the statement is actually about measurement, \
data, forecasting, or methodology.
- Do not assign H codes merely because a government official is speaking.
- Do not assign D04 merely because the passage discusses policy.
- Assign a secondary classification only when there is an additional, \
substantively important economic dimension. At most two. Fewer is better.
- Before selecting a code at any level, identify in a few words the specific \
mechanism, instrument, population, or outcome the quotation names — a funding \
formula, a staffing incentive, an eligibility rule, a governance structure, a \
market intervention, and so on. The code you choose must match that phrase. \
This dataset exists to reveal what policymakers are actually choosing to do, \
so a classification that would fit almost any government statement is not \
doing its job, whatever its title happens to be.

Return ONLY JSON, no preamble, no markdown fences:
{"primary": "<code>", "secondary": ["<code>", "<code>"]}
"""


class ResponseCache:
    """Content-addressed cache of model responses.

    Committing this to the repo is what makes a third party's re-run
    byte-identical: they replay the cache rather than re-querying a model whose
    outputs are not bitwise reproducible.
    """

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(**parts) -> str:
        blob = json.dumps(parts, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def get(self, key: str) -> Optional[dict]:
        p = self.root / key[:2] / f"{key}.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        return None

    def put(self, key: str, value: dict) -> None:
        p = self.root / key[:2] / f"{key}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def render_units(doc: Document, max_chars: int = 120_000) -> str:
    """Render the document as an ID-prefixed unit list for the model."""
    lines: list[str] = []
    total = 0
    last_para = None
    for u in doc.units:
        if u.para_idx != last_para:
            lines.append("")
            last_para = u.para_idx
        mark = "" if u.attributable else "  [not selectable: not the speaker's words]"
        line = f"{u.unit_id}: {u.text}{mark}"
        total += len(line)
        if total > max_chars:
            lines.append("[... document truncated ...]")
            break
        lines.append(line)
    return "\n".join(lines).strip()


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object in response: {text[:200]!r}")
    return json.loads(text[start:end + 1])


class Extractor:
    """Everything below this line is provider-agnostic.

    `provider` is anything satisfying `ModelProvider` (see providers.py) — it
    can be Anthropic, Mistral, or a fake with canned responses. Extraction
    logic, JSON parsing, JEL selection and caching behave identically no
    matter which one is passed in.
    """

    def __init__(
        self,
        taxonomy: JELTaxonomy,
        provider: Optional[ModelProvider] = None,
        client=None,
        model: str = DEFAULT_MODEL,
        cache: Optional[ResponseCache] = None,
        prompt_version: str = PROMPT_VERSION,
        identity_mode: str = "blind",
    ):
        if identity_mode not in IDENTITY_MODES:
            raise ValueError(f"identity_mode must be one of {IDENTITY_MODES}")
        self.tax = taxonomy
        self.cache = cache
        self.prompt_version = prompt_version
        self.identity_mode = identity_mode

        # `provider` is the current way in. `client`/`model` are kept working
        # for existing scripts and tests that construct an Anthropic client
        # directly — they are wrapped in an AnthropicProvider automatically.
        if provider is not None:
            self.provider = provider
        else:
            self.provider = AnthropicProvider(model=model, client=client)
        self.model = getattr(self.provider, "model", model)

    def _call(self, system: str, user: str, max_tokens: int = 2000) -> str:
        key = None
        if self.cache is not None:
            key = ResponseCache.key(
                provider=self.provider.name, model=self.model,
                system=system, user=user,
                prompt_version=self.prompt_version,
                identity_mode=self.identity_mode,
            )
            hit = self.cache.get(key)
            if hit is not None:
                return hit["text"]

        text = self.provider.call(system, user, max_tokens)

        if self.cache is not None and key is not None:
            self.cache.put(
                key, {"text": text, "model": self.model, "provider": self.provider.name}
            )
        return text

    # -- stage 1: which passages -------------------------------------------

    def build_user_message(self, doc: Document, speaker: str) -> str:
        """Assemble the extraction prompt.

        In blind mode the speaker, institution and document title are withheld,
        so the judgement is made on the text rather than on who is speaking.
        Document type and date are kept: type governs the attribution rules and
        date is needed to read tense correctly.
        """
        header = [
            f"DOCUMENT TYPE: {doc.doc_type}",
            f"DATE: {doc.pub_date.isoformat()}",
        ]
        if self.identity_mode == "full":
            header = [
                f"INSTITUTION: {doc.institution}",
                f"COUNTRY: {doc.country}",
                f"ELIGIBLE SPEAKER: {speaker}",
                f"TITLE: {doc.title}",
            ] + header
        else:
            header.append(
                "NOTE: the speaker and institution are withheld deliberately. "
                "Judge the text on its own terms. Treat first-person plural "
                "statements as the eligible speaker's own words."
            )
        return "\n".join(header) + f"\n\nDOCUMENT UNITS:\n{render_units(doc)}\n"

    def select_units(self, doc: Document, speaker: str) -> list[dict]:
        user = self.build_user_message(doc, speaker)
        raw = self._call(EXTRACT_SYSTEM, user, max_tokens=3000)
        data = _parse_json(raw)
        out = []
        for o in data.get("observations", []):
            ids = [str(i).strip() for i in (o.get("unit_ids") or [])]
            if ids:
                out.append({
                    "unit_ids": ids,
                    "anchor": o.get("anchor") or None,
                    "reason": str(o.get("reason") or "").strip()[:200],
                })
        return out

    # -- stage 2: JEL ------------------------------------------------------

    def classify(
        self, quote: str, context: str = ""
    ) -> tuple[JELAssignment, list[JELAssignment], str]:
        majors = self.tax.majors()
        # Each major with its two-character subcategories nested underneath,
        # so the branch is chosen knowing what is inside it rather than from
        # titles alone. Three-character codes are left to _refine().
        lines: list[str] = []
        for c in majors:
            lines.append(f"{c.code} — {c.title}")
            for sub in self.tax.subcategories(c.code):
                lines.append(f"  {sub.code} — {sub.title}")
        major_list = "\n".join(lines)
        user = (
            f"QUOTATION:\n{quote}\n\n"
            f"{('CONTEXT: ' + context) if context else ''}\n\n"
            f"Choose the single major category whose subtree best fits the "
            f"economic content, and up to two others only if substantively "
            f"justified. The subcategories are listed under each major so you "
            f"can see what competes with it.\n\nMAJOR CATEGORIES:\n{major_list}\n\n"
            'Return {"primary": "<letter>", "secondary": ["<letter>"]}'
        )
        top = _parse_json(self._call(JEL_SYSTEM, user, max_tokens=500))

        major, hint = self._resolve_major(str(top.get("primary", "")).strip())
        primary, mechanism = self._refine(quote, major, sub_hint=hint)
        secondary: list[JELAssignment] = []
        for code in (top.get("secondary") or [])[:2]:
            sec_major, sec_hint = self._resolve_major(str(code).strip())
            a, _ = self._refine(quote, sec_major, sub_hint=sec_hint)
            if not a.is_empty() and a.major_code != primary.major_code:
                secondary.append(a)
        # Only the primary branch's phrase is kept: it is the one attached to
        # the code that lands in `jel_primary_*`.
        return primary, secondary, mechanism

    def _resolve_major(self, code: str) -> tuple[str, str]:
        """Resolve whatever the model returned in a major-category slot.

        classify() asks for a single letter, but it now shows subcategories
        alongside the majors, and a model reading that list answers "I2" often
        enough to matter. validate_jel() rejects a non-level-1 major outright,
        which loses the whole observation -- the same trade _refine() already
        refuses one level down, and the cost is higher here because a bad major
        takes the row with it rather than just its specificity.

        So walk up instead of failing: a level-2 code yields its parent major
        and survives as a subcategory hint, and a level-3 code yields both of
        its ancestors. A code that is not in the frozen taxonomy at all is
        still dropped -- recovery applies to real codes at the wrong depth,
        never to invented ones.

        Returns (major, sub_hint), both empty when nothing is recoverable.
        """
        node = self.tax.by_code.get(code)
        if node is None:
            return "", ""
        if node.level == 1:
            return code, ""
        if node.level == 2:
            return node.parent, code
        parent = self.tax.by_code.get(node.parent)
        if parent is None or parent.level != 2:
            return "", ""
        return parent.parent, node.parent

    def _refine(self, quote: str, major: str,
                sub_hint: str = "") -> tuple[JELAssignment, str]:
        """Given a major category, pick a subcategory and detailed code from
        that branch only.

        `sub_hint` is a subcategory the model already named in classify(). It
        is deliberately not shown in the prompt: this variant changes parsing
        only, so the wording stays identical to P5 and any movement in the
        numbers is attributable to the fix rather than to new instructions.
        It is used as a fallback when this call's own answer does not survive
        verification, so a level-2 answer upstream recovers specificity that
        would otherwise be cleared to a bare major.

        Returns the assignment and the `mechanism` phrase the model stated
        before naming a code. The phrase is recorded, never fed back in.
        """
        if not major or major not in self.tax.by_code:
            return JELAssignment(), ""

        # Verified against the taxonomy on the way in, and discarded unless it
        # is a real subcategory sitting under this major.
        if sub_hint and (sub_hint not in self.tax.by_code
                         or self.tax.by_code[sub_hint].level != 2
                         or self.tax.by_code[sub_hint].parent != major):
            sub_hint = ""

        branch: list[str] = []
        for sub in self.tax.subcategories(major):
            branch.append(f"{sub.code} — {sub.title}")
            for det in self.tax.detailed(sub.code):
                branch.append(f"  {det.code} — {det.title}")
        if not branch:
            return self.tax.fill_titles(JELAssignment(major_code=major)), ""

        user = (
            f"QUOTATION:\n{quote}\n\n"
            f"Within major category {major}, choose the most specific code the "
            f"quotation clearly supports. Prefer a three-character code when it "
            f"clearly fits; otherwise give only the two-character subcategory "
            f"and leave 'detailed' empty. Do not stretch for specificity.\n\n"
            f"First, in a few words, name the specific mechanism, instrument, "
            f"population, or outcome the quotation names. Then check every code "
            f"in the list below and choose the one whose title most precisely "
            f"matches what you just named.\n\n"
            f"AVAILABLE CODES:\n" + "\n".join(branch) + "\n\n"
            'Return {"mechanism": "<a few words>", "sub": "<code>", '
            '"detailed": "<code or empty>"}'
        )
        picked = _parse_json(self._call(JEL_SYSTEM, user, max_tokens=400))
        mechanism = str(picked.get("mechanism") or "").strip()[:200]
        sub = str(picked.get("sub", "")).strip()
        det = str(picked.get("detailed", "")).strip()

        # Selection from a fixed list, then verified against the taxonomy.
        #
        # The prompt asks for a two-character code in "sub" and a
        # three-character one in "detailed", but both are shown in one indented
        # list above and the model sometimes returns a detailed code in the
        # "sub" slot. Demote it and recover its parent here, rather than
        # passing a level mismatch to validate_jel(), which rejects the whole
        # observation -- losing a quotation that has already passed every
        # structural check.
        known = self.tax.by_code.get(sub)
        if known is not None and known.level == 3:
            det = det or sub
            sub = known.parent

        # Levels are checked, not only membership. A code that exists but sits
        # at the wrong depth fails JELTaxonomy.check() later; clearing it here
        # costs specificity, whereas keeping it costs the observation.
        if sub and (sub not in self.tax.by_code
                    or self.tax.by_code[sub].level != 2
                    or self.tax.by_code[sub].parent != major):
            sub = ""

        # Nothing usable came back, but classify() had already named a
        # subcategory under this major. Falling back to it beats emitting a
        # bare major code, and it is the same verified taxonomy entry either
        # way. The detailed code is re-checked against it below.
        if not sub and sub_hint:
            sub = sub_hint

        if det and (det not in self.tax.by_code
                    or self.tax.by_code[det].level != 3
                    or self.tax.by_code[det].parent != sub):
            det = ""

        return self.tax.fill_titles(
            JELAssignment(major_code=major, sub_code=sub, detailed_code=det)
        ), mechanism

    # -- orchestration -----------------------------------------------------

    def extract(self, doc: Document, speaker: str, run_id: str = "") -> list[Observation]:
        from .validate import reconstruct_quote

        picks = self.select_units(doc, speaker)
        observations: list[Observation] = []
        for p in picks:
            obs = Observation(
                doc_id=doc.doc_id,
                unit_ids=p["unit_ids"],
                anchor=p["anchor"],
                reason=p.get("reason", ""),
                provider=self.provider.name,
                model_id=self.model,
                prompt_version=self.prompt_version,
                prompt_sha=prompt_fingerprint(),
                run_id=run_id,
                identity_mode=self.identity_mode,
            )
            # Classify against the reconstructed quote, so the model classifies
            # the same text that will appear in the dataset.
            quote, reason = reconstruct_quote(doc, obs.unit_ids, obs.anchor)
            if not reason:
                context = doc.title if self.identity_mode == "full" else ""
                primary, secondary, mechanism = self.classify(quote, context=context)
                obs.primary = primary
                obs.secondary = secondary
                obs.mechanism = mechanism
            observations.append(obs)
        return observations
