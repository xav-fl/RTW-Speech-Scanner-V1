"""The shared HTML-to-text layer.

These five cases are the UK harvest's B-05 fault written down. Every tag has to
become a space, because dropping one welds two words together and the frozen
text stops matching the page it cites. Two dozen adapters are about to inherit
this code, so the guarantee is tested here once rather than trusted 24 times.

Fixture strings only. No network calls in tests, ever.
"""

from __future__ import annotations

from eps.sources.text import _clean_inline, html_to_blocks, strip_noise


def _text(html: str) -> str:
    return " ".join(t for _, t in html_to_blocks(html))


def test_tag_boundary_between_two_words_produces_a_space():
    # The original fault: "Parents end up fighting" became "Parents endup".
    # Every tag becomes a space, with no exception for one sitting mid-word --
    # welding two words is a silent corruption, an extra space is visible.
    assert _clean_inline("Parents end <b>up</b> fighting") == "Parents end up fighting"
    assert _clean_inline("one<span></span>two") == "one two"
    assert _text("<p>Parents end</p><p>up fighting</p>") == "Parents end up fighting"


def test_newline_inside_a_block_becomes_a_space():
    assert _clean_inline("Parents end\nup fighting") == "Parents end up fighting"


def test_nbsp_becomes_an_ordinary_space():
    out = _clean_inline("supply&nbsp;chains")
    assert out == "supply chains"
    assert " " not in out


def test_stripped_tag_before_punctuation_does_not_leave_a_gap():
    assert _clean_inline("regulate <em>ISPs</em> .") == "regulate ISPs."
    assert _clean_inline("costs <b>fell</b> , sharply") == "costs fell, sharply"
    assert _clean_inline("( <em>see</em> annex )") == "(see annex)"


def test_abbr_keeps_the_abbreviation_and_drops_the_expansion():
    html = 'the <abbr title="Internet Service Providers">ISPs</abbr> involved'
    assert _clean_inline(html) == "the ISPs involved"


def test_br_is_a_line_break_not_a_word_join():
    assert _text("<p>first line<br>second line</p>") == "first line second line"
    assert _text("<p>Georgia<br/>Alabama</p>") == "Georgia Alabama"


def test_blockquote_depth_marks_quote_blocks():
    blocks = html_to_blocks(
        "<p>The Secretary said:</p><blockquote><p>We will act.</p></blockquote>"
        "<p>The department published the guidance.</p>"
    )
    assert [k for k, _ in blocks] == ["text", "quote", "text"]
    assert blocks[1][1] == "We will act."


def test_strip_noise_removes_script_and_style_payloads():
    html = "<p>Real prose.</p><script>var x = 'not prose';</script>"
    assert "not prose" not in _text(strip_noise(html))
    assert "Real prose." in _text(strip_noise(html))
    assert "color" not in _text(strip_noise("<style>p{color:red}</style><p>Text.</p>"))
