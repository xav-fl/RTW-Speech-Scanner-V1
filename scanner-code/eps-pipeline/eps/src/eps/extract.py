"""Extraction: the one stage where a model is involved.

Two things make this stage auditable:

1. The model returns *unit IDs*, never quote text. The quote is reconstructed
   from the frozen document in validate.py, so it is verbatim by construction.
2. JEL classification follows the project's frozen protocol (v2.0): a status
   and zero to three unordered three-character codes from the dated taxonomy.
   The model never supplies a parent or a title, which are looked up from the
   active list. A code that is not on the list is refused rather than written.

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
#: Which JEL classification protocol stage 2 runs. Recorded on every row apart
#: from PROMPT_VERSION, because PROMPT_VERSION is part of every cache key:
#: relabelling it would throw away the stage 1 cache along with stage 2's. The
#: classify cache moves on its own, since its system prompt changed.
JEL_PROTOCOL_VERSION = "JEL-v2.0"
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
    longer exists. The JEL taxonomy text and jel_context() are hashed because
    both reach the classify prompt.
    """
    parts = [EXTRACT_SYSTEM, JEL_SYSTEM, _reference_text(JEL_TAXONOMY_FILE)]
    for fn in (
        Extractor.build_user_message,
        Extractor.classify,
        Extractor.jel_context,
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

#: JEL classification protocol v2.0 (frozen 15 October 2026), the same text used
#: elsewhere in the project, so both parts classify on identical instructions.
#: It is loaded verbatim from the dated reference file rather than copied in
#: here, so there is one copy to keep in step. Change it only by issuing a new
#: protocol version under a new filename.
JEL_PROTOCOL_FILE = "jel_classification_protocol_v2.0.txt"
#: The dated taxonomy the protocol is run with: the AEA hierarchy, one
#: `code | title` line per level. Its three-character codes are the same 845
#: codes as the active list, with identical titles; Extractor checks this.
JEL_TAXONOMY_FILE = "jel_taxonomy_compact.txt"

#: The protocol's four statuses. Only "coded" carries codes.
JEL_STATUSES = ("coded", "no_defensible_economic_match",
                "not_research_item", "needs_more_context")


def _reference_text(name: str) -> str:
    from .pipeline import DATA_REFERENCE_DIR
    return (DATA_REFERENCE_DIR / name).read_text(encoding="utf-8").strip()


JEL_SYSTEM = _reference_text(JEL_PROTOCOL_FILE) + "\n"


def _check_taxonomy_matches(taxonomy_text: str, active: ActiveJELList) -> None:
    """Refuse to run if the taxonomy the model sees and the list its answers are
    checked against have drifted apart: every active code must appear in the
    taxonomy with the same title, or a correct answer could be refused."""
    shown: dict[str, str] = {}
    for line in taxonomy_text.splitlines():
        code, _, title = line.partition(" | ")
        shown[code.strip()] = title.strip()
    for c in active.codes:
        if shown.get(c.code) != c.title:
            raise ValueError(
                f"{JEL_TAXONOMY_FILE} and {active.source or 'the active list'} "
                f"disagree on {c.code}")


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
        taxonomy_text = _reference_text(JEL_TAXONOMY_FILE)
        _check_taxonomy_matches(taxonomy_text, active)
        # Built once so it is byte-identical on every classification call, which
        # is what lets the server-side cache be read rather than rewritten.
        self._jel_system = (
            f"{JEL_SYSTEM}\n"
            f"JEL TAXONOMY ({JEL_TAXONOMY_FILE}):\n"
            f"{taxonomy_text}\n"
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
    ) -> tuple[JELAssignment, list[JELAssignment], str, str]:
        """Classify one quote under JEL classification protocol v2.0.

        The protocol is the system prompt, verbatim, followed by the dated
        taxonomy; both are the same on every call, so they are cached and only
        the item travels in the user message. The quote is sent as the
        protocol's 'Specific item to classify', with `context` as its fixed
        context, one item per call.

        The model returns a status and zero to three UNORDERED codes, each with
        a strength and a one-sentence rationale. Parents and titles come from
        the active list by lookup; a code that is not on it is dropped and the
        drop is noted in the comments. Codes are stored alphabetically, so
        `primary` is the alphabetically first code, not the most important.

        Returns (primary, secondary, status, comments). Anything but a "coded"
        status comes back with empty assignments, and validation sets the
        observation aside with the status as its reason. An unusable response
        comes back with an empty status.
        """
        item_id = "item_1"
        lines = [f"item_id: {item_id}"]
        if context:
            lines += ["Fixed context:", context]
        lines += ["Specific item to classify:", quote]
        user = "\n".join(lines) + "\n"
        text = self._call(self._jel_system, user, max_tokens=1200,
                          cache_system=True)

        data = _parse_json(text)
        items = data.get("items") if isinstance(data, dict) else None
        record = next((r for r in (items or []) if isinstance(r, dict)
                       and str(r.get("item_id", "")).strip() == item_id), None)
        if record is None and items and isinstance(items[0], dict):
            record = items[0]
        if record is None:
            return JELAssignment(), [], "", "[pipeline] no record for the item"

        status = str(record.get("status") or "").strip()
        comments = str(record.get("comments") or "").strip()[:300]
        notes: list[str] = []
        if status not in JEL_STATUSES:
            notes.append(f"unknown status {status!r}")
            status = ""

        assignments: list[JELAssignment] = []
        seen: set[str] = set()
        raw_codes = [e for e in (record.get("codes") or []) if isinstance(e, dict)]
        if status != "coded" and raw_codes:
            notes.append(f"{len(raw_codes)} code(s) returned with status "
                         f"{status or 'unknown'} were dropped")
            raw_codes = []
        for entry in raw_codes:
            code = str(entry.get("code") or "").strip().upper()
            try:
                strength = int(entry.get("strength") or 0)
            except (TypeError, ValueError):
                strength = 0
            if code in seen:
                continue
            if code not in self.active:
                notes.append(f"dropped {code!r}: not on the active list")
                continue
            if strength not in (1, 2, 3):
                notes.append(f"dropped {code}: strength {strength!r}")
                continue
            seen.add(code)
            a = self.active.assignment(code, match_strength=strength)
            a.rationale = str(entry.get("rationale") or "").strip()[:300]
            assignments.append(a)
        if len(assignments) > 3:
            notes.append(f"{len(assignments)} valid codes returned; the protocol "
                         f"allows three, so the first three given were kept")
            assignments = assignments[:3]

        if notes:
            comments = " ".join(filter(None, [comments,
                                              "[pipeline] " + "; ".join(notes)]))
        if not assignments:
            return JELAssignment(), [], status, comments
        # Unordered by protocol; alphabetical for convenience only.
        assignments.sort(key=lambda a: a.detailed_code)
        return assignments[0], assignments[1:3], status, comments

    def jel_context(self, doc: Document) -> str:
        """The protocol's fixed context for a quote from `doc`.

        It says what kind of item this is, since the protocol was written for
        research questions. Blind mode withholds the title, as stage 1 does.
        """
        lines = [f"A verbatim passage from a government {doc.doc_type} "
                 f"dated {doc.pub_date.isoformat()}, in which the speaker "
                 f"states a policy position."]
        if self.identity_mode == "full" and doc.title:
            lines.append(f"Document title: {doc.title}")
        return "\n".join(lines)

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
                primary, secondary, status, comments = self.classify(
                    quote, context=self.jel_context(doc))
                obs.primary = primary
                obs.secondary = secondary
                obs.jel_status = status
                obs.jel_comments = comments
                obs.jel_protocol = JEL_PROTOCOL_VERSION
            observations.append(obs)
        return observations
