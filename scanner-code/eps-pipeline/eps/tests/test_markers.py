"""The `> ` blockquote marker never reaches unit text, on any path.

The marker is written by our renderers at the start of a quote block. It is
not the publisher's words, so it must not appear in a released quote. A `>`
the source itself printed is the publisher's words, and must survive.
No network.
"""

from __future__ import annotations

import pytest

from eps.normalise import QUOTE_MARKER, mark_attribution, segment

DOC_ID = "Dtest000000"

TEXT = """I am today updating the House on our plans.

> We will cut waiting lists by a third, and fund it properly.

The rule is simple: where demand > supply, prices rise. We will act."""

# A transcript: two distinct speaker labels, one block quoted by the renderer.
TRANSCRIPT = """SECRETARY RUBIO: Thank you all for coming.

> We will impose visa restrictions on those responsible.

QUESTION: Will that include family members?

SECRETARY RUBIO: It will."""


def _check_offsets(text: str, units) -> None:
    for u in units:
        assert text[u.char_start:u.char_end] == u.text, u.unit_id


def _paths(text: str):
    """Every route through mark_attribution that can see a marker."""
    units = segment(text, DOC_ID)
    return {
        "speaker_only": mark_attribution(units, "speech"),
        "speaker_only_with_sidecar": mark_attribution(
            units, "speech", None, [{"kind": "prose"}] * 3),
        "speaker_is_document_uk": mark_attribution(
            units, "press_release", "Jane Doe", None, "UK", True),
        "speaker_is_document_us": mark_attribution(
            units, "press_release", "Jane Doe", None, "US", True),
        "quote_block": mark_attribution(units, "press_release", "Jane Doe"),
    }


@pytest.mark.parametrize("path", list(_paths(TEXT)))
def test_marker_is_stripped_and_offsets_still_hold(path):
    units = _paths(TEXT)[path]
    assert not any(u.text.startswith(QUOTE_MARKER) for u in units)
    assert any(u.text.startswith("We will cut waiting lists") for u in units)
    _check_offsets(TEXT, units)


@pytest.mark.parametrize("path", list(_paths(TEXT)))
def test_a_greater_than_sign_the_source_printed_survives(path):
    units = _paths(TEXT)[path]
    assert any("demand > supply" in u.text for u in units)


def test_marker_pass_changes_text_only_never_attribution():
    from eps.normalise import _mark_attribution

    units = segment(TEXT, DOC_ID)
    for args in [("speech",), ("press_release", "Jane Doe", None, "UK", True),
                 ("press_release", "Jane Doe")]:
        before = _mark_attribution(units, *args)
        after = mark_attribution(units, *args)
        assert [(u.unit_id, u.attributable, u.char_end) for u in before] \
            == [(u.unit_id, u.attributable, u.char_end) for u in after]


def test_marker_inside_a_paragraph_is_the_sources_and_stays():
    # GOV.UK occasionally publishes a literal ">" mid-paragraph. Only the
    # opening of a paragraph can carry the renderer's marker.
    text = "Jane Doe said: > > We will act. > It is time."
    units = mark_attribution(segment(text, DOC_ID), "speech")
    assert units[0].text.startswith("Jane Doe said: > > ")
    assert units[1].text == "> It is time."


def test_marker_is_removed_once_not_twice():
    # A quote block whose own text opens with ">" renders as "> > ...". The
    # renderer added one marker; the other is the publisher's.
    text = "Intro.\n\n> > Quoted text here."
    for args in [("speech",), ("press_release", "Jane Doe", None, "UK", True)]:
        units = mark_attribution(segment(text, DOC_ID), *args)
        assert units[1].text == "> Quoted text here."
        _check_offsets(text, units)


def test_transcript_path_strips_the_marker_without_moving_attribution():
    units = mark_attribution(segment(TRANSCRIPT, DOC_ID), "speech", "Marco Rubio")
    quoted = next(u for u in units if "visa restrictions" in u.text)
    assert quoted.text.startswith("We will impose")
    assert quoted.attributable, "it follows a SECRETARY RUBIO label"
    question = next(u for u in units if "family members" in u.text)
    assert not question.attributable
    _check_offsets(TRANSCRIPT, units)
