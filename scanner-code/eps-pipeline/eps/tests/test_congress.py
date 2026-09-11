"""Congressional hearing collection: turn segmentation and the witness join.

The fixture is shaped from CHRG-119hhrg63860, the HUD oversight hearing of
2026-01-21, including the two things that actually broke the first version:
a turn marker followed by a capitalised word, and a witness line carrying the
department name after the person's name.
"""

from __future__ import annotations

import pytest

from eps.sources.blocks import (METHODS, hearing_blocks, split_hearing_turns)
from eps.sources.congress import CongressionalHearings, HearingRef, witness_name

TRANSCRIPT = """\
OVERSIGHT OF THE DEPARTMENT OF HOUSING AND URBAN DEVELOPMENT

    STATEMENT OF HON. SCOTT TURNER, SECRETARY, DEPARTMENT OF HOUSING
                        AND URBAN DEVELOPMENT

    Chairman Hill. Good morning. The committee will come to order.
I would like to thank our Secretary, Scott Turner, for being with us.
    Secretary Turner. Well, thank you, Chairman Hill, Ranking Member
Waters, and distinguished members of this committee. Happy to be here.
    Ms. Waters. Mr. Secretary, I want to ask about the budget.
    Secretary Turner. Yes. We are refocusing the Department on its core
mission of serving the American people.
    Mr. Torres. Reclaiming my time.
"""

WITNESS = ("Hon. Scott Turner, Secretary, Department of Housing and "
           "Urban Development")

OFFICEHOLDERS = [
    {"institution_id": "us-hud", "officeholder": "Scott Turner",
     "start_date": "2025-02-05", "end_date": ""},
    {"institution_id": "us-treasury", "officeholder": "Scott Bessent",
     "start_date": "2025-01-28", "end_date": ""},
    # A predecessor whose tenure ended before the hearing.
    {"institution_id": "us-labor", "officeholder": "Lori Chavez-DeRemer",
     "start_date": "2025-03-11", "end_date": "2025-04-20"},
]


# --- turn segmentation -----------------------------------------------------

def test_turns_are_split_on_the_printed_speaker_name():
    turns = split_hearing_turns(TRANSCRIPT)
    speakers = [s for s, _ in turns if s]
    assert speakers == ["Chairman Hill", "Secretary Turner", "Ms. Waters",
                        "Secretary Turner", "Mr. Torres"]


def test_front_matter_is_kept_under_the_empty_speaker():
    turns = split_hearing_turns(TRANSCRIPT)
    assert turns[0][0] == ""
    assert "OVERSIGHT OF THE DEPARTMENT" in turns[0][1]
    assert "STATEMENT OF HON. SCOTT TURNER" in turns[0][1]


def test_a_marker_does_not_swallow_the_first_word_of_the_turn():
    """The bug that made 52 of 112 apparent speakers fragments.

    "Chairman Hill. Good morning" must yield the speaker "Chairman Hill",
    not "Chairman Hill. Good".
    """
    turns = dict(split_hearing_turns(TRANSCRIPT))
    assert "Chairman Hill" in turns
    assert not any(s.endswith("Good") for s, _ in split_hearing_turns(TRANSCRIPT))
    assert turns["Chairman Hill"].startswith("Good morning")


#: A member welcoming the witness, wrapped by GPO exactly as it prints.
#: "Secretary Noem." lands at the start of a line without an indent.
WRAPPED = """\
    Mr. Raskin. Well, thank you kindly, Mr. Chair. Welcome,
Secretary Noem. We are glad to meet you, even though it has
been 13 months since you took office.
    Secretary Noem. Well, thank you, Mr. Chair, and thank you,
Ranking Member Raskin, for your opening statements.
"""


def test_a_wrapped_line_does_not_open_a_turn():
    """The fault that credited a witness with words spoken TO her.

    GPO wraps at about 72 characters. Without the indent rule the member's
    welcome is split at "Secretary Noem." and everything after it -- "We are
    glad to meet you..." -- is attributed to the Secretary.
    """
    turns = split_hearing_turns(WRAPPED)
    speakers = [s for s, _ in turns if s]
    assert speakers == ["Mr. Raskin", "Secretary Noem"]
    raskin = [t for s, t in turns if s == "Mr. Raskin"][0]
    assert "We are glad to meet you" in raskin, \
        "the welcome belongs to the member who said it"
    noem = [t for s, t in turns if s == "Secretary Noem"][0]
    assert noem.startswith("Well, thank you")
    assert "glad to meet you" not in noem


def test_the_witness_is_not_credited_with_words_spoken_to_her():
    blocks = hearing_blocks(WRAPPED, "Kristi Noem")
    quotes = [b for b in blocks if b.kind == "quote"]
    assert len(quotes) == 1
    assert "glad to meet you" not in quotes[0].text


def test_a_name_inside_running_prose_does_not_open_a_turn():
    """Only a line-start marker counts.

    The chairman's turn contains "our Secretary, Scott Turner, for being with
    us" mid-sentence. If that opened a turn the chairman's words would be
    split and half of them attributed to the witness.
    """
    turns = split_hearing_turns(TRANSCRIPT)
    hill = [t for s, t in turns if s == "Chairman Hill"][0]
    assert "Scott Turner" in hill


# --- attribution -----------------------------------------------------------

def test_only_the_officeholders_turns_are_attributable():
    blocks = hearing_blocks(TRANSCRIPT, "Scott Turner")
    quotes = [b for b in blocks if b.kind == "quote"]
    assert len(quotes) == 2
    assert all(b.method == "hearing_turn" for b in quotes)
    assert all(b.speaker == "Secretary Turner" for b in quotes)
    assert "Happy to be here" in quotes[0].text


def test_everyone_elses_words_carry_no_speaker():
    blocks = hearing_blocks(TRANSCRIPT, "Scott Turner")
    others = [b for b in blocks if b.kind == "text"]
    assert others, "the committee's turns must still be in the document"
    assert all(b.speaker is None for b in others)
    assert all(b.method == "none" for b in others)


def test_the_whole_transcript_survives_segmentation():
    """Nothing is dropped: a hearing must stay verifiable against the print."""
    blocks = hearing_blocks(TRANSCRIPT, "Scott Turner")
    joined = " ".join(b.text for b in blocks)
    for phrase in ("will come to order", "Happy to be here",
                   "ask about the budget", "Reclaiming my time"):
        assert phrase in joined


def test_hearing_turn_is_a_known_method():
    assert "hearing_turn" in METHODS


# --- the witness join ------------------------------------------------------

def test_witness_name_is_the_first_comma_clause():
    assert witness_name(WITNESS) == "Hon. Scott Turner"


def test_the_join_matches_the_witness_to_one_officeholder():
    c = CongressionalHearings()
    ref = HearingRef(package_id="CHRG-119hhrg63860", date="2026-01-21",
                     witnesses=[WITNESS])
    matched = c.match_officeholders(ref, OFFICEHOLDERS)
    assert matched == [("us-hud", "Scott Turner", WITNESS)]


def test_the_department_name_in_the_witness_line_does_not_defeat_the_match():
    """Regression: the whole line reads "Housing"/"Urban" as forenames."""
    from eps.sources.blocks import names_match
    assert not names_match(WITNESS, "Scott Turner")
    assert names_match(witness_name(WITNESS), "Scott Turner")


def test_tenure_is_checked_against_the_hearing_date():
    c = CongressionalHearings()
    ref = HearingRef(package_id="X", date="2026-01-21",
                     witnesses=["Hon. Lori Chavez-DeRemer, Secretary of Labor"])
    assert c.match_officeholders(ref, OFFICEHOLDERS) == []


def test_an_unmatched_witness_is_recorded_not_discarded():
    c = CongressionalHearings()
    ref = HearingRef(package_id="X", date="2026-01-21",
                     witnesses=["Ms. Margarita Devlin, Principal Deputy Under "
                                "Secretary for Benefits"])
    assert c.match_officeholders(ref, OFFICEHOLDERS) == []
    assert c.unmatched_witnesses, "the review gate needs to see who was skipped"


# --- coverage honesty ------------------------------------------------------

def test_lag_warning_flags_the_thin_tail_of_a_recent_window():
    """July is not a quiet month, it is an unfinished one."""
    by_month = {"2026-01": 15, "2026-02": 17, "2026-03": 15,
                "2026-04": 14, "2026-05": 15, "2026-06": 19, "2026-07": 5}
    assert CongressionalHearings.lag_warning(by_month) == ["2026-07"]


def test_lag_warning_is_quiet_on_an_even_window():
    by_month = {"2026-01": 15, "2026-02": 17, "2026-03": 15}
    assert CongressionalHearings.lag_warning(by_month) == []
