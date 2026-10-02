"""Tests for intention tagging.

Every test runs against `FakeProvider`, so the stage is exercised with no
network and no cost. As in test_context.py, the canned responses are the
point: a malformed or rule-breaking answer is written down exactly, and the
code's handling of it pinned.
"""

from __future__ import annotations

import csv
import json
from datetime import date

import pytest

from eps.assemble import (
    INTENTION_DISPLAY, NOT_TAGGED, RELEASE_COLUMNS, apply_intentions,
    intention_values, write_dataset,
)
from eps.context import quote_id
from eps.extract import ResponseCache
from eps.intention import (
    INTENTION_PROMPT, INTENTION_PROMPT_VERSION, IntentionTagger, build_request, cue_in_input,
    read_intention_log,
)
from eps.models import (
    BROAD_CODES, EVIDENCE_TYPES, FAILURE_REASONS, INTENTION_SUBS, SUB_CODES,
    Document, IntentionResult, JELAssignment, Observation, Unit,
)
from eps.providers import FakeProvider, ProviderStopped

QUOTE = "We will cut the disadvantage gap in half by 2030."


def make_doc(doc_id="Dabc") -> Document:
    texts = [
        "Good morning.",
        "Schools have struggled for years.",
        "Too many children fall behind.",
        QUOTE,
        "That is our promise to parents.",
        "Thank you.",
    ]
    units, pos = [], 0
    for i, t in enumerate(texts):
        units.append(Unit(f"{doc_id}.P001.S{i:03d}", 1, i, t, pos, pos + len(t)))
        pos += len(t) + 1
    return Document(
        doc_id=doc_id, institution="Department for Education", country="UK",
        url=f"https://example.gov.uk/{doc_id}", title="Opportunity speech",
        doc_type="speech", pub_date=date(2026, 3, 1),
        text=" ".join(texts), units=units,
    )


def make_row(doc: Document, quote=QUOTE, unit_ids=None, gloss=None) -> dict:
    return {
        "agency": doc.institution, "speaker": "A Minister",
        "document_title": doc.title, "document_type": doc.doc_type,
        "date": doc.pub_date.isoformat(), "url": doc.url,
        "direct_quote": quote, "quote_in_context": gloss or quote,
        "doc_id": doc.doc_id,
        "unit_ids": unit_ids if unit_ids is not None else doc.units[3].unit_id,
        "anchor": "", "country": doc.country,
    }


def answer(**over) -> dict:
    base = {
        "broad": "commits_to_action", "sub": "pledges_future_action",
        "evidence_type": None, "secondary_broad": None, "secondary_sub": None,
        "cue": "We will", "has_quantified_target": True,
        "target_cue": "cut the disadvantage gap in half by 2030",
        "claims_causal_effect": False, "causal_cue": None,
        "rationale": "A promise of future action with a stated target.",
    }
    base.update(over)
    return base


def scripted(*responses) -> FakeProvider:
    """Answers calls in order; dicts are sent as JSON, strings as they are."""
    queue = list(responses)

    def responder(system, user):
        r = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(r, Exception):
            raise r
        return r if isinstance(r, str) else json.dumps(r)

    return FakeProvider(responder)


def tag(*responses, rows=None, docs=None):
    doc = make_doc()
    tagger = IntentionTagger(provider=scripted(*responses))
    return tagger.run(rows or [make_row(doc)], docs if docs is not None else [doc])


# --- 1. a valid response ----------------------------------------------------


def test_valid_response_gives_result_and_release_strings():
    [r] = tag(answer())
    assert r.status == "tagged" and r.failure_reason is None
    assert (r.broad, r.sub) == ("commits_to_action", "pledges_future_action")
    assert r.has_quantified_target is True and r.claims_causal_effect is False
    assert r.context_source == "units"
    assert r.prompt_version == INTENTION_PROMPT_VERSION
    assert len(r.prompt_fingerprint) == 12
    assert r.quote_id == quote_id(make_row(make_doc()))
    assert intention_values(r) == {
        "intention": "Commits to action: pledges future action",
        "has_quantified_target": "Yes",
        "claims_causal_effect": "No",
    }


def test_no_sub_labels_and_evidence_type():
    [r] = tag(answer(broad="rules_out_option", sub=None, cue="We will"))
    assert intention_values(r)["intention"] == "Rules out option"
    [r] = tag(answer(sub="evidence", broad="calls_on_others",
                     evidence_type="public_consultation"))
    assert r.evidence_type == "public_consultation"
    assert intention_values(r)["intention"] == "Requests evidence"


@pytest.mark.parametrize("etype", EVIDENCE_TYPES)
def test_requests_evidence_has_no_subcategory_in_release(etype):
    """The evidence type stays in the log; the release says only "Requests
    evidence", whatever kind of evidence was asked for."""
    [r] = tag(answer(sub="evidence", broad="calls_on_others", evidence_type=etype))
    assert r.evidence_type == etype
    assert intention_values(r)["intention"] == "Requests evidence"


def test_unclear_may_have_no_cue():
    [r] = tag(answer(broad="unclear", sub=None, cue=None,
                     has_quantified_target=False, target_cue=None))
    assert r.status == "tagged" and intention_values(r)["intention"] == "Unclear"


# --- 2. every named failure reason -----------------------------------------

FAILURES = {
    "invalid_json": "I think this is a pledge.",
    "truncated_output": '{"broad": "commits_to_action", "sub": "pledges_fu',
    "invalid_label": answer(broad="commits_to_actions"),
    "invalid_sub_for_broad": answer(sub="outcome"),
    "evidence_type_mismatch": answer(evidence_type="expert_referral"),
    "cue_not_in_input": answer(cue="we shall"),
    "label_cue_not_in_quote": answer(cue="Too many children fall behind."),
    "missing_flag_cue": answer(target_cue=None),
    "provider_error": RuntimeError("connection reset after retries"),
}


def test_failure_table_covers_every_named_reason():
    assert set(FAILURES) == set(FAILURE_REASONS)


@pytest.mark.parametrize("reason", sorted(FAILURES))
def test_each_failure_reason_gives_not_tagged(reason):
    [r] = tag(FAILURES[reason])  # the same bad answer on the retry too
    assert r.status == "failed" and r.failure_reason == reason
    assert r.broad is None and r.sub is None  # never defaulted to a real label
    assert intention_values(r) == {
        "intention": NOT_TAGGED, "has_quantified_target": "",
        "claims_causal_effect": "",
    }


@pytest.mark.parametrize("bad, reason", [
    (answer(evidence_type=None, broad="calls_on_others", sub="evidence"),
     "evidence_type_mismatch"),
    (answer(evidence_type="a_survey", broad="calls_on_others", sub="evidence"),
     "evidence_type_mismatch"),
    (answer(claims_causal_effect=False, causal_cue="We will"), "missing_flag_cue"),
    (answer(secondary_broad="commits_to_action", secondary_sub=None),
     "invalid_sub_for_broad"),
    (answer(secondary_broad=None, secondary_sub="outcome"), "invalid_sub_for_broad"),
    (answer(secondary_broad="unclear", secondary_sub=None), "invalid_label"),
    (answer(broad="rules_out_option", sub="outcome"), "invalid_sub_for_broad"),
    (answer(target_cue="halve the gap"), "cue_not_in_input"),
    (answer(cue=""), "cue_not_in_input"),
    (answer(broad="states_view_without_action", sub="causal_belief",
            evidence_type="research_or_data"), "evidence_type_mismatch"),
])
def test_more_rule_breaks(bad, reason):
    [r] = tag(bad)
    assert (r.status, r.failure_reason) == ("failed", reason)


def test_one_failure_does_not_stop_the_batch():
    doc = make_doc()
    rows = [make_row(doc), make_row(doc, quote="Too many children fall behind.",
                                    unit_ids=doc.units[2].unit_id)]
    # First quote: bad twice. Second quote: good.
    ok = answer(broad="states_view_without_action", sub="describes_problem",
                cue="fall behind", has_quantified_target=False, target_cue=None)
    results = tag("junk", "junk", ok, rows=rows, docs=[doc])
    assert [r.status for r in results] == ["failed", "tagged"]


def test_stopped_account_records_the_rest_without_calling():
    doc = make_doc()
    rows = [make_row(doc), make_row(doc, quote="Thank you.",
                                    unit_ids=doc.units[5].unit_id)]
    provider = scripted(ProviderStopped("out of credit", "credit balance too low"))
    results = IntentionTagger(provider=provider).run(rows, [doc])
    assert [r.failure_reason for r in results] == ["provider_error"] * 2
    assert provider.calls == 1


# --- 3. retry ----------------------------------------------------------------


def test_bad_first_answer_then_good_retry_is_tagged():
    seen = []

    def responder(system, user):
        seen.append(user)
        return "not json" if len(seen) == 1 else json.dumps(answer())

    [r] = IntentionTagger(provider=FakeProvider(responder)).run(
        [make_row(make_doc())], [make_doc()])
    assert r.status == "tagged"
    assert len(seen) == 2
    assert "invalid_json" in seen[1] and "PREVIOUS ANSWER" in seen[1]


def test_retry_is_only_once():
    provider = scripted("junk")
    IntentionTagger(provider=provider).run([make_row(make_doc())], [make_doc()])
    assert provider.calls == 2


def test_cache_replays_without_calling(tmp_path):
    cache = ResponseCache(tmp_path / "cache")
    first = scripted(answer())
    IntentionTagger(provider=first, cache=cache).run([make_row(make_doc())], [make_doc()])
    second = scripted(answer())
    [r] = IntentionTagger(provider=second, cache=cache).run(
        [make_row(make_doc())], [make_doc()])
    assert second.calls == 0 and r.status == "tagged"


# --- 4. the release values ---------------------------------------------------


def test_release_values_are_exactly_the_permitted_set():
    """14 broad-sub pairs (13 in I1, plus causal belief from I2), Rules out
    option, Unclear and Not tagged: 17 values."""
    expected = {
        "Commits to action: announces decision",
        "Commits to action: pledges future action",
        "Commits to action: makes conditional commitment",
        "Reports existing action: completed action",
        "Reports existing action: outcome",
        "Reports existing action: ongoing implementation",
        "Considers open option: preferred option",
        "Considers open option: no stated preference",
        "Requests evidence",
        "Calls on others to act: other states",
        "Calls on others to act: private actors",
        "States view without action: describes problem",
        "States view without action: value judgement",
        "States view without action: causal belief",
        "Rules out option",
        "Unclear",
        "Not tagged",
    }
    # Every valid pair the model can produce, plus a failure.
    produced = set()
    for broad, subs in INTENTION_SUBS.items():
        for sub in subs or (None,):
            r = IntentionResult(
                quote_id="q", status="tagged", broad=broad, sub=sub,
                evidence_type="expert_referral" if sub == "evidence" else None,
                has_quantified_target=False, claims_causal_effect=False,
                cue=None if broad == "unclear" else "x",
            )
            produced.add(intention_values(r)["intention"])
    produced.add(intention_values(
        IntentionResult("q", "failed", failure_reason="invalid_json"))["intention"])
    assert produced == expected and len(expected) == 17
    assert set(INTENTION_DISPLAY.values()) | {NOT_TAGGED} == expected


# --- 5. the prompt names every code -----------------------------------------


def test_every_code_appears_in_the_prompt():
    for code in BROAD_CODES + SUB_CODES + EVIDENCE_TYPES:
        assert code in INTENTION_PROMPT, code


# --- 6. the cue check ---------------------------------------------------------


def test_cue_check_folds_apostrophes_and_whitespace_only():
    text = "We’re rolling out  Best Start\nFamily Hubs"
    assert cue_in_input("We're rolling out Best Start Family Hubs", text)
    assert cue_in_input("We’re rolling out", text)
    assert cue_in_input('"quoted"', "the “quoted” words")
    assert not cue_in_input("We are rolling out", text)
    assert not cue_in_input("we’re rolling out", text)  # case is not folded
    assert not cue_in_input("", text)


def test_curly_cue_against_straight_quote_is_accepted():
    doc = make_doc()
    row = make_row(doc, quote="We're rolling out hubs.", unit_ids=doc.units[3].unit_id)
    [r] = tag(answer(cue="We’re rolling out", has_quantified_target=False,
                     target_cue=None), rows=[row], docs=[doc])
    assert r.status == "tagged"


def test_flag_cue_may_come_from_context_but_not_straddle_it():
    ok = answer(claims_causal_effect=True, causal_cue="That is our promise to parents.")
    assert tag(ok)[0].status == "tagged"
    straddle = answer(causal_cue="fall behind. That is our promise",
                      claims_causal_effect=True)
    assert tag(straddle)[0].failure_reason == "cue_not_in_input"


def test_label_cue_must_come_from_the_quote_except_for_unclear():
    """I2: context settles tense and actor, but the label rests on the quote."""
    from_context = answer(broad="reports_existing_action", sub="completed_action",
                          cue="Too many children fall behind.",
                          has_quantified_target=False, target_cue=None)
    assert tag(from_context)[0].failure_reason == "label_cue_not_in_quote"
    unclear = answer(broad="unclear", sub=None, cue="Too many children fall behind.",
                     has_quantified_target=False, target_cue=None)
    assert tag(unclear)[0].status == "tagged"


# --- context retrieval ----------------------------------------------------------


def test_request_carries_two_units_before_and_one_after():
    doc = make_doc()
    user, context, source = build_request(make_row(doc), doc)
    assert source == "units"
    assert context == ("Schools have struggled for years. Too many children fall behind.",
                       "That is our promise to parents.")
    assert "Good morning" not in user
    for block in ("METADATA", "QUOTE", "CONTEXT"):
        assert f"{block}\n" in user
    assert "GLOSS" not in user  # the gloss adds nothing here


def test_missing_units_fall_back_to_the_gloss():
    doc = make_doc()
    gloss = QUOTE.replace("gap", "gap [between poorer pupils and others]")
    row = make_row(doc, unit_ids="Dabc.P009.S999", gloss=gloss)
    user, context, source = build_request(row, doc)
    assert source == "quote_only" and context == (gloss,)
    assert "GLOSS\n" in user
    [r] = tag(answer(), rows=[row], docs=[doc])
    assert r.context_source == "quote_only"
    [r] = tag(answer(), rows=[make_row(doc)], docs=[])
    assert r.context_source == "quote_only"


# --- 7. release column order ---------------------------------------------------


FLAGS = ("has_quantified_target", "claims_causal_effect")


def test_intention_alone_follows_quote_in_context():
    i = RELEASE_COLUMNS.index("quote_in_context")
    assert RELEASE_COLUMNS[i + 1] == "intention"
    assert RELEASE_COLUMNS[i + 2] == "economics_topics"


def test_written_release_carries_the_label_and_internal_the_flags(tmp_path):
    doc = make_doc()
    rows = [make_row(doc)]
    apply_intentions(rows, tag(answer()))
    release, internal = write_dataset(rows, tmp_path)
    for path in (release, internal):
        with open(path, newline="", encoding="utf-8") as fh:
            row = next(csv.DictReader(fh))
        assert row["intention"] == "Commits to action: pledges future action"
    assert row["has_quantified_target"] == "Yes"  # internal table
    assert row["claims_causal_effect"] == "No"


def test_flags_absent_from_release_present_in_log(tmp_path):
    summary, rows = _run_build(tmp_path, IntentionTagger(provider=scripted(answer())))
    with open(tmp_path / "dataset.csv", newline="", encoding="utf-8") as fh:
        header = csv.DictReader(fh).fieldnames
    for flag in FLAGS:
        assert flag not in header and flag not in RELEASE_COLUMNS
    [logged] = read_intention_log(tmp_path / "intention_log.jsonl")
    assert logged.has_quantified_target is True
    assert logged.target_cue == "cut the disadvantage gap in half by 2030"
    assert logged.claims_causal_effect is False and logged.causal_cue is None


# --- 8. skipping ---------------------------------------------------------------


def _valid_build_inputs():
    """One document and one observation that pass validation for real."""
    from eps.pipeline import load_active_codes
    from eps.validate import OfficeholderTable

    doc = make_doc()
    code = "I24"
    assert code in load_active_codes().by_code
    obs = Observation(
        doc_id=doc.doc_id, unit_ids=[doc.units[3].unit_id],
        primary=JELAssignment(major_code=code[0], sub_code=code[:2],
                              detailed_code=code, match_strength=3),
    )
    officeholders = OfficeholderTable([{
        "institution": doc.institution, "person": "A Minister", "role": "",
        "start_date": date(2025, 1, 1), "end_date": None,
    }])
    return doc, obs, officeholders


def _run_build(tmp_path, tagger):
    from eps.pipeline import build, load_taxonomy

    doc, obs, officeholders = _valid_build_inputs()
    summary = build([doc], {doc.doc_id: [obs]}, load_taxonomy(), officeholders,
                    tmp_path, intention_tagger=tagger)
    with open(tmp_path / "dataset.csv", newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return summary, rows


def test_skip_leaves_the_intention_column_blank(tmp_path):
    summary, rows = _run_build(tmp_path, None)
    assert summary["observations_kept"] == 1, summary["reject_reasons"]
    assert summary["intention"] == {"status": "skipped"}
    assert rows[0]["intention"] == ""
    assert read_intention_log(tmp_path / "intention_log.jsonl") == []


def test_build_tags_and_logs(tmp_path):
    tagger = IntentionTagger(provider=scripted(answer()))
    summary, rows = _run_build(tmp_path, tagger)
    assert summary["observations_kept"] == 1, summary["reject_reasons"]
    assert rows[0]["intention"] == "Commits to action: pledges future action"
    assert summary["intention"]["tagged"] == 1
    [logged] = read_intention_log(tmp_path / "intention_log.jsonl")
    assert logged.status == "tagged" and logged.cue == "We will"


# --- context preserved on build ------------------------------------------------


def _build_quote_id():
    doc, obs, _ = _valid_build_inputs()
    return quote_id({"doc_id": doc.doc_id, "unit_ids": " ".join(obs.unit_ids),
                     "anchor": ""})


def _write_context_log(out_dir, entries: dict[str, str]):
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "context_log.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["quote_id", "quote_in_context"])
        w.writeheader()
        for qid, text in entries.items():
            w.writerow({"quote_id": qid, "quote_in_context": text})


GLOSSED = QUOTE.replace("the disadvantage gap", "the disadvantage gap [in attainment]")


def test_build_joins_context_log(tmp_path, capsys):
    _write_context_log(tmp_path, {_build_quote_id(): GLOSSED})
    summary, rows = _run_build(tmp_path, None)
    assert rows[0]["quote_in_context"] == GLOSSED
    assert rows[0]["direct_quote"] == QUOTE
    assert summary["context"] == {"source": "context_log.csv", "unmatched": 0}
    assert "not joined" not in capsys.readouterr().err


def test_build_without_context_log_warns_and_keeps_plain_quote(tmp_path, capsys):
    summary, rows = _run_build(tmp_path, None)
    assert rows[0]["quote_in_context"] == QUOTE
    assert summary["context"] == {"source": "none", "unmatched": 0}
    assert ("quote_in_context not joined: context_log.csv not found for this run"
            in capsys.readouterr().err)


def test_build_with_partial_context_log_reports_unmatched(tmp_path, capsys):
    _write_context_log(tmp_path, {"someotherquote00": "unrelated"})
    summary, rows = _run_build(tmp_path, None)
    assert rows[0]["quote_in_context"] == QUOTE
    assert summary["context"]["unmatched"] == 1
    saved = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert saved["context"]["unmatched"] == 1
    assert "1 kept quote(s) have no row in the context log" in capsys.readouterr().err


def test_explicit_context_overrides_the_log(tmp_path):
    _write_context_log(tmp_path, {_build_quote_id(): "from the log"})
    from eps.pipeline import build, load_taxonomy

    doc, obs, officeholders = _valid_build_inputs()
    summary = build([doc], {doc.doc_id: [obs]}, load_taxonomy(), officeholders,
                    tmp_path, context={_build_quote_id(): GLOSSED})
    assert summary["context"]["source"] == "given"
    with open(tmp_path / "dataset.csv", newline="", encoding="utf-8") as fh:
        assert next(csv.DictReader(fh))["quote_in_context"] == GLOSSED


# --- missing key -----------------------------------------------------------------


class _NamedFake(FakeProvider):
    name = "anthropic"


def test_missing_key_warns_but_builds(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    tagger = IntentionTagger(provider=_NamedFake(
        lambda s, u: (_ for _ in ()).throw(TypeError("no auth"))))
    summary, rows = _run_build(tmp_path, tagger)
    out = capsys.readouterr()
    assert "ANTHROPIC_API_KEY is not set" in out.err and "--skip-intention" in out.err
    assert rows[0]["intention"] == NOT_TAGGED
    assert summary["intention"]["failure_reasons"] == {"provider_error": 1}
    assert "Not tagged: 1 of 1" in out.out and "provider_error" in out.out


def test_no_key_warning_when_key_set_or_skipped(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-real-key")
    _run_build(tmp_path, IntentionTagger(provider=_NamedFake(
        lambda s, u: json.dumps(answer()))))
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    _run_build(tmp_path, None)
    assert "is not set" not in capsys.readouterr().err


def test_cli_build_has_skip_option(monkeypatch):
    from eps import cli

    seen = {}
    monkeypatch.setattr(cli, "cmd_build", lambda args: seen.update(vars(args)) or 0)
    cli.main(["build", "--run-dir", "x", "--skip-intention"])
    assert seen["skip_intention"] is True
