"""Intention tagging: what the speaker is doing with a kept quote.

Extraction records *what* a quote is about (agency, date, JEL topics). This
stage records what the speaker is *doing* with it — committing to an action,
reporting one, weighing an option, ruling one out, calling on others, or only
stating a view — from the fixed codebook in INTENTION_CODEBOOK.md.

It mirrors the context stage (context.py): the provider is the only seam, every
call goes through the same content-addressed `ResponseCache`, and every quote
that enters leaves with exactly one outcome. Three properties make it auditable:

1. It never adds or removes a quote. One `IntentionResult` comes out per quote
   in, in the same order.
2. Code, not the model, decides whether a tag stands. The label pairing, the
   evidence type and the flag cues are checked by `IntentionResult` itself; the
   cues are checked here against the exact text that was sent.
3. A tag that fails any check is recorded as `failed` with a named reason and
   reaches the release as "Not tagged". It is never defaulted to a real label.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

from .extract import DEFAULT_MODEL, ResponseCache, _parse_json
from .models import (
    BROAD_CODES, Document, IntentionFailure, IntentionInvalid, IntentionResult,
)
from .providers import AnthropicProvider, ModelProvider, ProviderStopped

INTENTION_PROMPT_VERSION = "I1"

#: Units of surrounding text sent either side of the quote's own units.
CONTEXT_UNITS_BEFORE = 2
CONTEXT_UNITS_AFTER = 1

#: The answer is one small JSON object; this is several times its size.
MAX_TOKENS = 1200

INTENTION_PROMPT = """\
You are tagging the intention of a quotation from a government agency head.
The quotation has already been extracted and verified. Do not judge whether it
is relevant, correct or important. Your only task is to classify what the
speaker is doing with the statement.

You will receive:
- METADATA: agency, speaker, document title, document type, publication date
- QUOTE: the exact quotation to classify
- GLOSS: a bracketed clarification of references in the quote (may be absent)
- CONTEXT: text immediately before and after the quote in the same document

Classify the QUOTE. Use the CONTEXT and GLOSS only to decide tense, actor and
whether an action is new, existing, undecided or ruled out.

Work through the questions in the order given and stop at the first "yes".
Apply the boundary rules. If the QUOTE and CONTEXT together do not settle
the label, answer "unclear". Do not guess.

Every cue you give must be copied exactly from the QUOTE or CONTEXT.

Return JSON only, with no preamble and no Markdown code fences, in exactly
this form:

{
  "broad": "<broad code>",
  "sub": "<sub code, or null>",
  "evidence_type": "<public_consultation | expert_referral | research_or_data, or null>",
  "secondary_broad": "<broad code, or null>",
  "secondary_sub": "<sub code, or null>",
  "cue": "<exact words that determined the label>",
  "has_quantified_target": <true | false>,
  "target_cue": "<exact words, or null>",
  "claims_causal_effect": <true | false>,
  "causal_cue": "<exact words, or null>",
  "rationale": "<one sentence>"
}

LABELS, QUESTION ORDER, BOUNDARY RULES, FLAG RULES AND EXAMPLES:

1. LABELS

Each quote receives one broad code and, where listed, one sub code. Use the
codes exactly as written.

broad code                   sub codes
commits_to_action            announces_decision | pledges_future_action | makes_conditional_commitment
reports_existing_action      completed_action | outcome | ongoing_implementation
considers_open_option        preferred_option | no_stated_preference
rules_out_option             (none: sub is null)
calls_on_others              evidence | other_states | private_actors
states_view_without_action   describes_problem | value_judgement
unclear                      (none: sub is null)

evidence_type: one of public_consultation, expert_referral, research_or_data.
Required when sub = evidence, and must be null otherwise.

secondary_broad / secondary_sub: another intention the passage also expresses
but which the question order overrode (null if none; same valid pairs as above,
excluding unclear).

Flags (true / false): has_quantified_target, claims_causal_effect.

2. QUESTION ORDER

Label the QUOTE. Use the CONTEXT only to decide tense, actor and status. Ask
the questions in order and stop at the first "yes".

Q1. Does the speaker ask others to supply evidence, views, data or advice?
    -> calls_on_others / evidence. This includes public or stakeholder
    consultations, commitments to seek views, referrals to advisory or
    regulatory bodies (e.g. Ofcom, the JCVI, the Financial Policy Committee),
    and requests for research, data or evaluation. Set evidence_type. This
    question takes precedence over all others; record any other intention in
    secondary_broad / secondary_sub.
Q2. Does the speaker ask someone other than their own government to act?
    -> calls_on_others / other_states (foreign governments, international
    bodies, "the international community") or private_actors (firms,
    platforms, households, the public). Exception: if the passage also states
    the speaker's own government's response should the others not comply, use
    commits_to_action / makes_conditional_commitment instead.
Q3. Does the passage state a view with no action by anyone?
    -> states_view_without_action / describes_problem (describes a problem or
    state of affairs) or value_judgement (a value, fairness or trade-off
    judgment).
Q4. Does the speaker rule an option out, or decline to adopt it?
    -> rules_out_option.
Q5. Is the option still undecided?
    -> considers_open_option / preferred_option (a preference is stated:
    "minded to", "strongly minded to", "our intention, subject to
    consultation", "we have proposed") or no_stated_preference ("considering",
    "exploring", "looking at", "reviewing whether").
Q6. Was the action taken, or already under way, before this document?
    -> reports_existing_action / completed_action (a completed action),
    outcome (a claimed result or effect, e.g. figures achieved) or
    ongoing_implementation (implementation of an existing policy is in
    progress: "we are rolling out", "is implementing").
Q7. Otherwise
    -> commits_to_action / announces_decision (the decision is taken or made
    public in this document: "today", "I can announce", "I can confirm", "this
    week", or a press release's own announcement such as "Today's action" or
    "This investment") or pledges_future_action (a promise of future action
    with no decision made in this document: "we will", "I will", "legislation
    will be brought forward").

If the quote and context together do not settle the label, use unclear. Do not
guess.

3. BOUNDARY RULES

- Consultation on details of a decided policy: Q1 applies -> calls_on_others /
  evidence. Record the decided policy as secondary_broad / secondary_sub if the
  quote states it.
- The speaker's own organisation reviewing something without asking anyone
  else (e.g. "take a deeper dive into the services provided") is not an
  evidence request. Skip Q1 and continue down the order.
- Ambiguous "we": if the actor is not identifiably the speaker's own government
  (e.g. "we" meaning the international community), treat it as others acting
  -> Q2, other_states.
- Press-release effect statements ("This investment will...", "The new digital
  ID will..."): the action is announced in the document -> commits_to_action /
  announces_decision. The effect claim sets claims_causal_effect = true.
- Fragments with no tense (lists such as "Expanding free school meals, rolling
  out..."): decide from the context. If the context does not settle it ->
  unclear.
- Mixed passages: apply the question order; the first "yes" wins. Record the
  most important other intention in secondary_broad / secondary_sub.

4. FLAG RULES

has_quantified_target = true if the quote commits to a measurable outcome with
a number or a deadline.
- true: "cut the disadvantage gap in half"; "our goal of 1 million
  apprentices"; "a target of 10,000 homes a year by the end of this
  Parliament"; "clean power by 2030".
- false: spending amounts alone ("£200 million"); figures already achieved
  ("net migration fall by nearly 70%"); deadlines for process steps rather
  than outcomes ("within months", "from September").

claims_causal_effect = true if the quote links an action, policy or condition
to a specific outcome, whether as a result, an intended effect or an
explanation.
- true: "because of the changes that I have made"; "to bring borrowing costs
  down"; "capping ground rent – helping millions of leaseholders by saving them
  money"; "to better support compliance".
- false: the quote names actions without effects, or the only outcome is a
  vague aim ("securing a safer future for the next generation", "to get the
  job done").

Each flag set to true needs a cue (target_cue / causal_cue): the exact words
that justify it. A flag set to false has a null cue.

5. EXAMPLES (abridged where marked ...)

commits_to_action / announces_decision:
  "Today, I can announce that I am suspending certain visa routes for a further
  4 countries..."
commits_to_action / announces_decision:
  "So I can confirm today, that we will open two SFI application windows this
  year."
commits_to_action / pledges_future_action:
  "we will ban social media companies providing their services to under 16s"
commits_to_action / pledges_future_action; has_quantified_target = true:
  "I will cut the disadvantage gap in half."
commits_to_action / makes_conditional_commitment:
  "I expect all platforms to abide by Ofcom ’s new Violence Against Women and
  Girls (VAWG) guidance and if they do not, I am prepared to go further."
reports_existing_action / completed_action:
  "we created an Independent Prevent Commissioner."
reports_existing_action / completed_action; claims_causal_effect = true:
  "I repaired the public finances, whilst setting out a path of fiscal
  consolidation to bring borrowing costs down"
reports_existing_action / outcome; claims_causal_effect = true:
  "our largest pension funds invested an additional £10bn into private markets
  because of the changes that I have made"
reports_existing_action / ongoing_implementation; claims_causal_effect = true:
  "We’re rolling out Best Start Family Hubs so that parents can get the support
  they need."
considers_open_option / preferred_option:
  "Our intention, subject to consultation, is that the point at which
  settlement is possible will now vary."
considers_open_option / preferred_option:
  "I am also strongly minded to bring in default overnight curfews and breaks
  in infinite scrolling for 16- and 17-year-olds."
considers_open_option / no_stated_preference:
  "So, we’re considering ways to address this such as an agreement value cap."
rules_out_option:
  "As for a flat-rate scheme that would cost up to £10.3 billion and would
  simply not be right or fair, given it would be paid to the vast majority who
  were aware of the changes."
calls_on_others / evidence (evidence_type = expert_referral; secondary =
commits_to_action / pledges_future_action); claims_causal_effect = true:
  "So we will introduce more highly effective age assurance measures to better
  support compliance, and I have asked Ofcom to share proposals on these within
  months."
calls_on_others / evidence (evidence_type = public_consultation):
  "this government is consulting on whether to remove children’s access to
  social media entirely."
calls_on_others / other_states:
  "arms restrictions need to be enforced and extended"
calls_on_others / other_states (ambiguous "we"); claims_causal_effect = true:
  "We need to redouble our efforts to ensure countries can mobilise their own
  finance, spend well, borrow responsibly and manage shocks effectively, to
  build sustainable economies."
calls_on_others / private_actors:
  "American households must prioritize whole, nutrient-dense foods...and
  dramatically reduce highly processed foods."
states_view_without_action / describes_problem:
  A passage consisting only of a sentence such as "Right now, a quarter of the
  money goes to just 4% of farms."
states_view_without_action / value_judgement:
  "it’s better to spend taxpayer’s cash building new homes than subsidising
  buy-to-let landlords"
unclear:
  "Expanding free school meals, rolling out new free breakfast clubs, ending
  the two-child limit, fighting the disgrace of child poverty." (when the
  context does not settle whether these are promises or achievements)
"""


# --- request ---------------------------------------------------------------


def neighbour_context(doc: Optional[Document], unit_ids: Sequence[str]
                      ) -> Optional[tuple[str, str]]:
    """Text of up to two units before and one after the quote's own units.

    Returns (before, after), or None when the units cannot be found — the doc
    is missing, or a unit ID is not in it — so the caller can fall back to the
    gloss and say so in `context_source`. Neighbours are taken in document
    order across paragraph breaks, and include units that are not the
    speaker's own words: they are context for tense and actor, not quotation.
    """
    if doc is None or not unit_ids or not doc.units:
        return None
    index = {u.unit_id: i for i, u in enumerate(doc.units)}
    try:
        positions = [index[u] for u in unit_ids]
    except KeyError:
        return None
    first, last = min(positions), max(positions)
    before = doc.units[max(0, first - CONTEXT_UNITS_BEFORE):first]
    after = doc.units[last + 1:last + 1 + CONTEXT_UNITS_AFTER]
    return " ".join(u.text for u in before), " ".join(u.text for u in after)


def build_request(row: Mapping, doc: Optional[Document]
                  ) -> tuple[str, tuple[str, ...], str]:
    """The user message for one quote, and the context text actually sent.

    Returns (message, context_texts, context_source). The before and after
    texts come back separately, so a cue cannot straddle the two. Blocks are labelled METADATA,
    QUOTE, GLOSS and CONTEXT as the prompt describes. GLOSS is left out when
    it says nothing the quote does not.
    """
    quote = str(row.get("direct_quote", "") or "")
    gloss = str(row.get("quote_in_context", "") or "")
    unit_ids = str(row.get("unit_ids", "") or "").split()

    found = neighbour_context(doc, unit_ids)
    if found is None:
        context, source = (gloss or quote,), "quote_only"
        context_block = context[0]
    else:
        before, after = found
        context, source = (before, after), "units"
        context_block = (f"Before the quote: {before or '(start of document)'}\n"
                         f"After the quote: {after or '(end of document)'}")

    parts = [
        "METADATA\n"
        f"agency: {row.get('agency', '')}\n"
        f"speaker: {row.get('speaker', '')}\n"
        f"document title: {row.get('document_title', '')}\n"
        f"document type: {row.get('document_type', '')}\n"
        f"publication date: {row.get('date', '')}",
        f"QUOTE\n{quote}",
    ]
    if gloss and gloss != quote:
        parts.append(f"GLOSS\n{gloss}")
    parts.append(f"CONTEXT\n{context_block}")
    return "\n\n".join(parts), context, source


def intention_prompt_fingerprint() -> str:
    """Short hash of the prompt and the code that writes the user message.

    Computed as `extract.prompt_fingerprint()` is: the system prompt plus the
    source of the method building the user message, which carries wording too.
    """
    parts = [INTENTION_PROMPT, inspect.getsource(build_request)]
    return hashlib.sha256("".join(parts).encode("utf-8")).hexdigest()[:12]


# --- checks ----------------------------------------------------------------

#: Straight and curly quotation marks and apostrophes are one shape for the cue
#: check. A model reliably retypes a curly apostrophe as a straight one (see
#: context.fold_punctuation). Nothing else is folded: case, dashes and wording
#: must match exactly.
_QUOTE_MARKS = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
})
_WS_RE = re.compile(r"\s+")


def normalise_for_cue(text: str) -> str:
    return _WS_RE.sub(" ", (text or "").translate(_QUOTE_MARKS)).strip()


def cue_in_input(cue: str, *texts: str) -> bool:
    """Whether `cue` occurs in any one of `texts`, after the normalisation above."""
    needle = normalise_for_cue(cue)
    return bool(needle) and any(needle in normalise_for_cue(t) for t in texts)


def _looks_truncated(text: str) -> bool:
    """An object was opened and never closed: the response was cut off.

    The provider interface returns text only, so the API's stop reason is not
    visible here. A provider that records one as `last_stop_reason` is believed
    first (see `_call`); this is the fallback.
    """
    start = text.find("{")
    return start != -1 and text.count("{", start) > text.count("}", start)


def _opt_str(value) -> Optional[str]:
    """JSON null, a missing key, "null" and "" all mean no value."""
    if value is None:
        return None
    value = str(value).strip()
    return None if value in ("", "null", "None") else value


def parse_response(raw: str) -> dict:
    """Read the answer's JSON object. Raises IntentionInvalid on failure."""
    try:
        data = _parse_json(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        reason = (IntentionFailure.TRUNCATED_OUTPUT if _looks_truncated(raw)
                  else IntentionFailure.INVALID_JSON)
        raise IntentionInvalid(reason, str(exc)[:200]) from exc
    if not isinstance(data, dict):
        raise IntentionInvalid(IntentionFailure.INVALID_JSON, "not a JSON object")
    return data


# --- the stage -------------------------------------------------------------


class IntentionTagger:
    """Provider-agnostic, like `Contextualiser`: the provider is the only seam."""

    def __init__(
        self,
        provider: Optional[ModelProvider] = None,
        client=None,
        model: str = DEFAULT_MODEL,
        cache: Optional[ResponseCache] = None,
        prompt_version: str = INTENTION_PROMPT_VERSION,
    ):
        self.provider = provider or AnthropicProvider(model=model, client=client)
        self.model = getattr(self.provider, "model", model)
        self.cache = cache
        self.prompt_version = prompt_version
        self.fingerprint = intention_prompt_fingerprint()

    def _call(self, user: str) -> str:
        """Cached model call, keyed exactly as extraction and context key theirs."""
        key = None
        if self.cache is not None:
            key = ResponseCache.key(
                provider=self.provider.name, model=self.model,
                system=INTENTION_PROMPT, user=user,
                prompt_version=self.prompt_version,
            )
            hit = self.cache.get(key)
            if hit is not None:
                return hit["text"]

        text = self.provider.call(INTENTION_PROMPT, user, MAX_TOKENS,
                                  cache_system=True)
        if getattr(self.provider, "last_stop_reason", None) == "max_tokens":
            # Not cached: a cut-off answer is not a result worth replaying.
            raise IntentionInvalid(IntentionFailure.TRUNCATED_OUTPUT,
                                   "provider reported a max-tokens stop")

        if self.cache is not None and key is not None:
            self.cache.put(
                key, {"text": text, "model": self.model, "provider": self.provider.name}
            )
        return text

    def _result(self, qid: str, source: str, ts: str, **fields) -> IntentionResult:
        return IntentionResult(
            quote_id=qid, context_source=source,
            prompt_version=self.prompt_version,
            prompt_fingerprint=self.fingerprint, model=self.model,
            timestamp=ts, **fields,
        )

    def _validate(self, raw: str, qid: str, source: str, ts: str,
                  quote: str, context: Sequence[str]) -> IntentionResult:
        """Turn one response into a tagged result, or raise IntentionInvalid."""
        data = parse_response(raw)
        fields = {
            "broad": _opt_str(data.get("broad")),
            "sub": _opt_str(data.get("sub")),
            "secondary_broad": _opt_str(data.get("secondary_broad")),
            "secondary_sub": _opt_str(data.get("secondary_sub")),
            "evidence_type": _opt_str(data.get("evidence_type")),
            "has_quantified_target": data.get("has_quantified_target"),
            "target_cue": _opt_str(data.get("target_cue")),
            "claims_causal_effect": data.get("claims_causal_effect"),
            "causal_cue": _opt_str(data.get("causal_cue")),
            "cue": _opt_str(data.get("cue")),
            "rationale": _opt_str(data.get("rationale")),
        }
        if fields["broad"] is None:
            raise IntentionInvalid(IntentionFailure.INVALID_LABEL, "no broad code")
        result = self._result(qid, source, ts, status="tagged", **fields)

        # Every cue must be words that were actually sent: this tests the
        # tagger's reasoning, it is not a quote-fidelity check.
        for name in ("cue", "target_cue", "causal_cue"):
            cue = getattr(result, name)
            if cue is not None and not cue_in_input(cue, quote, *context):
                raise IntentionInvalid(IntentionFailure.CUE_NOT_IN_INPUT,
                                       f"{name} {cue!r} is not in the QUOTE or CONTEXT")
        return result

    def tag_one(self, row: Mapping, doc: Optional[Document], ts: str) -> IntentionResult:
        """Tag one quote. Never raises for a bad response; ProviderStopped is
        re-raised so the caller can stop making calls that cannot succeed."""
        qid = str(row.get("quote_id") or "")
        user, context, source = build_request(row, doc)
        quote = str(row.get("direct_quote", "") or "")

        request = user
        failure: Optional[IntentionInvalid] = None
        for attempt in range(2):
            try:
                raw = self._call(request)
                return self._validate(raw, qid, source, ts, quote, context)
            except ProviderStopped:
                raise
            except IntentionInvalid as exc:
                failure = exc
            except Exception:
                # The provider already retried with backoff; one more attempt
                # here would only double the wait for the same answer.
                return self._result(qid, source, ts, status="failed",
                                    failure_reason=IntentionFailure.PROVIDER_ERROR)
            # One retry, told what was wrong with the first answer.
            request = (
                f"{user}\n\nYOUR PREVIOUS ANSWER WAS REJECTED: {failure.reason} "
                f"({failure.detail}). Answer again, following the rules and "
                "returning JSON only."
            )
        return self._result(qid, source, ts, status="failed",
                            failure_reason=failure.reason)

    def run(self, rows: Iterable[Mapping], documents: Iterable[Document],
            run_timestamp: str = "") -> list[IntentionResult]:
        """Tag every row. One IntentionResult out per row in, same order.

        Quotes are independent: a failure on one is recorded and the next is
        tried. The exception is an account the API has stopped serving (out of
        credit, key rejected), where every further call would fail the same
        way; the remaining quotes are then recorded as provider errors without
        calling.
        """
        from .context import quote_id

        ts = run_timestamp or datetime.now(timezone.utc).isoformat()
        docs = {d.doc_id: d for d in documents}
        done: dict[str, IntentionResult] = {}
        stopped = False
        out: list[IntentionResult] = []
        for row in rows:
            row = dict(row)
            row["quote_id"] = row.get("quote_id") or quote_id(row)
            qid = row["quote_id"]
            if qid not in done:
                doc = docs.get(str(row.get("doc_id", "") or ""))
                if stopped:
                    done[qid] = self._result(
                        qid, build_request(row, doc)[2], ts, status="failed",
                        failure_reason=IntentionFailure.PROVIDER_ERROR)
                else:
                    try:
                        done[qid] = self.tag_one(row, doc, ts)
                    except ProviderStopped:
                        stopped = True
                        done[qid] = self._result(
                            qid, build_request(row, doc)[2], ts, status="failed",
                            failure_reason=IntentionFailure.PROVIDER_ERROR)
            out.append(done[qid])
        return out


def write_intention_log(results: Iterable[IntentionResult], out_dir) -> Path:
    """The full records, one JSON object per line, beside the release."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "intention_log.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")
    return path


def read_intention_log(path) -> list[IntentionResult]:
    with open(path, encoding="utf-8") as fh:
        return [IntentionResult(**json.loads(line)) for line in fh if line.strip()]


# --- trial files -----------------------------------------------------------

#: Fixed so the review sample can be drawn again identically. Recorded in the
#: sample's file name.
REVIEW_SEED = 20260925
REVIEW_PER_BROAD = 4
#: Shares are left blank for groups smaller than this.
MIN_SHARE_DENOMINATOR = 10


def write_trial_files(out_dir, seed: int = REVIEW_SEED) -> dict[str, Path]:
    """The Section 8 read-through files, from a finished tagged build.

    Reads the build's own `observations_internal.csv` and `intention_log.jsonl`
    from `out_dir` and joins them on quote ID, so the files describe exactly
    what was released.
    """
    import csv
    import random

    from .assemble import intention_label
    from .context import quote_id

    out_dir = Path(out_dir)
    with open(out_dir / "observations_internal.csv", newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    by_id = {r.quote_id: r for r in read_intention_log(out_dir / "intention_log.jsonl")}
    joined = [(row, by_id.get(quote_id(row))) for row in rows]
    files: dict[str, Path] = {}

    # The release itself, under the name the brief gives it.
    release = out_dir / "release_with_intention.csv"
    release.write_bytes((out_dir / "dataset.csv").read_bytes())
    files["release"] = release

    # Label counts: overall, by country, by document type.
    counts_path = out_dir / "intention_label_counts.csv"
    with open(counts_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["breakdown", "group", "intention", "n", "group_total", "share"])
        for breakdown, key in (("overall", None), ("country", "country"),
                               ("document_type", "document_type")):
            groups: dict[str, list[str]] = {}
            for row, _ in joined:
                groups.setdefault(row[key] if key else "all", []).append(row["intention"])
            for group in sorted(groups):
                labels = groups[group]
                total = len(labels)
                for label in sorted(set(labels), key=lambda l: (-labels.count(l), l)):
                    n = labels.count(label)
                    share = (f"{n / total:.1%}" if total >= MIN_SHARE_DENOMINATOR
                             else "")
                    w.writerow([breakdown, group, label or "(blank)", n, total, share])
    files["counts"] = counts_path

    failures_path = out_dir / "intention_failures.csv"
    with open(failures_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["quote_id", "agency", "speaker", "date", "url", "direct_quote",
                    "failure_reason", "context_source"])
        for row, res in joined:
            if res is None or res.status == "failed":
                w.writerow([quote_id(row), row["agency"], row["speaker"], row["date"],
                            row["url"], row["direct_quote"],
                            res.failure_reason if res else "missing_from_log",
                            res.context_source if res else ""])
    files["failures"] = failures_path

    # Review sample: every Unclear and Not tagged quote, and up to four drawn
    # at random from each other broad category.
    rng = random.Random(seed)
    sample: list[tuple[dict, Optional[IntentionResult], str]] = []
    for row, res in joined:
        if res is None or res.status == "failed":
            sample.append((row, res, "not_tagged"))
        elif res.broad == "unclear":
            sample.append((row, res, "unclear"))
    for broad in BROAD_CODES:
        if broad == "unclear":
            continue
        pool = [(row, res) for row, res in joined
                if res is not None and res.status == "tagged" and res.broad == broad]
        for row, res in rng.sample(pool, min(REVIEW_PER_BROAD, len(pool))):
            sample.append((row, res, f"random {broad}"))

    sample_path = out_dir / f"intention_review_sample_seed{seed}.csv"
    with open(sample_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["agency", "speaker", "date", "direct_quote", "intention",
                    "secondary_label", "evidence_type", "has_quantified_target",
                    "claims_causal_effect", "cue", "target_cue", "causal_cue",
                    "rationale", "context_source", "failure_reason",
                    "sample_reason", "quote_id"])
        for row, res, why in sample:
            w.writerow([
                row["agency"], row["speaker"], row["date"], row["direct_quote"],
                row["intention"],
                intention_label(res.secondary_broad, res.secondary_sub) if res else "",
                (res.evidence_type or "") if res else "",
                row["has_quantified_target"], row["claims_causal_effect"],
                (res.cue or "") if res else "", (res.target_cue or "") if res else "",
                (res.causal_cue or "") if res else "",
                (res.rationale or "") if res else "",
                res.context_source if res else "",
                (res.failure_reason or "") if res else "missing_from_log",
                why, quote_id(row),
            ])
    files["sample"] = sample_path
    return files


def summarise(results: Sequence[IntentionResult]) -> dict:
    tagged = [r for r in results if r.status == "tagged"]
    failed = [r for r in results if r.status == "failed"]
    reasons: dict[str, int] = {}
    for r in failed:
        reasons[r.failure_reason] = reasons.get(r.failure_reason, 0) + 1
    return {
        "status": "tagged",
        "quotes": len(results),
        "tagged": len(tagged),
        "not_tagged": len(failed),
        "failure_reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
        "unclear": sum(1 for r in tagged if r.broad == "unclear"),
        "context_quote_only": sum(1 for r in results if r.context_source == "quote_only"),
        "prompt_version": results[0].prompt_version if results else "",
        "prompt_fingerprint": results[0].prompt_fingerprint if results else "",
        "model": results[0].model if results else "",
    }
