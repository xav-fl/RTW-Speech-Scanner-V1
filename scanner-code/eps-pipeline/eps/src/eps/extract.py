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

#: P8 (2026-09-15): a passage qualifies when it is a policy choice that economics
#: research could produce evidence about, in any applied field, and the model
#: writes that research question as its reason (H-99). Replaces P7's narrower
#: "economic substance at the centre" rule (H-98), which was never run. The JEL
#: code list is in the cached system prompt (H-97).
#: P9 (2026-09-15): design details, instruments, scope and causal claims about a
#: specific policy qualify in their own right, and the research question must be
#: about the selected words rather than a policy described elsewhere (H-100).
PROMPT_VERSION = "P9-units-blind"
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

WHAT THE DATASET IS FOR
It records what policymakers are choosing to do, so that it can be compared \
with the research questions governments publish in their Areas of Research \
Interest and learning agendas, and with the research economists produce. \
"Economics" means the whole discipline and its applied fields: public finance, \
labour, health, education, crime and law enforcement, migration, development \
and aid, conflict and defence, industrial organisation and digital markets, \
regulation, environment and energy, urban and transport, family and children, \
political economy. A policy does NOT need to be about money, prices or markets \
for economics research to inform it. Most government policy has implicit \
economics: it changes incentives, behaviour, costs, access or outcomes for \
someone.

A passage QUALIFIES when all three hold:
1. A POLICY CHOICE. The eligible speaker states their own government's position, \
decision, proposal, commitment, target, design choice, or causal belief about \
what a policy does. There is a lever: a rule, ban, programme, eligibility \
condition, service, spending or funding decision, regulation, institution, \
sanction, or intervention.
2. RESEARCHABLE BY ECONOMISTS. You can turn it into a one-line question that an \
applied economist could answer with evidence — about its effects on behaviour \
or outcomes, its costs and benefits, its incentives, who gains and who loses, or \
how best to design or target it. For example:
   "we will ban social media for under 16s" -> Does restricting adolescents' \
social media use improve wellbeing or attainment?
   "new controls on the online sale and delivery of knives" -> Do restrictions \
on online knife sales reduce violent crime?
   "a reduction in initial leave to remain for refugees from five years to two \
and a half" -> How does shorter temporary protection affect refugees' \
employment and integration?
   "I will be asking them to re-examine eligibility for meningitis vaccines" -> \
Which vaccine eligibility rules deliver the most health gain for the cost?
   "every pupil will learn about social media in the classroom" -> Does \
classroom digital-literacy teaching change pupils' online behaviour?
3. SUBSTANTIVE. The selection says what the policy is, and reads as a complete \
statement on its own: who is acting and what they will do ("we will ban social \
media for under 16s"), never a bare fragment ("maintain American leadership in \
low Earth orbit").

THE DETAIL IS THE POLICY. A headline commitment and the design choices that \
implement it are separate observations, and each of these qualifies in its own \
right even when it elaborates a policy you have already selected:
- eligibility and conditions — who qualifies and on what terms ("A clean \
criminal record… No debt to the taxpayer… A history of being in work and paying \
taxes");
- named instruments and mechanisms ("an advanced market commitment to quantum", \
"the first G7 country to issue a Digital Sovereign Bond");
- scope and coverage — who or what is included or exempted;
- causal claims about what a specific policy has done or will do ("our largest \
pension funds invested an additional £10bn… because of the changes that I have \
made"), and stated choices between alternatives ("it's better to spend \
taxpayer's cash building new homes than subsidising buy-to-let landlords").

Do not exclude a passage because its subject is not conventionally "economic". \
Crime, health, schooling, online safety, migration, defence, aid and conflict \
are all fields economists study. Exclude only for the reasons below.

It does NOT qualify when:
- NOTHING IS CHOSEN: ceremony, condolences, congratulations, thanks; readouts \
of meetings and calls ("they discussed regional security"); a statement of \
fact or a statistic with no position taken on it ("the UN appeal is 13 per \
cent funded"); announcements of process or timing with no substance ("the white \
paper is coming soon", "legislation will be brought forward as soon as \
parliamentary time allows", "I have written to the regulator"); appointments.
- THERE IS NO LEVER: slogans, values, aspirations and praise ("an education \
system that captures everything it means to learn"); condemnation, or demands \
made of other governments or parties with no action by the speaker's own \
government; partisan criticism without the speaker's own alternative; a \
description of a policy the speaker opposes, unless they state their own.
- ECONOMICS WOULD NOT BE AMONG THE DISCIPLINES INFORMING IT: military operations \
and tactics, the outcome of an individual court case, threat levels, \
commemorations, constitutional or parliamentary procedure.
- IT IS NOT THE SPEAKER: an interviewer, host, reporter or quoted third party.

If you cannot write the one-line research question, leave the passage out. \
Put that question in "reason".

The question must be about what the SELECTED WORDS state, not about a policy \
described elsewhere in the document. If the words you are about to select only \
praise a policy, name a goal, or say something matters ("making defence an \
engine for jobs and growth", "our land-grant universities are critical in \
educating the next generation"), select the words that describe the policy \
itself instead — or nothing.

SELECTION RULES
- Units must be contiguous and within a single paragraph.
- Select the minimum span that carries the policy claim, with enough context to \
understand it. Prefer one or two units.
- If a paragraph contains two genuinely distinct policy claims, return two \
observations. If several sentences express one claim, return one. A list of \
conditions or instruments that together define one policy is one observation: \
select the whole list, not its first item.
- Only select units marked selectable.
- If nothing qualifies, return an empty list. Documents that produce nothing are \
expected and useful; do not stretch to find something.

OPTIONAL ANCHOR
If the qualifying claim is a clause rather than a whole sentence, you may supply \
"anchor": an exact substring copied character-for-character from the selected \
units. The anchor must itself read as a complete statement, with its subject. \
It is checked by exact match and the observation is dropped if it does not \
match. Omit it if unsure.

Return ONLY JSON, no preamble, no markdown fences:
{"observations": [{"unit_ids": ["D....P003.S002"], "anchor": null, \
"reason": "<the one-line research question, at most 20 words>"}]}
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

Applied fields are economics. A policy on crime, health, schooling, migration, \
online platforms, defence, aid or conflict has an economic research object \
when economists study the effects, costs, incentives or distribution of such \
policies, and it belongs in that applied field — for example K42, I18, I21, \
F22, L86, H56, F35 or D74 — rather than in a catch-all code such as D78 or H83 \
that would fit any government statement.

If the quotation has no defensible economic research or policy object at all — \
it is ceremonial, rhetorical, procedural, or a statement of fact — return an \
empty "codes" list. Returning nothing is a valid answer and the observation is \
set aside; do not reach for a weak code to avoid giving it.

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
        # Built once so it is byte-identical on every classification call, which
        # is what lets the server-side cache be read rather than rewritten.
        self._jel_system = (
            f"{JEL_SYSTEM}\n"
            f"ACTIVE JEL CODES — choose only from these:\n"
            f"{active.prompt_lines()}\n"
        )
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

    def _call(self, system: str, user: str, max_tokens: int = 2000,
              cache_system: bool = False) -> str:
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

        text = self.provider.call(system, user, max_tokens, cache_system=cache_system)

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

        Prompt caching: the code list is the same 30KB on every call, so it is
        part of the SYSTEM prompt, which is cached, and only the quotation
        travels in the user message. It used to sit in the user message AFTER
        the quotation. A cache is a prefix match, so a list placed behind a
        changing quotation can never be read back: every one of an estimated
        4,000 calls in the full run would have paid for the list in full, about
        four fifths of the whole extract's cost (H-97).
        """
        user = (
            f"QUOTATION:\n{quote}\n\n"
            f"{('CONTEXT: ' + context) if context else ''}\n\n"
            'Return {"mechanism": "<a few words>", '
            '"codes": [{"code": "<three characters>", "strength": 3}]}'
        )
        picked_text = self._call(self._jel_system, user, max_tokens=600,
                                 cache_system=True)

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
