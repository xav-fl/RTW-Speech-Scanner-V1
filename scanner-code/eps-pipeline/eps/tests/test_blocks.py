"""The block model and the two quote detectors.

One HTML fixture per case the brief names. The last one -- a quote attributed
to someone else entirely -- is the case that protects data quality: a press
release quoting a union leader must not silently inherit the Secretary as
speaker.

Fixture files only. No network calls in tests, ever.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eps.sources.blocks import (
    Block, METHODS, detect_blockquotes, detect_us_quotes, name_appears,
    names_match, quote_speakers, render, split_quoted,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def quotes(blocks: list[Block]) -> list[Block]:
    return [b for b in blocks if b.kind == "quote"]


# --------------------------------------------------------------------------
# Splitting
# --------------------------------------------------------------------------

def test_split_handles_a_straight_open_and_a_curly_close():
    # ed.gov does exactly this inside a single sentence.
    spans = split_quoted('He said "we will act” today')
    assert [q for q, _ in spans] == [False, True, False]
    assert spans[1][1] == "we will act"


def test_an_unclosed_quote_runs_to_the_end_of_the_paragraph():
    # US releases open every paragraph of a long quotation and close only the
    # last, so an unclosed span is the convention, not an error.
    spans = split_quoted('“We will act on this next year')
    assert spans == [(True, "We will act on this next year")]


def test_apostrophes_are_not_quotation_marks():
    spans = split_quoted("the department’s plan and the states' role")
    assert [q for q, _ in spans] == [False]


# --------------------------------------------------------------------------
# Attribution
# --------------------------------------------------------------------------

def test_attribution_after_the_quote():
    blocks = detect_us_quotes(load("us_quote_after.html"))
    q = quotes(blocks)
    assert len(q) == 1
    assert q[0].speaker == "U.S. Secretary of Education Linda McMahon"
    assert q[0].method == "speech_verb"
    assert names_match(q[0].speaker, "Linda McMahon")


def test_attribution_before_the_quote():
    blocks = detect_us_quotes(load("us_quote_before.html"))
    q = quotes(blocks)
    assert len(q) == 1
    assert q[0].speaker == "Secretary Smith"
    assert q[0].method == "speech_verb"


def test_attribution_splitting_the_quote_attributes_both_halves():
    blocks = detect_us_quotes(load("us_quote_split.html"))
    q = quotes(blocks)
    assert len(q) == 2
    assert [b.speaker for b in q] == ["Smith", "Smith"]
    assert all(b.method == "speech_verb" for b in q)


def test_a_second_consecutive_quoted_sentence_carries_the_same_speaker():
    blocks = detect_us_quotes(load("us_quote_consecutive.html"))
    q = quotes(blocks)
    assert len(q) == 3
    assert {b.speaker for b in q} == {"Secretary Smith"}
    # Only the first was attributed explicitly; the rest inherited.
    assert q[0].method == "speech_verb"
    assert q[-1].method == "structural"


def test_a_quote_attributed_to_someone_else_comes_back_with_that_name():
    blocks = detect_us_quotes(load("us_quote_other_speaker.html"))
    q = quotes(blocks)
    assert len(q) == 2
    assert q[0].speaker == "Secretary Smith"
    assert q[1].speaker == "Randi Weingarten"
    assert not names_match(q[1].speaker, "John Smith")


def test_a_plain_paragraph_after_a_quotation_clears_the_carry():
    blocks = detect_us_quotes(load("us_quote_consecutive.html"))
    assert blocks[-1].kind == "text"
    assert blocks[-1].speaker is None


def test_scare_quotes_are_not_promoted_to_quote_blocks():
    blocks = detect_us_quotes(load("scare_quotes.html"))
    assert quotes(blocks) == []
    # The words are still there; a detection floor is not a filter.
    assert "administrative bloat" in render(blocks)


def test_every_method_value_is_one_of_the_declared_four():
    for name in ("us_quote_after.html", "us_quote_split.html",
                 "us_quote_consecutive.html", "us_quote_other_speaker.html",
                 "uk_blockquote.html"):
        for b in detect_us_quotes(load(name)):
            assert b.method in METHODS


# --------------------------------------------------------------------------
# The UK detector still works, unchanged
# --------------------------------------------------------------------------

def test_blockquote_detector_reads_the_frame_line():
    blocks = detect_blockquotes(load("uk_blockquote.html"))
    q = quotes(blocks)
    assert len(q) == 2
    assert q[0].speaker == "Education Secretary Bridget Phillipson"
    assert q[1].speaker == "Paul Whiteman"
    assert all(b.method == "structural" for b in q)


def test_us_detector_finds_nothing_in_a_govuk_shaped_page_without_blockquotes():
    # The point of writing a second detector: the UK rule returns zero quote
    # blocks on inline US quoting, and this is the mirror image of that.
    plain = "<p>Secretary Smith welcomed the announcement in a statement.</p>"
    assert quotes(detect_us_quotes(plain)) == []


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def test_render_uses_the_same_quote_marker_as_the_uk_rewriter():
    out = render(detect_us_quotes(load("us_quote_after.html")))
    quoted = [line for line in out.split("\n\n") if line.startswith("> ")]
    assert len(quoted) == 1
    assert quoted[0].startswith("> North Dakota is proving")
    assert "\n\n" in out          # blocks stay separated, as the UK rewriter does


def test_quote_speakers_are_distinct_and_in_first_seen_order():
    blocks = detect_us_quotes(load("us_quote_other_speaker.html"))
    assert quote_speakers(blocks) == ["Secretary Smith", "Randi Weingarten"]


# --------------------------------------------------------------------------
# Name comparison
# --------------------------------------------------------------------------

@pytest.mark.parametrize("found,expected,match", [
    ("Secretary Smith", "John Smith", True),
    ("Secretary of the Treasury Scott Bessent", "Scott Bessent", True),
    ("U.S. Secretary of Education Linda McMahon", "Linda McMahon", True),
    ("Randi Weingarten", "Linda McMahon", False),
    ("Jane Smith", "John Smith", False),
    ("Secretary", "John Smith", False),
])
def test_names_match(found, expected, match):
    assert names_match(found, expected) is match


@pytest.mark.parametrize("haystack,found", [
    # rule 1: every distinctive token present
    ("Today Linda McMahon visited North Dakota.", True),
    # rule 2: office title in front of the surname, no forename anywhere
    ("Secretary McMahon's Remarks to 1,000 High School Students", True),
    ("Administrator McMahon opened the session", True),
    # a bare surname is NOT enough -- this is what caused B-01
    ("McMahon was mentioned in passing", False),
    ("Assistant Secretary Chris Pilkerton's Remarks", False),
    ("Statement on the President's Decision", False),
])
def test_name_appears(haystack, found):
    assert name_appears("Linda McMahon", haystack) is found
