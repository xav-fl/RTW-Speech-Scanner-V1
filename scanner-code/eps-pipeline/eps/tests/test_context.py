"""Tests for the editorial-context stage.

Every test here runs against `FakeProvider`, so the whole stage is exercised
with no network and no cost. The canned responses are the point: they let a
malformed or dishonest model response be written down exactly and the code's
answer to it pinned.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from eps.context import (
    MAX_INSERTION_WORDS, Contextualiser, Status, build_quote_in_context,
    clean_document_text, quote_id, summarise,
)
from eps.models import ContextRow, Document, Insertion
from eps.providers import FakeProvider

# The example from the brief: the quote names no action, the title does.
USDA_TITLE = (
    "USDA Strengthens National Security and Protects Taxpayers by "
    "Standardizing Grant and Cooperative Agreement Requirements"
)
USDA_QUOTE = (
    "Today’s action not only reduces government bureaucracy and makes it "
    "easier for USDA customers to access our programs, but it also strengthens "
    "our ability to take swift action."
)
USDA_TEXT = (
    "(Washington, D.C., December 31, 2025) — Today, U.S. Secretary of "
    "Agriculture Brooke L. Rollins signed a Secretary’s Memorandum "
    "directing all USDA agencies to adopt the first-ever set of USDA General "
    "Terms and Conditions for all future awards.\n\n"
    "> " + USDA_QUOTE + "\n"
)


def make_doc(doc_id="D8498242a1d", title=USDA_TITLE, text=USDA_TEXT) -> Document:
    return Document(
        doc_id=doc_id,
        institution="Department of Agriculture",
        country="US",
        url=f"https://usda.gov/{doc_id}",
        title=title,
        doc_type="press_release",
        pub_date=date(2025, 12, 31),
        text=text,
    )


def make_row(doc: Document, quote=USDA_QUOTE, unit_ids="D8498242a1d.P004.S001",
             anchor="") -> dict:
    return {
        "doc_id": doc.doc_id,
        "url": doc.url,
        "agency": doc.institution,
        "speaker": "Brooke Rollins",
        "date": doc.pub_date.isoformat(),
        "document_title": doc.title,
        "direct_quote": quote,
        "unit_ids": unit_ids,
        "anchor": anchor,
    }


def scripted(triage: object, resolve: object) -> FakeProvider:
    """A provider that answers triage and resolve calls from canned objects.

    Which prompt arrived is told from the system text, so the order of calls is
    not baked into the fixture. A value that is already a string is returned
    as-is, which is how malformed responses are tested.
    """

    def responder(system: str, user: str) -> str:
        payload = triage if "screening direct quotations" in system else resolve
        if callable(payload):
            payload = payload(user)
        return payload if isinstance(payload, str) else json.dumps(payload)

    return FakeProvider(responder)


def run_stage(rows, docs, triage, resolve, **kw):
    ctx = Contextualiser(provider=scripted(triage, resolve), **kw)
    return ctx.run(rows, docs)


def triage_yes(qid, expressions=("Today’s action",)):
    return [{"quote_id": qid, "needs_context": True,
             "expressions": list(expressions)}]


def resolve_ok(qid, insertions, status="resolved", note=""):
    return [{"quote_id": qid, "status": status, "insertions": insertions,
             "note": note}]


# --- 1. the worked example -------------------------------------------------


def test_usda_example_resolves_with_the_title_as_evidence():
    doc, = [make_doc()]
    row = make_row(doc)
    qid = quote_id(row)
    out = run_stage(
        [row], [doc], triage_yes(qid),
        resolve_ok(qid, [{
            "anchor": "Today’s action",
            "insertion": "standardizing grant and cooperative agreement requirements",
            # evidence taken from the title, which the brief allows
            "evidence": "Standardizing Grant and Cooperative Agreement Requirements",
        }]),
    )
    assert len(out) == 1
    assert out[0].final_status == Status.RESOLVED
    assert out[0].quote_in_context.startswith(
        "Today’s action [standardizing grant and cooperative agreement "
        "requirements] not only reduces"
    )
    assert out[0].triage_expressions == ["Today’s action"]


# --- 2. two insertions, and the round trip ---------------------------------


def test_two_insertions_build_and_round_trip():
    quote = "This program will help these producers recover."
    doc = make_doc(text="The Emergency Livestock Relief Program pays "
                        "drought-affected cattle producers.", title="Relief")
    row = make_row(doc, quote=quote)
    qid = quote_id(row)
    out = run_stage(
        [row], [doc],
        triage_yes(qid, ("This program", "these producers")),
        resolve_ok(qid, [
            {"anchor": "This program",
             "insertion": "the Emergency Livestock Relief Program",
             "evidence": "The Emergency Livestock Relief Program"},
            {"anchor": "these producers",
             "insertion": "drought-affected cattle producers",
             "evidence": "drought-affected cattle producers"},
        ]),
    )
    assert out[0].final_status == Status.RESOLVED
    assert out[0].quote_in_context == (
        "This program [the Emergency Livestock Relief Program] will help these "
        "producers [drought-affected cattle producers] recover."
    )
    # round trip is enforced in code, but assert it here too
    import re
    assert re.sub(r" \[[^\[\]]*\]", "", out[0].quote_in_context) == quote


# --- 3. each failure code fires --------------------------------------------

EVIDENCE = "The Emergency Livestock Relief Program"
DOCTEXT = "The Emergency Livestock Relief Program pays producers."


def ins(anchor="the program", insertion="Emergency Livestock Relief Program",
        evidence=EVIDENCE) -> Insertion:
    return Insertion(anchor=anchor, insertion=insertion, evidence=evidence)


@pytest.mark.parametrize("quote, insertions, expected", [
    # anchor absent from the quote
    ("We will fund it.", [ins(anchor="the program")],
     Status.FAILED_ANCHOR_NOT_FOUND),
    # anchor appears twice, so the insertion point is ambiguous
    ("the program and the program again.", [ins(anchor="the program")],
     Status.FAILED_ANCHOR_NOT_UNIQUE),
    # evidence is nowhere in the document or title
    ("the program helps.", [ins(evidence="a passage never published")],
     Status.FAILED_EVIDENCE_NOT_FOUND),
    # empty insertion
    ("the program helps.", [ins(insertion="   ")], Status.FAILED_INSERTION_FORMAT),
    # insertion over the word limit
    ("the program helps.", [ins(insertion=" ".join(["word"] * 13))],
     Status.FAILED_INSERTION_FORMAT),
    # brackets inside an insertion would break the round trip
    ("the program helps.", [ins(insertion="a [nested] bracket")],
     Status.FAILED_INSERTION_FORMAT),
])
def test_failure_codes_fire(quote, insertions, expected):
    got = build_quote_in_context(quote, insertions, DOCTEXT, "Title")
    assert got.status == expected
    assert got.text == quote  # the row keeps its plain quote


def test_too_many_insertions():
    quote = "a b c d"
    four = [Insertion(anchor=c, insertion="x", evidence="x") for c in "abcd"]
    got = build_quote_in_context(quote, four, "x", "")
    assert got.status == Status.FAILED_TOO_MANY_INSERTIONS


def test_overlapping_anchors():
    quote = "the relief program helps."
    got = build_quote_in_context(
        quote,
        [Insertion("the relief", "ELRP", "ELRP"),
         Insertion("relief program", "ELRP", "ELRP")],
        "ELRP", "",
    )
    assert got.status == Status.FAILED_OVERLAPPING_ANCHORS


def test_roundtrip_guard_catches_a_quote_that_already_had_brackets():
    # build_quote_in_context is also reachable directly; a quote carrying a
    # bracket makes the strip ambiguous and must not silently corrupt the text.
    quote = "the program [sic] helps."
    got = build_quote_in_context(quote, [ins()], DOCTEXT, "")
    assert got.status == Status.FAILED_ROUNDTRIP
    assert got.text == quote


# --- 4. triage response integrity ------------------------------------------


def test_triage_missing_and_duplicated_ids_both_fail():
    doc = make_doc()
    rows = [make_row(doc, quote=f"Quote number {i} about this policy.",
                     unit_ids=f"U{i}") for i in range(3)]
    ids = [quote_id(r) for r in rows]
    # id[0] duplicated, id[1] present once, id[2] missing altogether
    triage = [
        {"quote_id": ids[0], "needs_context": False, "expressions": []},
        {"quote_id": ids[0], "needs_context": False, "expressions": []},
        {"quote_id": ids[1], "needs_context": False, "expressions": []},
    ]
    out = run_stage(rows, [doc], triage, [])
    by_id = {r.quote_id: r for r in out}
    assert by_id[ids[0]].final_status == Status.FAILED_TRIAGE_MISSING_ID
    assert by_id[ids[1]].final_status == Status.NOT_NEEDED_TRIAGE
    assert by_id[ids[2]].final_status == Status.FAILED_TRIAGE_MISSING_ID


def test_triage_drops_expressions_that_are_not_in_the_quote():
    doc = make_doc()
    row = make_row(doc)
    qid = quote_id(row)
    out = run_stage([row], [doc],
                    triage_yes(qid, ("a phrase the speaker never said",)), [])
    assert out[0].final_status == Status.FAILED_TRIAGE_NO_EXPRESSIONS
    assert out[0].triage_expressions == []


def test_unparseable_triage_response_is_logged_not_ignored():
    doc = make_doc()
    row = make_row(doc)
    out = run_stage([row], [doc], "I'm afraid I can't help with that.", [])
    assert out[0].final_status == Status.FAILED_TRIAGE_PARSE
    assert out[0].quote_in_context == USDA_QUOTE


# --- 5. existing brackets ---------------------------------------------------


def test_quote_with_existing_brackets_is_set_aside_without_a_model_call():
    doc = make_doc()
    row = make_row(doc, quote="We will fund [sic] the program.")
    provider = scripted([], [])
    out = Contextualiser(provider=provider).run([row], [doc])
    assert out[0].final_status == Status.MANUAL_REVIEW_EXISTING_BRACKETS
    assert out[0].quote_in_context == row["direct_quote"]
    assert provider.calls == 0


# --- 6. token budget --------------------------------------------------------


def test_document_over_budget_is_refused_not_truncated():
    long_text = "word " * 20_000  # ~25k tokens
    doc = make_doc(text=long_text)
    row = make_row(doc)
    qid = quote_id(row)
    sent: list[str] = []

    def resolve(user):  # pragma: no cover - asserted not to run
        sent.append(user)
        return json.dumps([])

    out = run_stage([row], [doc], triage_yes(qid), resolve, max_doc_tokens=1000)
    assert out[0].final_status == Status.FAILED_DOCUMENT_TOO_LONG
    assert sent == []  # no truncated document was ever sent
    assert out[0].quote_in_context == USDA_QUOTE


# --- 7 & 8. invariants over the whole stage ---------------------------------


def test_direct_quote_is_untouched_and_every_row_gets_one_status():
    doc = make_doc()
    rows = [
        make_row(doc),                                            # resolves
        make_row(doc, quote="We will fund [sic] it.", unit_ids="U2"),  # brackets
        make_row(doc, quote="We will raise the levy to 50 per cent.",
                 unit_ids="U3"),                                  # not needed
    ]
    ids = [quote_id(r) for r in rows]
    before = [r["direct_quote"] for r in rows]

    triage = [
        {"quote_id": ids[0], "needs_context": True,
         "expressions": ["Today’s action"]},
        {"quote_id": ids[2], "needs_context": False, "expressions": []},
    ]
    resolve = resolve_ok(ids[0], [{
        "anchor": "Today’s action",
        "insertion": "standardizing grant requirements",
        "evidence": "Standardizing Grant and Cooperative Agreement Requirements",
    }])
    out = run_stage(rows, [doc], triage, resolve)

    assert len(out) == len(rows)                       # rows in == rows out
    assert [r.direct_quote for r in out] == before     # byte-identical
    assert all(r.final_status for r in out)            # exactly one status each
    assert sum(summarise(out).values()) == len(rows)
    statuses = {r.quote_id: r.final_status for r in out}
    assert statuses[ids[0]] == Status.RESOLVED
    assert statuses[ids[1]] == Status.MANUAL_REVIEW_EXISTING_BRACKETS
    assert statuses[ids[2]] == Status.NOT_NEEDED_TRIAGE


def test_unresolved_and_not_needed_from_the_resolve_step():
    doc = make_doc()
    row = make_row(doc)
    qid = quote_id(row)
    for model_status, expected in [
        ("unresolved", Status.UNRESOLVED),
        ("not_needed", Status.NOT_NEEDED_RESOLVE),
    ]:
        out = run_stage([row], [doc], triage_yes(qid),
                        resolve_ok(qid, [], status=model_status, note="why"))
        assert out[0].final_status == expected
        assert out[0].quote_in_context == USDA_QUOTE
        assert out[0].model_note == "why"


# --- caching ----------------------------------------------------------------


def test_rerun_with_unchanged_inputs_makes_no_new_calls(tmp_path):
    from eps.extract import ResponseCache

    doc = make_doc()
    row = make_row(doc)
    qid = quote_id(row)
    cache = ResponseCache(tmp_path / "cache")
    provider = scripted(triage_yes(qid), resolve_ok(qid, [{
        "anchor": "Today’s action",
        "insertion": "standardizing grant requirements",
        "evidence": "Standardizing Grant and Cooperative Agreement Requirements",
    }]))

    first = Contextualiser(provider=provider, cache=cache).run([row], [doc])
    calls_after_first = provider.calls
    assert calls_after_first == 2  # one triage, one resolve

    second = Contextualiser(provider=provider, cache=cache).run([row], [doc])
    assert provider.calls == calls_after_first  # replayed, nothing new
    assert second[0].quote_in_context == first[0].quote_in_context


def test_changing_the_prompt_version_invalidates_the_cache(tmp_path):
    from eps.extract import ResponseCache

    doc = make_doc()
    row = make_row(doc)
    qid = quote_id(row)
    cache = ResponseCache(tmp_path / "cache")
    provider = scripted(triage_yes(qid), resolve_ok(qid, []))

    Contextualiser(provider=provider, cache=cache).run([row], [doc])
    before = provider.calls
    Contextualiser(provider=provider, cache=cache,
                   triage_prompt_version="CTX-TRIAGE-vNEXT").run([row], [doc])
    assert provider.calls > before


# --- text handling ----------------------------------------------------------


def test_renderer_markers_are_stripped_but_a_published_angle_bracket_survives():
    assert clean_document_text("> quoted line\nplain") == "quoted line\nplain"
    assert clean_document_text("## Heading\nbody") == "Heading\nbody"
    # an inequality the agency published is not a marker
    assert clean_document_text("we need x > y here") == "we need x > y here"


def test_evidence_matches_across_a_line_break_in_the_stored_text():
    # whitespace may be collapsed for the comparison, and only for it
    quote = "the program helps."
    got = build_quote_in_context(
        quote, [ins(evidence="Emergency Livestock\n   Relief Program")],
        "The Emergency Livestock Relief Program pays.", "",
    )
    assert got.status == Status.RESOLVED


def test_evidence_matches_when_only_the_apostrophe_shape_differs():
    """A model retyping a curly apostrophe straight is not a paraphrase.

    In the first trial run this alone caused 8 of 14 evidence failures, every
    one a passage the document really did contain.
    """
    got = build_quote_in_context(
        "the program helps.",
        [ins(evidence="the UK's publicly owned energy company")],
        "Great British Energy, the UK’s publicly owned energy company, "
        "will invest.", "",
    )
    assert got.status == Status.RESOLVED


@pytest.mark.parametrize("evidence", [
    # stitched across an interviewer's interruption, as Rubio's was
    "All those oilfields that used to produce a lot - and wealth for their people",
    # two non-adjacent passages joined with an ellipsis
    "the next UK-EU summit rescheduled... on agrifoods and emissions trading",
])
def test_folding_punctuation_does_not_let_spliced_evidence_through(evidence):
    doc = (
        "All those oilfields that used to produce a lot — QUESTION: Right. "
        "SECRETARY RUBIO: — and wealth for their people. I want to see the "
        "next UK-EU summit rescheduled as soon as possible, and much else "
        "besides, on agrifoods and emissions trading."
    )
    got = build_quote_in_context("the program helps.", [ins(evidence=evidence)],
                                 doc, "")
    assert got.status == Status.FAILED_EVIDENCE_NOT_FOUND


def test_anchor_with_a_straight_apostrophe_matches_a_curly_quote():
    """The brief's own example failed this way in the first trial run."""
    got = build_quote_in_context(
        USDA_QUOTE,  # holds U+2019
        [Insertion(anchor="Today's action",          # straight
                   insertion="standardizing grant requirements",
                   evidence="Standardizing Grant and Cooperative Agreement "
                            "Requirements")],
        USDA_TEXT, USDA_TITLE,
    )
    assert got.status == Status.RESOLVED
    # spliced at the right place in the ORIGINAL text, curly apostrophe intact
    assert got.text.startswith(
        "Today’s action [standardizing grant requirements] not only"
    )


def test_punctuation_fold_is_length_preserving():
    """Anchor offsets index the unfolded quote, so the fold must stay 1:1."""
    from eps.context import fold_punctuation

    for s in ["‘a’", "“b”", "x—y", "n m",
              "…", USDA_QUOTE]:
        assert len(fold_punctuation(s)) == len(s), s


def test_triage_expression_matches_across_apostrophe_shapes():
    doc = make_doc()
    row = make_row(doc)
    qid = quote_id(row)
    out = run_stage(
        [row], [doc],
        triage_yes(qid, ("Today's action",)),  # straight, quote has curly
        resolve_ok(qid, [{
            "anchor": "Today’s action",
            "insertion": "standardizing grant requirements",
            "evidence": "Standardizing Grant and Cooperative Agreement Requirements",
        }]),
    )
    assert out[0].final_status == Status.RESOLVED


@pytest.mark.parametrize("raw, want", [
    (", Contracts for Difference AR7,", "Contracts for Difference AR7"),
    ("— £86.5 million in ITM Power —", "£86.5 million in ITM Power"),
    ("(several senior RSF commanders)", "several senior RSF commanders"),
    ("health visitors,", "health visitors"),
    ("the Right to Manage", "the Right to Manage"),
])
def test_insertions_are_trimmed_of_edge_punctuation(raw, want):
    """9 of 24 resolved rows in the first trial run read `[, like this,]`."""
    from eps.context import tidy_insertion

    assert tidy_insertion(raw) == want


def test_an_insertion_that_is_only_punctuation_still_fails_format():
    got = build_quote_in_context("the program helps.", [ins(insertion=" ,,-- ")],
                                 DOCTEXT, "")
    assert got.status == Status.FAILED_INSERTION_FORMAT


def test_evidence_is_not_matched_case_insensitively():
    quote = "the program helps."
    got = build_quote_in_context(
        quote, [ins(evidence="emergency livestock relief program")],
        DOCTEXT, "",
    )
    assert got.status == Status.FAILED_EVIDENCE_NOT_FOUND


def test_quote_id_is_stable_and_keyed_on_the_units_not_the_text():
    doc = make_doc()
    a = make_row(doc, quote="one wording")
    b = make_row(doc, quote="another wording")
    assert quote_id(a) == quote_id(b)          # same units -> same id
    assert quote_id(a) != quote_id(make_row(doc, unit_ids="different"))


def test_anchor_outside_the_triage_expressions_warns_but_does_not_fail():
    got = build_quote_in_context(
        "the program helps.", [ins()], DOCTEXT, "",
        triage_expressions=["something else entirely"],
    )
    assert got.status == Status.RESOLVED
    assert any("warn_anchor_not_from_triage" in w for w in got.warnings)


def test_log_records_the_tidied_insertion_not_the_raw_one():
    """The validation log and the dataset must agree on what was added."""
    doc = make_doc()
    row = make_row(doc)
    qid = quote_id(row)
    out = run_stage(
        [row], [doc], triage_yes(qid),
        resolve_ok(qid, [{
            "anchor": "Today\u2019s action",
            "insertion": ", standardizing grant requirements,",   # raw, messy
            "evidence": "Standardizing Grant and Cooperative Agreement Requirements",
        }]),
    )
    assert out[0].final_status == Status.RESOLVED
    assert out[0].insertions[0].insertion == "standardizing grant requirements"
    assert f"[{out[0].insertions[0].insertion}]" in out[0].quote_in_context


# --- opening frames (position: "before") -----------------------------------

LAMMY = ("That\u2019s why the UK wholeheartedly endorses the Call to Action to "
         "all development actors, and we encourage you to join us.")
LAMMY_DOC = ("Shifting the power: modern partnerships in practice. We have "
             "spoken today about locally led development and the Call to "
             "Action issued at this conference.")


def test_opening_frame_is_placed_before_the_first_word():
    got = build_quote_in_context(
        LAMMY,
        [Insertion(anchor="", insertion="on locally led development",
                   evidence="locally led development", position="before")],
        LAMMY_DOC, "",
    )
    assert got.status == Status.RESOLVED
    assert got.text == f"[on locally led development] {LAMMY}"


def test_opening_frame_round_trips():
    import re
    got = build_quote_in_context(
        LAMMY,
        [Insertion(anchor="", insertion="on locally led development",
                   evidence="locally led development", position="before")],
        LAMMY_DOC, "",
    )
    stripped = re.sub(r"^\[[^\[\]]*\] ", "", got.text)
    assert re.sub(r" \[[^\[\]]*\]", "", stripped) == LAMMY


def test_opening_frame_combines_with_an_anchored_insertion():
    got = build_quote_in_context(
        LAMMY,
        [
            Insertion(anchor="", insertion="on locally led development",
                      evidence="locally led development", position="before"),
            Insertion(anchor="the Call to Action",
                      insertion="issued at this conference",
                      evidence="the Call to Action issued at this conference"),
        ],
        LAMMY_DOC, "",
    )
    assert got.status == Status.RESOLVED
    assert got.text.startswith("[on locally led development] That\u2019s why")
    assert "the Call to Action [issued at this conference]" in got.text
    import re
    stripped = re.sub(r"^\[[^\[\]]*\] ", "", got.text)
    assert re.sub(r" \[[^\[\]]*\]", "", stripped) == LAMMY


def test_two_opening_frames_are_refused():
    two = [Insertion(anchor="", insertion=f"frame {i}",
                     evidence="locally led development", position="before")
           for i in range(2)]
    got = build_quote_in_context(LAMMY, two, LAMMY_DOC, "")
    assert got.status == Status.FAILED_TOO_MANY_INSERTIONS


def test_opening_frame_still_needs_evidence():
    got = build_quote_in_context(
        LAMMY,
        [Insertion(anchor="", insertion="on something invented",
                   evidence="a passage never published", position="before")],
        LAMMY_DOC, "",
    )
    assert got.status == Status.FAILED_EVIDENCE_NOT_FOUND
    assert got.text == LAMMY


def test_one_malformed_entry_does_not_sink_the_rest_of_the_document():
    """A speech announcing "project reset" broke a whole document's response."""
    doc = make_doc()
    rows = [make_row(doc, quote=f"This program number {i} helps.", unit_ids=f"U{i}")
            for i in range(3)]
    ids = [quote_id(r) for r in rows]
    triage = [{"quote_id": i, "needs_context": True,
               "expressions": ["This program"]} for i in ids]
    # the middle object carries an unescaped double quote, as the model emitted
    resolve = (
        '[{"quote_id": "%s", "status": "unresolved", "insertions": [], "note": "a"},'
        ' {"quote_id": "%s", "status": "unresolved", "insertions": [], "note": "I launched "project reset" today"},'
        ' {"quote_id": "%s", "status": "unresolved", "insertions": [], "note": "c"}]'
        % (ids[0], ids[1], ids[2])
    )
    out = run_stage(rows, [doc], triage, resolve)
    by = {r.quote_id: r.final_status for r in out}
    assert by[ids[0]] == Status.UNRESOLVED       # salvaged
    assert by[ids[2]] == Status.UNRESOLVED       # salvaged
    assert by[ids[1]] == Status.FAILED_RESOLVE_MISSING_ID  # the broken one only


def test_triage_is_not_shown_the_document_title():
    doc = make_doc(title="GSA Awards Interim Leasing Support Services Contract")
    row = make_row(doc)
    seen = []

    def triage(user):
        seen.append(user)
        return json.dumps([{"quote_id": quote_id(row), "needs_context": False,
                            "expressions": []}])

    run_stage([row], [doc], triage, [])
    assert "GSA Awards Interim" not in seen[0]
    assert "Brooke Rollins" in seen[0]  # speaker and agency still supplied
