"""The US adapters, from fixtures. No network.

Granted at the previous review gate. Every case here is a fault that actually
reached the corpus and had to be found by inspecting output, not by reading
code — which is the argument for having the file at all.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eps.harvest_us import (
    SPEAKER_EVIDENCE, SPEAKER_IS_DOCUMENT_TYPES, eligible_on, parse_label_map,
    sidecar_path, speaker_evidence, text_filename, write_document,
)
from eps.sources.base import DocumentRef, looks_like_testimony
from eps.sources.blocks import detect_us_quotes, render
from eps.sources.us import ADAPTERS, EducationAdapter, TreasuryAdapter
from eps.sources.us.treasury import _is_section_landing

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class _NoNetwork:
    """Any adapter reaching the network in these tests is a test bug."""

    def __init__(self, page: str = ""):
        self.page = page

    def get_text(self, url, params=None):
        return self.page

    def get_json(self, url, params=None):
        raise AssertionError("no network in tests")

    def get_bytes(self, url, params=None):
        raise AssertionError("no network in tests")

    def rest(self):
        pass


# --------------------------------------------------------------------------
# Treasury page parsing
# --------------------------------------------------------------------------

def test_treasury_title_comes_from_the_heading_not_the_mega_menu():
    # The fault that titled every Treasury document "About Treasury" and, in
    # doing so, silently disabled every title-based rule downstream of it.
    adapter = TreasuryAdapter(fetcher=_NoNetwork(load("treasury_article.html")))
    ref = DocumentRef(institution_id="us-treasury",
                      url="https://home.treasury.gov/news/press-releases/sb0600/",
                      source_document_type="Secretary Statements & Remarks")
    doc = adapter.fetch_document(ref)
    assert doc.status == "ok"
    assert doc.title.startswith("Secretary Bessent Issues Statement")
    assert "About Treasury" not in doc.title


def test_treasury_title_entities_are_unescaped():
    adapter = TreasuryAdapter(fetcher=_NoNetwork(load("treasury_article.html")))
    doc = adapter.fetch_document(DocumentRef(institution_id="us-treasury", url="u"))
    assert "S&P Global" in doc.title
    assert "&amp;" not in doc.title


def test_treasury_reads_the_date_from_the_page_as_metadata():
    adapter = TreasuryAdapter(fetcher=_NoNetwork(load("treasury_article.html")))
    doc = adapter.fetch_document(
        DocumentRef(institution_id="us-treasury", url="u",
                    date="2026-01-01", date_source="listing"))
    assert doc.date == "2026-08-07"
    assert doc.date_source == "metadata"


def test_treasury_body_excludes_script_payloads_and_navigation():
    adapter = TreasuryAdapter(fetcher=_NoNetwork(load("treasury_article.html")))
    doc = adapter.fetch_document(DocumentRef(institution_id="us-treasury", url="u"))
    text = render(detect_us_quotes(doc.html))
    assert "milestone for critical minerals" in text
    assert "not prose" not in text
    assert "About Treasury" not in text


def test_treasury_quote_is_attributed_by_speech_verb():
    adapter = TreasuryAdapter(fetcher=_NoNetwork(load("treasury_article.html")))
    doc = adapter.fetch_document(DocumentRef(institution_id="us-treasury", url="u"))
    quotes = [b for b in detect_us_quotes(doc.html) if b.kind == "quote"]
    assert len(quotes) == 1
    assert quotes[0].speaker == "Secretary of the Treasury Scott Bessent"
    assert quotes[0].method == "speech_verb"


# --------------------------------------------------------------------------
# Treasury index quirks
# --------------------------------------------------------------------------

@pytest.mark.parametrize("item,is_landing", [
    ({"sectionSlug": "testimonies", "sectionLabel": "Testimonies",
      "title": "Testimonies", "url": "/news/press-releases/testimonies/"}, True),
    ({"sectionSlug": "readouts", "sectionLabel": "Readouts",
      "title": "Readouts", "url": "/news/press-releases/readouts/"}, True),
    ({"sectionSlug": "press-releases", "sectionLabel": "Press Releases",
      "title": "Treasury Sanctions Iranian Officials",
      "url": "/news/press-releases/sb0617/"}, False),
])
def test_section_landing_pages_are_not_documents(item, is_landing):
    assert _is_section_landing(item) is is_landing


# --------------------------------------------------------------------------
# Education listing and page parsing
# --------------------------------------------------------------------------

def test_education_listing_rows_carry_label_and_date():
    adapter = EducationAdapter(fetcher=_NoNetwork())
    rows = adapter._rows(load("ed_listing.html"))
    assert len(rows) == 2, "the offsite link must not become a document"
    assert rows[0].source_document_type == "Press Release"
    assert rows[0].date == "2026-07-30"
    assert rows[0].date_source == "listing"
    assert rows[1].source_document_type == "Speech"


def test_education_article_title_and_date():
    adapter = EducationAdapter(fetcher=_NoNetwork(load("ed_article.html")))
    doc = adapter.fetch_document(DocumentRef(institution_id="us-education", url="u"))
    assert doc.status == "ok"
    assert doc.title.startswith("Secretary McMahon")
    assert doc.date == "2026-07-10"
    assert doc.date_source == "metadata"


def test_education_mixed_straight_and_curly_quote_marks():
    # ed.gov opens with a straight mark and closes with a curly one.
    adapter = EducationAdapter(fetcher=_NoNetwork(load("ed_article.html")))
    doc = adapter.fetch_document(DocumentRef(institution_id="us-education", url="u"))
    quotes = [b for b in detect_us_quotes(doc.html) if b.kind == "quote"]
    assert len(quotes) == 1
    assert quotes[0].speaker == "U.S. Secretary of Education Linda McMahon"


# --------------------------------------------------------------------------
# Document typing
# --------------------------------------------------------------------------

@pytest.mark.parametrize("title,expected", [
    ("Statement from Secretary Bessent Before the United States Senate Finance Committee", True),
    ("Secretary Scott Bessent's Statement Before the Appropriations Subcommittee", True),
    ("Secretary McMahon Testifies on the FY2027 Budget Request", True),
    ("Written Testimony of the Deputy Secretary", True),
    # "Before the ..." is also how Treasury names an audience. These must not
    # be swept up; a loose rule relabelled 13 speeches as testimony.
    ("Remarks by Treasury Secretary Scott Bessent before the Petroleum Club of Houston", False),
    ("Remarks by Secretary Bessent Before the EXIM Annual Conference", False),
    ("Remarks Before the Financial Literacy and Education Commission", False),
    ("Treasury Sanctions Iranian Regime Officials", False),
])
def test_looks_like_testimony(title, expected):
    assert looks_like_testimony(title) is expected


@pytest.mark.parametrize("label,title,expected", [
    ("Press Releases", "Treasury Sanctions Networks", "press_release"),
    ("Readouts", "Readout of the Secretary's Meeting", "press_release"),
    ("Secretary Statements & Remarks",
     "Remarks by Secretary Bessent at the Economic Club", "speech"),
    ("Secretary Statements & Remarks",
     "Secretary Bessent Issues Statement Welcoming S&P", "statement"),
    ("Secretary Statements & Remarks",
     "Statement from Secretary Bessent Before the United States Senate Finance Committee",
     "testimony"),
])
def test_treasury_normalise_type(label, title, expected):
    assert TreasuryAdapter().normalise_type(label, title) == expected


def test_education_speech_section_still_yields_testimony_by_title():
    assert EducationAdapter().normalise_type(
        "Speech", "Secretary McMahon Testifies on the Budget Request") == "testimony"


def test_an_unmapped_label_is_other_and_is_counted():
    adapter = TreasuryAdapter()
    assert adapter.normalise_type("Blog Post", "Some title") == "other"
    assert adapter.unknown_labels == {"Blog Post": 1}


def test_parse_label_map_round_trips_the_config_format():
    assert parse_label_map("Press Releases=press_release;Readouts=press_release") == {
        "Press Releases": "press_release", "Readouts": "press_release"}


# --------------------------------------------------------------------------
# Config and the officeholder join
# --------------------------------------------------------------------------

CONFIG = Path(__file__).resolve().parents[1] / "config" / "us_agencies.csv"
OFFICEHOLDERS = (Path(__file__).resolve().parents[4]
                 / "harvest-code" / "officeholders_2026.csv")


def test_config_has_all_24_agencies_and_no_invented_slugs():
    import csv
    rows = list(csv.DictReader(CONFIG.open(encoding="utf-8-sig")))
    assert len(rows) == 24
    slugs = {r["institution_id"] for r in rows}
    # The four the foundations brief invented. The officeholder file wins.
    assert {"us-usda", "us-dod", "us-doj", "us-dot"} & slugs == set()
    assert {"us-agriculture", "us-defense", "us-justice",
            "us-transportation"} <= slugs


@pytest.mark.skipif(not OFFICEHOLDERS.is_file(), reason="officeholders CSV absent")
def test_every_config_slug_exists_in_the_officeholder_file():
    import csv
    cfg = {r["institution_id"]
           for r in csv.DictReader(CONFIG.open(encoding="utf-8-sig"))}
    oh = {r["institution_id"]
          for r in csv.DictReader(OFFICEHOLDERS.open(encoding="utf-8-sig"))
          if r["country"] == "United States"}
    assert cfg == oh


def test_officeholder_lookup_filters_on_date_not_first_match():
    rows = [
        {"institution_id": "us-labor", "institution": "Department of Labor",
         "officeholder": "Lori Chavez-DeRemer",
         "start_date": "2025-03-11", "end_date": "2026-04-20"},
        {"institution_id": "us-labor", "institution": "Department of Labor",
         "officeholder": "Keith E. Sonderling",
         "start_date": "2026-04-20", "end_date": ""},
    ]
    assert eligible_on(rows, "us-labor", "2026-01-15") == ["Lori Chavez-DeRemer"]
    assert eligible_on(rows, "us-labor", "2026-06-01") == ["Keith E. Sonderling"]
    # end_date inclusive, matching the UK harvest (H-14): both on handover day.
    assert eligible_on(rows, "us-labor", "2026-04-20") == [
        "Lori Chavez-DeRemer", "Keith E. Sonderling"]


def test_a_dissolved_agency_yields_no_officeholder():
    rows = [{"institution_id": "us-usaid", "institution": "USAID",
             "officeholder": "[none - agency dissolved]",
             "start_date": "2025-07-01", "end_date": ""}]
    assert eligible_on(rows, "us-usaid", "2026-06-01") == []


# --------------------------------------------------------------------------
# Speaker evidence
# --------------------------------------------------------------------------

def test_speech_and_testimony_are_speaker_is_document():
    for doc_type in SPEAKER_IS_DOCUMENT_TYPES:
        assert speaker_evidence([], "A title", "body", ["Scott Bessent"],
                                doc_type) == "speaker_is_document"


def test_a_press_release_is_not_speaker_is_document():
    assert speaker_evidence([], "A title", "body", ["Scott Bessent"],
                            "press_release") == "none"


def test_speaker_is_document_needs_an_expected_officeholder():
    assert speaker_evidence([], "A title", "body", [], "speech") == "none"


def test_every_evidence_value_is_declared():
    blocks = detect_us_quotes(load("us_quote_other_speaker.html"))
    for doc_type in ("speech", "press_release", "testimony"):
        assert speaker_evidence(blocks, "t", "b", ["John Smith"],
                                doc_type) in SPEAKER_EVIDENCE


# --------------------------------------------------------------------------
# The sidecar as written by the harvester
# --------------------------------------------------------------------------

class _Ref:
    url = "https://example.gov/doc"
    institution_id = "us-education"


class _Doc:
    ref = _Ref()
    title = "A Title"
    date = "2026-07-10"
    date_source = "metadata"
    source_document_type = "Press Release"


def test_sidecar_path_sits_beside_the_text_file():
    assert sidecar_path("documents/x.txt") == "documents/x.blocks.json"


def test_written_text_file_has_no_header_and_matches_the_sidecar(tmp_path):
    blocks = detect_us_quotes(load("us_quote_other_speaker.html"))
    body = render(blocks)
    rel = text_filename("https://example.gov/a/doc", "2026-07-10")
    write_document(str(tmp_path), rel, _Doc(), blocks, body)

    written = (tmp_path / rel).read_text(encoding="utf-8")
    assert written == body
    assert not written.startswith("TITLE:"), "the .txt must carry no header"
    assert "\n---\n" not in written

    payload = json.loads(
        (tmp_path / sidecar_path(rel)).read_text(encoding="utf-8"))
    assert len(payload["blocks"]) == len(body.split("\n\n"))
    assert payload["url"] == _Ref.url
    assert [b["index"] for b in payload["blocks"]] == list(range(len(blocks)))
    assert payload["blocks"][0]["kind"] == blocks[0].kind


#: The twelve agencies with an adapter, and the twelve without.
#:
#: Replaces the original two-agency assertion, which was correct while Treasury
#: and Education were the only adapters and became wrong when the survey
#: (H-46 to H-52) was worked through. The point of the test is unchanged: the
#: registry is a deliberate list, not whatever happens to import, so adding an
#: adapter without deciding it belongs fails here.
IMPLEMENTED = {
    "us-treasury", "us-education",          # the two reference adapters
    "us-nasa", "us-va",                     # feed tier, WordPress REST
    "us-dhs", "us-gsa", "us-hud", "us-interior", "us-opm", "us-sba",
    "us-state", "us-usaid",                 # listing tier, plain HTTP
    "us-agriculture", "us-hhs", "us-labor", "us-ssa", "us-transportation",
                                            # listing tier, TLS impersonation
    "us-epa", "us-nsf", "us-justice", "us-energy",       # index from the Archive, bodies live
    "us-commerce",                          # registered for desktop_harvest.py
}

#: Why each of the other twelve is absent. Values are the `transport` or `tier`
#: recorded in `config/us_agencies.csv`, so this test fails if the config and
#: the registry ever disagree about who is collectable.
NOT_IMPLEMENTED = {
    # Releases are PDFs. PI decision, 2026-09-08; a documented gap.
    "us-nrc": "listing",
    # Listing is Vue-rendered live AND in the archive: 69 documents, no press
    # releases at all (H-67, H-77).
    "us-defense": "awkward",
}


def test_adapter_registry_is_the_reachable_agencies():
    assert set(ADAPTERS) == IMPLEMENTED


def test_every_agency_is_either_implemented_or_has_a_recorded_reason():
    import csv
    rows = list(csv.DictReader(CONFIG.open(encoding="utf-8-sig")))
    slugs = {r["institution_id"] for r in rows}
    assert IMPLEMENTED | set(NOT_IMPLEMENTED) == slugs
    assert not (IMPLEMENTED & set(NOT_IMPLEMENTED))


def test_config_records_a_module_for_every_implemented_adapter():
    """An adapter that exists but is not named in the config never runs."""
    import csv
    rows = {r["institution_id"]: r
            for r in csv.DictReader(CONFIG.open(encoding="utf-8-sig"))}
    for iid in IMPLEMENTED:
        assert rows[iid]["adapter"], "%s has an adapter but no config entry" % iid
    for iid in NOT_IMPLEMENTED:
        assert not rows[iid]["adapter"], "%s names an adapter it does not have" % iid


def test_unimplemented_agencies_say_why_in_the_config():
    import csv
    rows = {r["institution_id"]: r
            for r in csv.DictReader(CONFIG.open(encoding="utf-8-sig"))}
    for iid, reason in NOT_IMPLEMENTED.items():
        row = rows[iid]
        assert reason in (row["transport"], row["tier"]), (
            "%s: config says tier=%s transport=%s, expected %s"
            % (iid, row["tier"], row["transport"], reason))
        assert row["notes"].strip(), "%s must record why it is not collected" % iid
