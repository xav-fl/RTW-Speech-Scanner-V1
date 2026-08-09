from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

import pytest

from eps.extract import Extractor, render_units
from eps.harvest.local import (
    IngestError, MANIFEST_COLUMNS, extract_text, ingest_manifest, ingest_row,
    validate_row, write_template,
)
from eps.pipeline import load_taxonomy

SPEECH_TXT = """Thank you to the organisers, and good morning to everyone here.

From April we will raise the apprenticeship levy transfer cap to 50 per cent. Larger employers will be able to fund training across their supply chains.

It has been a pleasure to speak with you today."""

SPEECH_HTML = """<html><body><article>
<p>Good morning, and thank you for having me.</p>
<p>We are committing to a real-terms floor on per-pupil funding for the whole of this Parliament.</p>
</article></body></html>"""


@pytest.fixture
def docs_dir(tmp_path: Path) -> Path:
    d = tmp_path / "docs"
    d.mkdir()
    (d / "skills_speech.txt").write_text(SPEECH_TXT, encoding="utf-8")
    (d / "funding_speech.html").write_text(SPEECH_HTML, encoding="utf-8")
    (d / "notes.xyz").write_text("unsupported", encoding="utf-8")
    return d


def _row(path: Path, **over) -> dict:
    row = {
        "path": str(path), "institution": "Department for Education",
        "country": "UK", "url": "https://www.gov.uk/government/speeches/a",
        "title": "A speech", "doc_type": "speech", "date": "2026-03-04",
        "delivery_status": "unknown", "speaker_hint": "", "notes": "",
    }
    row.update(over)
    return row


# --- text extraction -------------------------------------------------------

def test_extract_txt_preserves_paragraphs(docs_dir):
    text = extract_text(docs_dir / "skills_speech.txt")
    assert text.count("\n\n") == 2
    assert "apprenticeship levy transfer cap to 50 per cent" in text


def test_extract_html_strips_markup(docs_dir):
    text = extract_text(docs_dir / "funding_speech.html")
    assert "<p>" not in text
    assert "real-terms floor on per-pupil funding" in text


def test_unsupported_type_raises(docs_dir):
    with pytest.raises(IngestError):
        extract_text(docs_dir / "notes.xyz")


# --- manifest --------------------------------------------------------------

def test_template_lists_only_supported_files(docs_dir, tmp_path):
    out = tmp_path / "manifest.csv"
    n = write_template(list(docs_dir.rglob("*")), out, country="UK")
    assert n == 2
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert list(rows[0]) == MANIFEST_COLUMNS
    assert all(r["country"] == "UK" for r in rows)
    assert not any(r["path"].endswith(".xyz") for r in rows)


@pytest.mark.parametrize("bad,expect", [
    ({"date": ""}, "date is empty"),
    ({"date": "04/03/2026"}, "not ISO format"),
    ({"institution": ""}, "institution is empty"),
    ({"country": "FR"}, "country must be"),
    ({"url": ""}, "url is empty"),
    ({"doc_type": "rant"}, "doc_type"),
    ({"delivery_status": "maybe"}, "delivery_status"),
])
def test_bad_metadata_is_caught(docs_dir, bad, expect):
    problems = validate_row(_row(docs_dir / "skills_speech.txt", **bad), 2)
    assert any(expect in p for p in problems), problems


def test_missing_file_is_caught(tmp_path):
    problems = validate_row(_row(tmp_path / "nope.txt"), 2)
    assert any("file not found" in p for p in problems)


def test_good_row_has_no_problems(docs_dir):
    assert validate_row(_row(docs_dir / "skills_speech.txt"), 2) == []


def test_strict_mode_refuses_bad_manifest(docs_dir, tmp_path):
    m = tmp_path / "m.csv"
    with m.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=MANIFEST_COLUMNS)
        w.writeheader()
        w.writerow(_row(docs_dir / "skills_speech.txt", date=""))
    with pytest.raises(IngestError):
        ingest_manifest(m, None, strict=True)


def test_lenient_mode_skips_bad_rows(docs_dir, tmp_path):
    m = tmp_path / "m.csv"
    with m.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=MANIFEST_COLUMNS)
        w.writeheader()
        w.writerow(_row(docs_dir / "skills_speech.txt"))
        w.writerow(_row(docs_dir / "funding_speech.html", country="FR"))
    docs, errors = ingest_manifest(m, None, strict=False)
    assert len(docs) == 1 and errors


# --- document construction -------------------------------------------------

def test_ingested_doc_matches_harvested_shape(docs_dir):
    doc = ingest_row(_row(docs_dir / "skills_speech.txt"))
    assert doc.country == "UK"
    assert doc.pub_date == date(2026, 3, 4)
    assert doc.source_index == "local_ingest"
    assert doc.segmenter_version and doc.raw_sha256 and doc.text_sha256
    assert doc.units
    for u in doc.units:
        assert doc.text[u.char_start:u.char_end] == u.text


def test_ingest_is_deterministic(docs_dir):
    a = ingest_row(_row(docs_dir / "skills_speech.txt"))
    b = ingest_row(_row(docs_dir / "skills_speech.txt"))
    assert a.doc_id == b.doc_id
    assert [u.unit_id for u in a.units] == [u.unit_id for u in b.units]


def test_tracking_params_stripped_from_url(docs_dir):
    doc = ingest_row(_row(
        docs_dir / "skills_speech.txt",
        url="https://www.gov.uk/government/speeches/a?utm_source=x&id=7"))
    assert "utm_source" not in doc.url and "id=7" in doc.url


def test_as_prepared_detected_from_text(docs_dir, tmp_path):
    p = tmp_path / "prepared.txt"
    p.write_text("Remarks as prepared for delivery.\n\n" + SPEECH_TXT, encoding="utf-8")
    doc = ingest_row(_row(p, delivery_status="unknown"))
    assert doc.delivery_status == "as_prepared"


def test_explicit_delivery_status_is_respected(docs_dir):
    doc = ingest_row(_row(docs_dir / "skills_speech.txt",
                          delivery_status="as_delivered"))
    assert doc.delivery_status == "as_delivered"


# --- identity blinding -----------------------------------------------------

def _extractor(mode: str) -> Extractor:
    return Extractor(load_taxonomy(), client=object(), identity_mode=mode)


def test_blind_mode_withholds_identity(docs_dir):
    doc = ingest_row(_row(docs_dir / "skills_speech.txt",
                          title="Skills for growth: Minister's speech"))
    msg = _extractor("blind").build_user_message(doc, "A Minister")
    assert "A Minister" not in msg
    assert "Department for Education" not in msg
    assert "Skills for growth" not in msg
    assert "DOCUMENT TYPE: speech" in msg
    assert "DATE: 2026-03-04" in msg


def test_full_mode_includes_identity(docs_dir):
    doc = ingest_row(_row(docs_dir / "skills_speech.txt",
                          title="Skills for growth: Minister's speech"))
    msg = _extractor("full").build_user_message(doc, "A Minister")
    assert "A Minister" in msg
    assert "Department for Education" in msg
    assert "Skills for growth" in msg


def test_both_modes_show_the_same_document_text(docs_dir):
    doc = ingest_row(_row(docs_dir / "skills_speech.txt"))
    units = render_units(doc)
    for mode in ("blind", "full"):
        assert units in _extractor(mode).build_user_message(doc, "A Minister")


def test_invalid_identity_mode_rejected():
    with pytest.raises(ValueError):
        Extractor(load_taxonomy(), client=object(), identity_mode="sideways")


# --- prompt provenance -----------------------------------------------------

def test_fingerprint_is_stable_and_short():
    from eps.extract import prompt_fingerprint
    a, b = prompt_fingerprint(), prompt_fingerprint()
    assert a == b and len(a) == 12


def test_fingerprint_tracks_prompt_text_not_the_label(monkeypatch):
    """The whole point: editing the wording changes the fingerprint even if you
    forget to change PROMPT_VERSION."""
    import eps.extract as ex
    before = ex.prompt_fingerprint()
    monkeypatch.setattr(ex, "EXTRACT_SYSTEM", ex.EXTRACT_SYSTEM + "\nExtra rule.")
    assert ex.prompt_fingerprint() != before


def test_editing_the_prompt_invalidates_the_cache():
    """Confirms you do NOT need to bump PROMPT_VERSION for an edit to take
    effect — the prompt text is part of the cache key."""
    from eps.extract import ResponseCache
    base = dict(model="m", user="u", prompt_version="P2", identity_mode="blind")
    assert ResponseCache.key(system="one", **base) != ResponseCache.key(system="two", **base)


def test_identity_mode_does_not_collide_in_cache():
    from eps.extract import ResponseCache
    base = dict(model="m", system="s", user="u", prompt_version="P2")
    assert (ResponseCache.key(identity_mode="blind", **base)
            != ResponseCache.key(identity_mode="full", **base))


# --- speaker resolution ----------------------------------------------------

def test_manifest_speaker_used_when_table_is_empty(docs_dir):
    """You can skip the officeholder table entirely by naming the speaker in
    the manifest."""
    from eps.validate import OfficeholderTable, resolve_speaker
    doc = ingest_row(_row(docs_dir / "skills_speech.txt", speaker_hint="Jane Smith"))
    speaker, source, warning = resolve_speaker(doc, OfficeholderTable([]))
    assert speaker == "Jane Smith"
    assert source == "manifest"
    assert warning == ""


def test_table_wins_when_both_present_and_agree(docs_dir):
    from eps.validate import OfficeholderTable, resolve_speaker
    from datetime import date as D
    doc = ingest_row(_row(docs_dir / "skills_speech.txt", speaker_hint="Jane Smith"))
    table = OfficeholderTable([{
        "institution": "Department for Education", "person": "Jane Smith",
        "role": "SoS", "start_date": D(2026, 1, 1), "end_date": None}])
    speaker, source, warning = resolve_speaker(doc, table)
    assert speaker == "Jane Smith" and source == "officeholder_table" and warning == ""


def test_disagreement_is_flagged(docs_dir):
    """A mismatch usually means a wrong date — surface it rather than pick one
    silently."""
    from eps.validate import OfficeholderTable, resolve_speaker
    from datetime import date as D
    doc = ingest_row(_row(docs_dir / "skills_speech.txt", speaker_hint="Jane Smith"))
    table = OfficeholderTable([{
        "institution": "Department for Education", "person": "John Doe",
        "role": "SoS", "start_date": D(2026, 1, 1), "end_date": None}])
    speaker, source, warning = resolve_speaker(doc, table)
    assert speaker == "John Doe"          # the table is authoritative
    assert "check the dates" in warning   # but you are told


def test_no_speaker_anywhere_is_rejected(docs_dir):
    from eps.validate import OfficeholderTable, resolve_speaker
    doc = ingest_row(_row(docs_dir / "skills_speech.txt", speaker_hint=""))
    speaker, source, warning = resolve_speaker(doc, OfficeholderTable([]))
    assert speaker is None and source == ""


def test_out_of_range_date_falls_back_to_manifest(docs_dir):
    """Document dated outside every table range still works if the manifest
    names the speaker."""
    from eps.validate import OfficeholderTable, resolve_speaker
    from datetime import date as D
    doc = ingest_row(_row(docs_dir / "skills_speech.txt", speaker_hint="Jane Smith"))
    table = OfficeholderTable([{
        "institution": "Department for Education", "person": "John Doe",
        "role": "SoS", "start_date": D(2026, 6, 1), "end_date": None}])
    speaker, source, _ = resolve_speaker(doc, table)
    assert speaker == "Jane Smith" and source == "manifest"


# --- Excel BOM ---------------------------------------------------------

def test_manifest_with_excel_bom_is_read_correctly(docs_dir, tmp_path):
    """Excel on Windows often prepends a byte-order mark when saving CSV. That
    mark must not corrupt the first header cell ('path' silently becoming
    unreadable, reported as a missing column)."""
    from eps.harvest.local import read_manifest

    m = tmp_path / "excel_saved.csv"
    with open(m, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=MANIFEST_COLUMNS)
        w.writeheader()
        w.writerow(_row(docs_dir / "skills_speech.txt"))

    # Confirm the mark is actually present in the raw bytes, so the test is
    # exercising the real scenario rather than a plain utf-8 file.
    assert m.read_bytes().startswith(b"\xef\xbb\xbf")

    rows = read_manifest(m)
    assert rows[0]["path"] == str(docs_dir / "skills_speech.txt")


def test_bom_manifest_ingests_end_to_end(docs_dir, tmp_path):
    m = tmp_path / "excel_saved.csv"
    with open(m, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=MANIFEST_COLUMNS)
        w.writeheader()
        w.writerow(_row(docs_dir / "skills_speech.txt"))
    docs, errors = ingest_manifest(m, None, strict=True)
    assert len(docs) == 1 and not errors


# --- regression: extract must see manifest-only speakers too --------------

def test_extract_calls_the_model_for_manifest_only_speaker(docs_dir, tmp_path):
    """Regression test for a real bug: cmd_extract once checked only the
    officeholder table, so a document whose speaker came solely from the
    manifest's speaker_hint was silently treated as having no eligible
    speaker and skipped — the model was never called, with no error printed.
    `build` used the correct resolve_speaker() and reported the speaker fine,
    so the mismatch was invisible until someone checked whether the model
    cache had actually been written to."""
    from eps.extract import Extractor, ResponseCache
    from eps.providers import FakeProvider
    from eps.validate import OfficeholderTable, resolve_speaker

    doc = ingest_row(_row(docs_dir / "skills_speech.txt", speaker_hint="Jane Smith"))
    empty_table = OfficeholderTable([])  # the exact scenario that broke

    # What cmd_extract must do: resolve via manifest fallback, not table-only.
    speaker, source, warning = resolve_speaker(doc, empty_table)
    assert speaker == "Jane Smith" and source == "manifest"

    provider = FakeProvider(lambda system, user: '{"observations": []}')
    ex = Extractor(load_taxonomy(), provider=provider, cache=ResponseCache(tmp_path / "c"))
    ex.extract(doc, speaker, run_id="t")

    # The real assertion: the model was actually invoked, not silently skipped.
    assert provider.calls > 0
