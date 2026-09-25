from __future__ import annotations

import csv
from datetime import date

import pytest

from eps.assemble import RELEASE_COLUMNS, _topics_at, observation_row, write_dataset
from eps.jel import JELTaxonomy
from eps.models import Document, JELAssignment, Observation
from eps.normalise import (
    html_to_text, make_doc_id, mark_attribution, normalise_text, segment,
    split_sentences,
)
from eps.pipeline import load_taxonomy
from eps.validate import (
    OfficeholderTable, RejectReason, dedupe, reconstruct_quote, validate_jel,
    validate_observations,
)

SPEECH_HTML = """
<div class="govspeak">
  <p>Thank you all for coming today. It is a pleasure to be here.</p>
  <p>We will raise the apprenticeship levy transfer cap to 50 per cent from April.
  This will let large employers fund training in their supply chains, which we
  expect to lift completions among small firms by around a fifth. Dr. Smith of
  the U.K. Skills Council has argued the same for years.</p>
  <p>Let me close by thanking the organisers.</p>
</div>
"""

PRESS_RELEASE_HTML = """
<div class="govspeak">
  <p>The department today announced a new fund. The fund will allocate money to
  regional skills partnerships across the whole of the country.</p>
  <p>The Secretary of State said: "We are committing to a floor on per-pupil
  funding in real terms for the whole of this Parliament." She added that the
  policy would take effect immediately.</p>
</div>
"""


def build_doc(html: str, doc_type: str, institution="Department for Education") -> Document:
    text = html_to_text(html)
    doc_id = make_doc_id("https://example.gov.uk/x", "deadbeef")
    units = mark_attribution(segment(text, doc_id), doc_type)
    return Document(
        doc_id=doc_id, institution=institution, country="UK",
        url="https://example.gov.uk/x", title="Test document",
        doc_type=doc_type, pub_date=date(2026, 3, 1), text=text, units=units,
    )


# --- normalisation ---------------------------------------------------------

def test_paragraph_boundaries_preserved():
    text = html_to_text(SPEECH_HTML)
    assert text.count("\n\n") == 2
    assert "Thank you all" in text
    assert "  " not in text


def test_normalise_is_idempotent():
    text = html_to_text(SPEECH_HTML)
    assert normalise_text(text) == text


def test_abbreviations_do_not_split_sentences():
    para = "Dr. Smith of the U.K. Skills Council spoke. She was clear."
    spans = split_sentences(para)
    assert len(spans) == 2
    assert para[spans[0][0]:spans[0][1]].startswith("Dr. Smith")


def test_unit_offsets_point_at_the_right_text():
    doc = build_doc(SPEECH_HTML, "speech")
    assert doc.units
    for u in doc.units:
        assert doc.text[u.char_start:u.char_end] == u.text


def test_unit_ids_are_stable_across_runs():
    a = build_doc(SPEECH_HTML, "speech")
    b = build_doc(SPEECH_HTML, "speech")
    assert [u.unit_id for u in a.units] == [u.unit_id for u in b.units]
    assert a.doc_id == b.doc_id


# --- quote reconstruction --------------------------------------------------

def test_quote_is_verbatim_substring_of_source():
    doc = build_doc(SPEECH_HTML, "speech")
    ids = [u.unit_id for u in doc.units if u.para_idx == 2][:2]
    quote, reason = reconstruct_quote(doc, ids)
    assert reason == ""
    assert quote in doc.text
    assert quote.startswith("We will raise the apprenticeship levy")


def test_model_cannot_alter_quote_text():
    doc = build_doc(SPEECH_HTML, "speech")
    ids = [u.unit_id for u in doc.units if u.para_idx == 2][:1]
    quote, _ = reconstruct_quote(doc, ids)
    assert quote == doc.unit_map()[ids[0]].text
    assert "50 per cent" in quote and "50%" not in quote


def test_non_contiguous_units_rejected():
    doc = build_doc(SPEECH_HTML, "speech")
    p2 = [u.unit_id for u in doc.units if u.para_idx == 2]
    quote, reason = reconstruct_quote(doc, [p2[0], p2[2]])
    assert quote == "" and reason == RejectReason.NON_CONTIGUOUS


def test_cross_paragraph_units_rejected():
    doc = build_doc(SPEECH_HTML, "speech")
    a = next(u.unit_id for u in doc.units if u.para_idx == 1)
    b = next(u.unit_id for u in doc.units if u.para_idx == 2)
    _, reason = reconstruct_quote(doc, [a, b])
    assert reason == RejectReason.CROSS_PARAGRAPH


def test_hallucinated_unit_id_rejected():
    doc = build_doc(SPEECH_HTML, "speech")
    _, reason = reconstruct_quote(doc, ["Dffffffffff.P099.S099"])
    assert reason == RejectReason.UNKNOWN_UNIT


def test_anchor_must_match_exactly():
    doc = build_doc(SPEECH_HTML, "speech")
    ids = [u.unit_id for u in doc.units if u.para_idx == 2][:1]
    good, reason = reconstruct_quote(
        doc, ids,
        anchor="raise the apprenticeship levy transfer cap to 50 per cent from April",
    )
    assert reason == "" and good in doc.text
    _, reason = reconstruct_quote(
        doc, ids, anchor="raise the apprenticeship levy transfer cap to 50%")
    assert reason == RejectReason.ANCHOR_NOT_FOUND


def test_retyped_anchor_typography_is_forgiven_but_quote_stays_verbatim():
    doc = build_doc(
        "<p>You – they’re not going to rebuild that industry without "
        "private investment from American companies.</p>", "speech")
    ids = [doc.units[0].unit_id]
    quote, reason = reconstruct_quote(
        doc, ids,
        anchor="They're not going to rebuild that industry without private investment")
    assert reason == ""
    assert quote == ("they’re not going to rebuild that industry without "
                     "private investment")
    assert quote in doc.text


def test_short_quotes_rejected():
    doc = build_doc("<p>We act. And then a much longer following sentence here.</p>", "speech")
    _, reason = reconstruct_quote(doc, [doc.units[0].unit_id])
    assert reason == RejectReason.TOO_SHORT


# --- attribution -----------------------------------------------------------

def test_press_release_departmental_prose_not_attributable():
    doc = build_doc(PRESS_RELEASE_HTML, "press_release")
    p1 = [u for u in doc.units if u.para_idx == 1]
    assert p1 and all(not u.attributable for u in p1)
    _, reason = reconstruct_quote(doc, [p1[0].unit_id])
    assert reason == RejectReason.NOT_ATTRIBUTABLE


def test_press_release_quoted_passage_is_attributable():
    doc = build_doc(PRESS_RELEASE_HTML, "press_release")
    quoted = [u for u in doc.units if u.para_idx == 2 and u.attributable]
    assert quoted, "the quoted sentence should be selectable"
    quote, reason = reconstruct_quote(doc, [quoted[0].unit_id])
    assert reason == "" and "floor on per-pupil" in quote


def test_speech_body_is_wholly_attributable():
    doc = build_doc(SPEECH_HTML, "speech")
    assert all(u.attributable for u in doc.units)


# --- JEL -------------------------------------------------------------------

@pytest.fixture(scope="module")
def tax() -> JELTaxonomy:
    return load_taxonomy()


def test_taxonomy_loads_and_has_majors(tax):
    assert len(tax.majors()) >= 15
    assert tax.title("I") is not None


def test_unknown_code_rejected(tax):
    obs = Observation(doc_id="d", unit_ids=[],
                      primary=JELAssignment(major_code="I", sub_code="I9"))
    assert "unknown JEL code" in validate_jel(obs, tax)


def test_inconsistent_hierarchy_rejected(tax):
    sub = next(c for c in tax.codes if c.level == 2 and c.parent == "I")
    wrong_major = "J" if sub.parent != "J" else "H"
    obs = Observation(doc_id="d", unit_ids=[],
                      primary=JELAssignment(major_code=wrong_major, sub_code=sub.code))
    assert "does not sit under" in validate_jel(obs, tax)


def test_wrong_title_rejected(tax):
    sub = next(c for c in tax.codes if c.level == 2)
    obs = Observation(
        doc_id="d", unit_ids=[],
        primary=JELAssignment(
            major_code=sub.parent, major_title=tax.title(sub.parent),
            sub_code=sub.code, sub_title="Something The AEA Never Wrote"),
    )
    assert "does not match the AEA title" in validate_jel(obs, tax)


def test_fill_titles_makes_assignment_valid(tax):
    sub = next(c for c in tax.codes if c.level == 2)
    a = tax.fill_titles(JELAssignment(major_code=sub.parent, sub_code=sub.code))
    assert validate_jel(Observation(doc_id="d", unit_ids=[], primary=a), tax) == ""


def test_detailed_without_parent_rejected(tax):
    det = next(c for c in tax.codes if c.level == 3)
    obs = Observation(doc_id="d", unit_ids=[],
                      primary=JELAssignment(major_code=det.parent[0],
                                            detailed_code=det.code))
    assert "without its parent" in validate_jel(obs, tax)


def test_too_many_secondaries_rejected(tax):
    a = tax.fill_titles(JELAssignment(major_code="I"))
    obs = Observation(doc_id="d", unit_ids=[], primary=a, secondary=[a, a, a])
    assert "more than two" in validate_jel(obs, tax)


# --- end to end ------------------------------------------------------------

def test_full_validation_and_row_assembly(tax):
    doc = build_doc(SPEECH_HTML, "speech")
    ids = [u.unit_id for u in doc.units if u.para_idx == 2][:2]
    sub = next(c for c in tax.codes if c.level == 2 and c.parent == "J")
    primary = tax.fill_titles(JELAssignment(major_code="J", sub_code=sub.code))
    obs = Observation(doc_id=doc.doc_id, unit_ids=ids, primary=primary,
                      model_id="test", prompt_version="P1-units")

    holders = OfficeholderTable([
        {"institution": "Department for Education", "person": "A Minister",
         "role": "Secretary of State", "start_date": date(2026, 1, 1),
         "end_date": None}])
    validated, speaker, source, warning = validate_observations(doc, [obs], tax, holders)

    assert speaker == "A Minister"
    assert source == "officeholder_table" and warning == ""
    assert validated[0].valid, validated[0].reject_reason

    row = observation_row(doc, validated[0], speaker)
    for col in ("agency", "speaker", "document_title", "document_type",
                "date", "url", "direct_quote", "economics_topics",
                "jel_major_categories", "jel_subcategories"):
        assert row[col] != "", f"{col} is empty"
    assert row["direct_quote"] in doc.text
    assert row["date"] == "2026-03-01"


def test_release_header_is_the_agreed_contract(tmp_path, tax):
    """The release header is what the supervisor reads. Pin it on disk.

    `observation_row` producing a key is not the same as `write_dataset` writing
    the column: the writer has its own field list, and drops anything missing
    from it without complaint (`extrasaction="ignore"`).
    """
    sub = next(c for c in tax.codes if c.level == 2 and c.parent == "J")
    obs = Observation(doc_id="d", unit_ids=["u1"],
                      primary=tax.fill_titles(
                          JELAssignment(major_code="J", sub_code=sub.code)))
    doc = build_doc(SPEECH_HTML, "speech")
    release, _ = write_dataset([observation_row(doc, obs, "A Minister")], tmp_path)

    with open(release, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        header, row = reader.fieldnames, next(reader)

    assert header == [
        "agency", "speaker", "document_title", "document_type", "date", "url",
        "direct_quote", "quote_in_context", "intention",
        "economics_topics",
        "jel_major_categories", "jel_subcategories",
    ]
    assert header == RELEASE_COLUMNS
    # A build that never ran the context stage still fills the column, so a
    # reader never meets a blank one.
    assert row["quote_in_context"] == row["direct_quote"]
    assert row["jel_major_categories"] == f"J — {tax.title('J')}"
    assert row["jel_subcategories"] == f"{sub.code} — {sub.title}"


def test_rolled_up_jel_columns_name_the_parents_once(tax):
    """The rolled-up columns carry code and title, and say a shared parent once."""
    subs = [c for c in tax.codes if c.level == 2 and c.parent == "J"][:2]
    primary = tax.fill_titles(JELAssignment(major_code="J", sub_code=subs[0].code))
    second = tax.fill_titles(JELAssignment(major_code="J", sub_code=subs[1].code))
    obs = Observation(doc_id="d", unit_ids=["u1"], primary=primary,
                      secondary=[second])

    majors = _topics_at(obs, "major")
    assert majors == f"J — {tax.title('J')}"

    sub_labels = _topics_at(obs, "sub").split("; ")
    assert sub_labels == [f"{c.code} — {c.title}" for c in subs]


def test_ineligible_speaker_blocks_everything(tax):
    doc = build_doc(SPEECH_HTML, "speech")
    obs = Observation(doc_id=doc.doc_id, unit_ids=[doc.units[1].unit_id])
    holders = OfficeholderTable([
        {"institution": "Department for Education", "person": "A Minister",
         "role": "SoS", "start_date": date(2026, 6, 1), "end_date": None}])
    validated, speaker, source, _ = validate_observations(doc, [obs], tax, holders)
    assert speaker is None and source == ""
    assert validated[0].reject_reason == RejectReason.NO_ELIGIBLE_SPEAKER


def test_duplicate_quotes_dropped():
    a = Observation(doc_id="d", unit_ids=["x"], quote="We will fund it fully.", valid=True)
    b = Observation(doc_id="e", unit_ids=["y"], quote="We  will fund it fully!", valid=True)
    out = dedupe([a, b])
    assert out[0].valid
    assert out[1].reject_reason == RejectReason.DUPLICATE


# --- quoted-span trimming --------------------------------------------------

def test_attribution_frame_trimmed_from_press_release_quote():
    doc = build_doc(PRESS_RELEASE_HTML, "press_release")
    u = next(u for u in doc.units if u.para_idx == 2 and u.attributable)
    quote, reason = reconstruct_quote(doc, [u.unit_id])
    assert reason == ""
    assert not quote.startswith("The Secretary of State said")
    assert quote.startswith("We are committing to a floor")
    assert quote in doc.text          # still verbatim
    assert '"' not in quote           # framing quotes removed


def test_speech_quotes_are_not_trimmed():
    from eps.validate import trim_to_quoted_span
    doc = build_doc(SPEECH_HTML, "speech")
    u = next(u for u in doc.units if u.para_idx == 2)
    quote, _ = reconstruct_quote(doc, [u.unit_id])
    assert quote == u.text


def test_trim_leaves_unbalanced_quotes_alone():
    from eps.validate import trim_to_quoted_span
    assert trim_to_quoted_span('She said "we will act') == 'She said "we will act'
    assert trim_to_quoted_span("No quotes at all here") == "No quotes at all here"
    assert trim_to_quoted_span('He said: "we will act now."') == "we will act now."
    assert trim_to_quoted_span('\u201csmart quotes work too\u201d') == "smart quotes work too"


def test_trim_does_not_break_apostrophes():
    from eps.validate import trim_to_quoted_span
    s = "We won't cut the nation's schools budget."
    assert trim_to_quoted_span(s) == s
