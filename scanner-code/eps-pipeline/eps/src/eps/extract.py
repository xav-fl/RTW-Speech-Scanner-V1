"""Extraction: the one stage where a model is involved.

Two things make this stage auditable:

1. The model returns *unit IDs*, never quote text. The quote is reconstructed
   from the frozen document in validate.py, so it is verbatim by construction.
2. JEL classification is a single selection from the flat list of active
   three-character codes. The model picks codes; it never picks a branch, and
   it never supplies a parent or a title, which are looked up from the list.
   A code that is not on the list is refused rather than written.

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
from .jel import ActiveJELList, JELTaxonomy
from anthropic import Anthropic

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

    Both system prompts are hashed, and so is the source of the two methods
    that build user messages: build_user_message() and classify(). Those methods
    contain prompt wording too, and hashing only the system constants leaves
    changes to it invisible in the provenance columns.

    Method source is hashed wholesale, so editing a comment or renaming a local
    variable inside those methods also moves the fingerprint. That is the safe
    direction: a fingerprint that moves without a wording change is noise, but a
    fingerprint that holds still despite one is a false provenance record.

    _refine() used to be hashed here too. It selected within a branch and no
    longer exists.
    """
    parts = [EXTRACT_SYSTEM, JEL_SYSTEM]
    for fn in (
        Extractor.build_user_message,
        Extractor.classify,
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
that produced it. You will be given the full list of active three-character JEL \
codes. Choose from that list only, and return codes exactly as they appear in \
it. Do not invent codes, and do not return a one- or two-character category.

Assign one to three codes. Put the best and most central code first. Add a \
second or third only when it covers a distinct and important part of the \
quotation. Do not pad to three.

Rules:
- When a passage names both a policy area and a policy instrument, classify by \
the area, not the instrument (a tax change to fund schools is education, not \
taxation), unless the instrument itself is the substance of the claim.
- Do not assign C codes unless the statement is actually about measurement, \
data, forecasting, or methodology.
- Do not assign H codes merely because a government official is speaking.
- Do not assign D04 merely because the passage discusses policy.
- Before selecting any code, identify in a few words the specific mechanism, \
instrument, population, or outcome the quotation names — a funding formula, a \
staffing incentive, an eligibility rule, a governance structure, a market \
intervention, and so on. The codes you choose must match that phrase. This \
dataset exists to reveal what policymakers are actually choosing to do, so a \
classification that would fit almost any government statement is not doing its \
job, whatever its title happens to be.

Give each code a match strength describing how well it fits. This is a semantic \
match score, not a probability and not your confidence:
  3 — direct: the code describes a central part of the quotation;
  2 — strong: the code clearly fits an important part, but the quotation is \
broader or less specific;
  1 — weak: the code is plausible, but substantial interpretation is needed.

If the quotation has no defensible economic research or policy object at all, \
return an empty "codes" list. Economic content normally concerns behaviour, \
choice, incentives, allocation, markets, production, welfare, distribution, \
valuation, regulation, or the effects of public policy; a statement is not \
economic merely because an economist could study it. Returning nothing is a \
valid answer and the observation is set aside — do not reach for a weak code to \
avoid giving it.

Return ONLY JSON, no preamble, no markdown fences:
{"mechanism": "<a few words>", "codes": [{"code": "I22", "strength": 3}]}
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
        active: Optional[ActiveJELList] = None,
    ):
        if identity_mode not in IDENTITY_MODES:
            raise ValueError(f"identity_mode must be one of {IDENTITY_MODES}")
        self.tax = taxonomy
        # The dated flat list classification selects from. `taxonomy` is still
        # accepted and still used elsewhere in the pipeline; classification does
        # not read it any more.
        if active is None:
            from .pipeline import load_active_codes
            active = load_active_codes()
        self.active = active
        self.cache = cache
        # Store the client directly for prompt caching support. When client is
        # passed directly (not wrapped in a provider), we can use it with
        # cache_control for cost savings on the large code list.
        self._direct_client = client
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
        """Pick one to three three-character codes from the flat active list.

        One call, one list, no branch. The previous version chose a major
        category first and then searched inside it, which meant a wrong turn at
        the top could not be recovered lower down: the code that actually fitted
        was never on the table. Here every code competes on every call.

        The model returns codes and strengths only. Parents and titles come from
        the list by lookup, so it cannot emit a code that does not exist, cannot
        corrupt a title, and cannot return a level mismatch — the three failure
        modes the old two-stage path spent its recovery logic on.

        Returns (primary, secondary, mechanism). An empty result means the
        classifier found no defensible economic object; the caller leaves the
        assignments empty and validation sets the observation aside.

        Prompt caching: if a client was provided directly (not via provider),
        uses the Anthropic SDK's cache_control to cache the code list across
        calls. The provider.call() fallback does not support caching.
        """
        user = (
            f"QUOTATION:\n{quote}\n\n"
            f"{('CONTEXT: ' + context) if context else ''}\n\n"
            f"ACTIVE JEL CODES — choose only from these:\n"
            f"{self.active.prompt_lines()}\n\n"
            'Return {"mechanism": "<a few words>", '
            '"codes": [{"code": "<three characters>", "strength": 3}]}'
        )

        # Try the cached path first (direct client with cache_control). Falls
        # back to provider.call() if no client was given.
        picked_text = None
        if self._direct_client is not None:
            try:
                response = self._direct_client.messages.create(
                    model=self.model,
                    max_tokens=600,
                    system=[
                        {
                            "type": "text",
                            "text": JEL_SYSTEM,
                            # Cache the system prompt and the list together. The
                            # list is byte-identical on every call, so this is the
                            # big cost win: 30KB paid once, reused across thousands.
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    messages=[
                        {
                            "role": "user",
                            "content": user,
                        }
                    ],
                )
                if response.content and response.content[0].type == "text":
                    picked_text = response.content[0].text
            except Exception:
                # If direct client fails for any reason, fall back to provider.
                pass

        # Fallback: use the provider if no client was given or it failed.
        if picked_text is None:
            picked_text = self._call(JEL_SYSTEM, user, max_tokens=600)

        picked = _parse_json(picked_text)
        mechanism = str(picked.get("mechanism") or "").strip()[:200]

        assignments: list[JELAssignment] = []
        seen: set[str] = set()
        for entry in (picked.get("codes") or [])[:3]:
            if not isinstance(entry, dict):
                continue
            code = str(entry.get("code") or "").strip().upper()
            try:
                strength = int(entry.get("strength") or 0)
            except (TypeError, ValueError):
                strength = 0

            # Selection from a fixed list, then verified against it. A code that
            # is not on the list is dropped rather than written: the old path
            # could recover a real code at the wrong depth, but there are no
            # depths here, so anything unrecognised is simply wrong.
            if code in seen or code not in self.active:
                continue
            if strength not in (1, 2, 3):
                continue
            seen.add(code)
            assignments.append(self.active.assignment(code, match_strength=strength))

        if not assignments:
            return JELAssignment(), [], mechanism
        return assignments[0], assignments[1:3], mechanism

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
