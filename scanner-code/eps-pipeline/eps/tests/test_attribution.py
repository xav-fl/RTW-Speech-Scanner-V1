"""Both attribution paths, from fixtures. No network.

The GOV.UK path must behave exactly as it did before the sidecar existed. The
US path must attribute from `Block.speaker` without any frame line being
invented for it. The two must not interfere.
"""

from __future__ import annotations

import json

import pytest

from eps.harvest.local import IngestError, load_block_sidecar
from eps.normalise import (
    AttributionMismatch, QUOTE_MARKER, mark_attribution, segment,
    speaker_names_match,
)
from eps.sources.blocks import detect_us_quotes, render

DOC_ID = "Dtest000000"


def units_for(text: str):
    return segment(text, DOC_ID)


def attributable_paras(units) -> set[int]:
    return {u.para_idx for u in units if u.attributable}


# --------------------------------------------------------------------------
# The GOV.UK colon-frame path, unchanged
# --------------------------------------------------------------------------

GOVUK_TEXT = """Radical expansion in rights for children with SEND

The government has today announced a package of reforms.

Education Secretary Bridget Phillipson said:

> This government will put teachers back at the heart of the system, and we will fund it properly.

Paul Whiteman, general secretary of the NAHT, said:

> The funding announced today does not meet the scale of the problem."""


def test_govuk_frame_path_attributes_only_the_ministers_block():
    units = mark_attribution(units_for(GOVUK_TEXT), "press_release",
                             "Bridget Phillipson")
    attributed = [u for u in units if u.attributable]
    assert attributed, "the minister's blockquote should be attributable"
    joined = " ".join(u.text for u in attributed)
    assert "put teachers back at the heart" in joined
    assert "does not meet the scale" not in joined, \
        "the union leader's block must not be attributed to the minister"


def test_govuk_path_strips_the_quote_marker_and_advances_the_offset():
    units = mark_attribution(units_for(GOVUK_TEXT), "press_release",
                             "Bridget Phillipson")
    first = next(u for u in units if u.attributable)
    assert not first.text.startswith(QUOTE_MARKER)
    assert first.text.startswith("This government")


def test_govuk_path_is_untouched_when_no_sidecar_is_passed():
    # Explicit None and the default must agree; this is the whole basis of the
    # byte-identity guarantee for the UK corpus.
    a = mark_attribution(units_for(GOVUK_TEXT), "press_release", "Bridget Phillipson")
    b = mark_attribution(units_for(GOVUK_TEXT), "press_release",
                         "Bridget Phillipson", None)
    assert a == b


def test_speaker_only_types_are_wholly_attributable_on_both_paths():
    units = units_for(GOVUK_TEXT)
    assert all(u.attributable for u in mark_attribution(units, "speech"))
    assert all(u.attributable for u in mark_attribution(units, "speech", None, []))


# --------------------------------------------------------------------------
# The US sidecar path
# --------------------------------------------------------------------------

US_HTML = (
    '<div><p>The Department announced new flexibility for rural districts.</p>'
    '<p>"We are cutting red tape so that homes get built faster this year," '
    'said Secretary Smith.</p></div>'
)

US_THIRD_PARTY_HTML = (
    '<div><p>The Department published the guidance on Tuesday.</p>'
    '<p>"The Department has abandoned working families and it knows it," said '
    'Randi Weingarten, president of the American Federation of Teachers.</p></div>'
)

US_NO_QUOTES_HTML = (
    '<div><p>The Department published the guidance on Tuesday.</p>'
    '<p>It takes effect in the autumn term.</p></div>'
)


def sidecar_from(html: str) -> tuple[str, list[dict]]:
    blocks = detect_us_quotes(html)
    payload = [{"index": i, "kind": b.kind, "speaker": b.speaker,
                "method": b.method} for i, b in enumerate(blocks)]
    return render(blocks), payload


def test_us_speech_verb_document_attributes_the_quote():
    text, blocks = sidecar_from(US_HTML)
    units = mark_attribution(units_for(text), "press_release", "John Smith", blocks)
    attributed = [u for u in units if u.attributable]
    assert attributed, "the US path must find what the colon-frame rule cannot"
    assert "cutting red tape" in " ".join(u.text for u in attributed)


def test_the_govuk_rule_alone_would_find_nothing_here():
    # The reason this brief exists, asserted rather than asserted-about.
    text, _ = sidecar_from(US_HTML)
    units = mark_attribution(units_for(text), "press_release", "John Smith")
    assert not any(u.attributable for u in units)


def test_us_third_party_quote_is_not_attributed_to_the_secretary():
    text, blocks = sidecar_from(US_THIRD_PARTY_HTML)
    units = mark_attribution(units_for(text), "press_release", "John Smith", blocks)
    assert not any(u.attributable for u in units)
    # ...but the sidecar still carries who really said it.
    assert any(b["speaker"] == "Randi Weingarten" for b in blocks)


def test_us_third_party_quote_is_attributed_to_that_third_party():
    text, blocks = sidecar_from(US_THIRD_PARTY_HTML)
    units = mark_attribution(units_for(text), "press_release",
                             "Randi Weingarten", blocks)
    assert any(u.attributable for u in units)


def test_us_document_with_no_quotes_attributes_nothing():
    text, blocks = sidecar_from(US_NO_QUOTES_HTML)
    units = mark_attribution(units_for(text), "press_release", "John Smith", blocks)
    assert not any(u.attributable for u in units)
    assert all(b["kind"] == "text" for b in blocks)


def test_us_path_fails_closed_with_no_expected_speaker():
    text, blocks = sidecar_from(US_HTML)
    units = mark_attribution(units_for(text), "press_release", None, blocks)
    assert not any(u.attributable for u in units)


def test_us_path_strips_the_quote_marker():
    text, blocks = sidecar_from(US_HTML)
    units = mark_attribution(units_for(text), "press_release", "John Smith", blocks)
    assert not any(u.text.startswith(QUOTE_MARKER) for u in units)


# --------------------------------------------------------------------------
# The sidecar contract
# --------------------------------------------------------------------------

def test_length_mismatch_is_a_hard_error():
    text, blocks = sidecar_from(US_HTML)
    with pytest.raises(AttributionMismatch):
        mark_attribution(units_for(text), "press_release", "John Smith", blocks[:-1])


def test_sidecar_is_optional_and_absent_for_uk_documents(tmp_path):
    p = tmp_path / "uk.txt"
    p.write_text(GOVUK_TEXT, encoding="utf-8")
    assert load_block_sidecar(p) is None


def test_sidecar_is_loaded_when_present(tmp_path):
    text, blocks = sidecar_from(US_HTML)
    p = tmp_path / "us.txt"
    p.write_text(text, encoding="utf-8")
    (tmp_path / "us.blocks.json").write_text(
        json.dumps({"url": "https://example.gov/x", "blocks": blocks}),
        encoding="utf-8")
    assert load_block_sidecar(p) == blocks


def test_a_stale_sidecar_is_rejected(tmp_path):
    text, blocks = sidecar_from(US_HTML)
    p = tmp_path / "us.txt"
    p.write_text(text, encoding="utf-8")
    (tmp_path / "us.blocks.json").write_text(
        json.dumps({"url": "https://example.gov/x", "blocks": blocks,
                    "text_sha256": "0" * 64}),
        encoding="utf-8")
    with pytest.raises(IngestError, match="stale"):
        load_block_sidecar(p)


# --------------------------------------------------------------------------
# Name comparison
# --------------------------------------------------------------------------

@pytest.mark.parametrize("found,expected,match", [
    ("Secretary Smith", "John Smith", True),
    ("Secretary of the Treasury Scott Bessent", "Scott Bessent", True),
    ("Secretary McMahon's", "Linda McMahon", True),      # possessive stripped
    ("Randi Weingarten", "Linda McMahon", False),
    ("Jane Smith", "John Smith", False),
])
def test_speaker_names_match(found, expected, match):
    assert speaker_names_match(found, expected) is match
