"""Stage 2 under JEL classification protocol v2.0.

The protocol text is the frozen file shared with the rest of the project; these
tests check how the pipeline sends an item to it and what it does with the
answer, not the model's judgement.
"""

from __future__ import annotations

import json

import pytest

from eps.extract import (
    JEL_PROTOCOL_FILE, JEL_PROTOCOL_VERSION, JEL_SYSTEM, Extractor,
    _check_taxonomy_matches, _reference_text,
)
from eps.models import Observation
from eps.pipeline import load_active_codes, load_taxonomy
from eps.validate import validate_jel


class FakeProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, answer):
        self.answer = answer
        self.calls: list[tuple[str, str]] = []

    def call(self, system, user, max_tokens, cache_system=False):
        self.calls.append((system, user))
        return json.dumps(self.answer)


def item(status="coded", codes=(), comments=""):
    return {"items": [{"item_id": "item_1", "status": status,
                       "codes": [{"code": c, "strength": s, "rationale": f"why {c}"}
                                 for c, s in codes],
                       "comments": comments}]}


def classify(answer, quote="We will raise the minimum wage.", context=""):
    p = FakeProvider(answer)
    out = Extractor(load_taxonomy(), provider=p).classify(quote, context=context)
    return out, p


def test_system_prompt_is_the_frozen_protocol_then_the_taxonomy():
    (_, p) = classify(item(codes=[("J31", 3)]))
    system, user = p.calls[0]
    assert system.startswith(_reference_text(JEL_PROTOCOL_FILE))
    assert JEL_SYSTEM.startswith("JEL CLASSIFICATION PROTOCOL v2.0")
    assert "\nJ31 | Wage Level and Structure" in system
    # The item, not the protocol, travels in the user message.
    assert "Specific item to classify:\nWe will raise the minimum wage." in user
    assert "item_id: item_1" in user


def test_codes_are_unordered_and_stored_alphabetically():
    (primary, secondary, status, comments), _ = classify(
        item(codes=[("J38", 2), ("J22", 3), ("J31", 3)]))
    assert status == "coded" and comments == ""
    assert [a.detailed_code for a in [primary, *secondary]] == ["J22", "J31", "J38"]
    assert primary.match_strength == 3 and secondary[1].match_strength == 2
    assert primary.rationale == "why J22"
    assert primary.sub_code == "J2" and primary.major_code == "J"


@pytest.mark.parametrize("status", ["no_defensible_economic_match",
                                    "not_research_item", "needs_more_context"])
def test_non_coded_status_is_kept_with_no_codes(status):
    (primary, secondary, got, comments), _ = classify(item(status, comments="c"))
    assert got == status and comments == "c"
    assert primary.is_empty() and secondary == []


def test_codes_with_a_non_coded_status_are_dropped_and_noted():
    (primary, _, status, comments), _ = classify(
        item("no_defensible_economic_match", codes=[("J31", 1)]))
    assert status == "no_defensible_economic_match" and primary.is_empty()
    assert "[pipeline]" in comments and "dropped" in comments


def test_off_list_code_and_bad_strength_are_refused_and_noted():
    (primary, secondary, status, comments), _ = classify(
        item(codes=[("Z99", 3), ("J3", 3), ("J31", 0), ("J22", 2)]))
    assert [a.detailed_code for a in [primary, *secondary]] == ["J22"]
    assert "'Z99'" in comments and "'J3'" in comments and "J31" in comments


def test_unknown_status_and_missing_record_give_an_empty_status():
    (_, _, status, comments), _ = classify(item("maybe"))
    assert status == "" and "unknown status" in comments
    (_, _, status, comments), _ = classify({"items": []})
    assert status == "" and "no record" in comments


def _obs(answer):
    (primary, secondary, status, comments), _ = classify(answer)
    return Observation(doc_id="d", unit_ids=[], primary=primary, secondary=secondary,
                       jel_status=status, jel_comments=comments,
                       jel_protocol=JEL_PROTOCOL_VERSION)


def test_validation_passes_coded_and_names_each_non_coded_status():
    active = load_active_codes()
    assert validate_jel(_obs(item(codes=[("J31", 3)])), active) == ""
    why = validate_jel(_obs(item("needs_more_context", comments="unclear 'it'")), active)
    assert why == "classifier status needs_more_context: unclear 'it'"
    why = validate_jel(_obs(item("not_research_item")), active)
    assert why == "classifier status not_research_item"
    assert "no usable code" in validate_jel(_obs(item(codes=[("Z99", 3)])), active)
    assert "no usable status" in validate_jel(_obs(item("maybe")), active)


def test_taxonomy_and_active_list_must_agree():
    active = load_active_codes()
    text = _reference_text("jel_taxonomy_compact.txt")
    _check_taxonomy_matches(text, active)
    with pytest.raises(ValueError, match="J31"):
        _check_taxonomy_matches(text.replace("J31 | Wage Level", "J31 | Wages"), active)
