"""The block model, and a US quote detector to fill it.

The UK converter returns `[(kind, text)]`. That was enough because GOV.UK marks
a ministerial quotation with `<blockquote>` and an introducing line naming the
speaker, so attribution could be decided later, structurally, from the rendered
text.

US agencies do the opposite. Quotations are inline, inside an ordinary
paragraph, marked with quotation marks, and attributed by a speech verb in the
same block:

    <p>"We're cutting red tape to get homes built," said Secretary Smith.
    "This is about supply."</p>

Run the blockquote detector over that and you get zero quote blocks. So the
speaker moves onto the block itself, decided at collection time by whichever
rule the page actually supports, and `method` records which rule fired.

Rendering is unchanged: `> ` in front of quote blocks, exactly as the UK
rewriter emits, so both corpora look identical to whatever reads them next.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .text import html_to_blocks, strip_noise

QUOTE_MARKER = "> "

#: How a block's speaker was decided.
#:   blockquote    -- the block was inside <blockquote> (the GOV.UK shape)
#:   speech_verb   -- a speech verb next to the quoted span named the speaker
#:   structural    -- inherited from an adjacent block: a frame line ending in
#:                    ":", or the attributed quote this one continues
#:   hearing_turn  -- a congressional transcript turn, where the GPO prints the
#:                    speaker's name at the head of every turn. This is the
#:                    STRONGEST evidence of the five: the attribution is made by
#:                    the official reporter, not inferred from punctuation or
#:                    proximity, and it names one speaker for a bounded span of
#:                    text rather than for a quotation inside someone's prose.
#:   none          -- no speaker could be decided
METHODS = ("blockquote", "speech_verb", "structural", "hearing_turn", "none")

KINDS = ("quote", "text")


@dataclass
class Block:
    kind: str               # "quote" | "text"
    text: str
    speaker: Optional[str]  # attributed speaker, None if unknown
    method: str             # how attribution was decided


# --------------------------------------------------------------------------
# Quotation marks
# --------------------------------------------------------------------------
# Straight and curly are mixed freely in practice. The Department of Education
# press release used to build this detector opens a quotation with a straight
# mark and closes it with a curly one in the same sentence, so the detector
# cannot assume a matched pair of the same character.

_OPEN_Q = "\"“‟«"
_CLOSE_Q = "\"”‟»"

# Apostrophes are never treated as quotation marks. That was B-08 in the UK
# pipeline and it is not worth repeating.

#: A quoted span shorter than this many words is left inline rather than
#: promoted to a quote block. Scare quotes around a term are not utterances,
#: and promoting them would put a speakerless `> ` block into every second
#: document. This is a detection floor, not an eligibility filter: the words
#: stay in the text either way.
MIN_QUOTE_WORDS = 4


# --------------------------------------------------------------------------
# Names and speech verbs
# --------------------------------------------------------------------------

_VERB = (
    r"(?:said|says|saying|added|adds|noted|notes|stated|states|told|tells"
    r"|continued|continues|explained|explains|remarked|remarks|wrote|writes"
    r"|argued|argues|declared|declares|emphasized|emphasised|testified"
    r"|concluded|observed|warned|warns|urged|urges|announced|announces"
    r"|commented|comments|responded|replied|recalled|stressed|insisted)"
)

# A capitalised token, allowing internal punctuation: "U.S.", "O'Brien",
# "Chavez-DeRemer", "Jr.".
_NTOK = r"[A-Z][A-Za-z’'.\-]*"
# Lowercase connectors that legitimately sit inside an office title, as in
# "Secretary of the Treasury Scott Bessent".
_CONN = r"(?:of|the|for|de|van|von|da|del|la|und)"
_NAME = _NTOK + r"(?:\s+(?:" + _CONN + r"\s+)*" + _NTOK + r")*"

# Captures that are grammatically capitalised but are not people.
_NOT_A_NAME = {
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
    "sunday", "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
    "today", "yesterday", "tomorrow", "this", "that", "these", "those", "it",
    "he", "she", "they", "we", "i", "a", "an", "the", "in", "on", "at", "but",
    "and", "no", "not", "if", "when", "while", "however", "meanwhile",
}

_AFTER = re.compile(
    r"^[\s,.;:—–-]*(?:" + _VERB + r"\s+(?P<a>" + _NAME + r")"
    r"|(?P<b>" + _NAME + r")\s+" + _VERB + r")\b",
    re.UNICODE,
)
_BEFORE = re.compile(
    r"(?:(?P<a>" + _NAME + r")\s+" + _VERB + r"|" + _VERB + r"\s+(?P<b>" + _NAME + r"))"
    r"\s*[,:—–-]*\s*$",
    re.UNICODE,
)

# A GOV.UK-style introducing line -- "Education Secretary Bridget Phillipson
# said:" -- used for any US page that does carry a real blockquote.
_FRAME_TAIL = re.compile(r"\b" + _VERB + r"\s*:\s*$", re.UNICODE)
_NAME_ANY = re.compile(_NAME, re.UNICODE)


def _tidy_name(raw: str) -> str:
    """Trim the punctuation a greedy capture drags in."""
    return raw.strip().strip(",.;:—–- ").strip()


def _is_person(name: str) -> bool:
    if not name:
        return False
    tokens = [t.strip(".").lower() for t in name.split()]
    return any(t and t not in _NOT_A_NAME for t in tokens)


def frame_speaker(text: str) -> Optional[str]:
    """The speaker named by an introducing line ending in a speech verb and ':'.

    The FIRST name phrase in the line, not the one nearest the verb. "Paul
    Whiteman, general secretary of the NAHT, said:" names Paul Whiteman; the
    phrase adjacent to the verb is his employer.
    """
    line = (text or "").rstrip()
    m = _FRAME_TAIL.search(line)
    if not m:
        return None
    for cand in _NAME_ANY.finditer(line[:m.start()]):
        name = _tidy_name(cand.group(0))
        if _is_person(name) and name_tokens(name):
            return name
    return None


def _speaker_from(pattern, fragment: str) -> Optional[str]:
    m = pattern.search(fragment or "")
    if not m:
        return None
    name = _tidy_name(m.group("a") or m.group("b") or "")
    return name if _is_person(name) else None


# --------------------------------------------------------------------------
# Name comparison
# --------------------------------------------------------------------------
# The UK harvester's rule, plus the office titles US pages put in front of a
# name. "said Secretary Smith" and the officeholder record "John Smith" have to
# reduce to the same surname with no forename conflict; stripping the title
# first is what makes that work.

_TITLE_WORDS = {
    "secretary", "deputy", "under", "assistant", "acting", "administrator",
    "commissioner", "director", "chair", "chairman", "chairwoman",
    "chairperson", "president", "vice", "ambassador", "general", "attorney",
    "surgeon", "senator", "representative", "governor", "mayor", "judge",
    "justice", "counsel", "spokesperson", "spokesman", "spokeswoman",
    "of", "the", "for", "us", "u.s", "united", "states", "department",
    "office", "agency", "bureau", "mr", "mrs", "ms", "miss", "dr", "prof",
    "professor", "hon", "honorable", "honourable",
}

_POST_NOMINALS = {"jr", "sr", "ii", "iii", "iv", "phd", "md", "esq"}

#: The subset of _TITLE_WORDS that is an actual office, used to license a
#: surname-only match. Connectors and honorifics are excluded on purpose.
_OFFICE_TITLES = (
    "secretary", "administrator", "commissioner", "director", "chair",
    "chairman", "chairwoman", "chairperson", "president", "ambassador",
    "attorney general", "surgeon general", "counsel",
)


def name_tokens(name: str) -> list[str]:
    """Reduce a name to comparable lowercase tokens, office titles removed."""
    if not name:
        return []
    name = re.sub(r"\(.*?\)", " ", name)
    name = re.sub(r"[^\w\s'’-]", " ", name)
    # "Secretary McMahon's Remarks" must reduce to the same token as
    # "McMahon". A trailing possessive is punctuation, not part of the name.
    name = re.sub(r"['’]s\b", "", name)
    tokens = [t.lower().strip("'’-") for t in name.split()]
    tokens = [t for t in tokens if t and t not in _POST_NOMINALS]
    # A capture made only of title words is not a name. Returning [] there
    # means it matches nobody, rather than matching everybody.
    return [t for t in tokens if t not in _TITLE_WORDS]


def names_match(a: str, b: str) -> bool:
    """True if two names plausibly refer to the same person.

    Surname must match, plus either a shared forename or one name carrying no
    forename at all, which is what lets "Secretary Smith" match "John Smith".
    """
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return False
    if ta[-1] != tb[-1]:
        return False
    fa, fb = set(ta[:-1]), set(tb[:-1])
    if not fa or not fb:
        return True
    return bool(fa & fb)


def name_appears(name: str, haystack: str) -> bool:
    """Is this person named in this text?

    Two ways to qualify:

      1. Every distinctive token of the name appears. This is the UK rule
         (I-10). Surname alone was B-01 -- matching "MP" attributed everything
         to everyone -- so the all-tokens requirement is the default.

      2. The surname appears directly after an office title: "Secretary
         McMahon", "Administrator Zeldin". US agencies write their principals
         this way constantly and almost never give the forename, so rule 1
         alone reports "no trace of the officeholder" for a document titled
         "Secretary McMahon's Remarks to 1,000 High School Students". Requiring
         the office word in front is what keeps this from becoming B-01 again:
         a bare surname never matches.
    """
    tokens = [t for t in name_tokens(name) if len(t) > 1]
    if not tokens:
        return False
    low = (haystack or "").lower()
    if all(t in low for t in tokens):
        return True
    surname = tokens[-1]
    return any(re.search(r"\b" + title + r"\s+" + re.escape(surname) + r"\b", low)
               for title in _OFFICE_TITLES)


# --------------------------------------------------------------------------
# Splitting a paragraph into quoted and unquoted spans
# --------------------------------------------------------------------------

def _split_marks(text: str) -> list[tuple[bool, str, str, str]]:
    """[(is_quoted, span, open_mark, close_mark)] in source order.

    The marks are carried so a span that is not promoted to a quote block can be
    folded back into its neighbour with the characters the agency actually
    published, rather than with a normalised pair this code chose.
    """
    out: list[tuple[bool, str, str, str]] = []
    buf: list[str] = []
    opener = ""
    in_q = False
    for ch in text or "":
        if not in_q and ch in _OPEN_Q:
            if buf:
                out.append((False, "".join(buf), "", ""))
            buf = []
            in_q = True
            opener = ch
            continue
        if in_q and ch in _CLOSE_Q:
            out.append((True, "".join(buf), opener, ch))
            buf = []
            in_q = False
            opener = ""
            continue
        buf.append(ch)
    if buf:
        out.append((in_q, "".join(buf), opener if in_q else "", ""))
    return [t for t in out if t[1].strip()]


def split_quoted(text: str) -> list[tuple[bool, str]]:
    """Split one paragraph into [(is_quoted, span)] in source order.

    An opening mark with no closing mark before the end of the paragraph runs
    to the end of the paragraph. US press releases open every paragraph of a
    multi-paragraph quotation and close only the last, so an unclosed span is
    the convention rather than an error.
    """
    return [(q, s) for q, s, _o, _c in _split_marks(text)]


def _long_enough(span: str) -> bool:
    return len(span.split()) >= MIN_QUOTE_WORDS


# --------------------------------------------------------------------------
# The two detectors
# --------------------------------------------------------------------------

def detect_blockquotes(html: str, speaker: Optional[str] = None) -> list[Block]:
    """The GOV.UK rule: blockquote is the quotation, a frame line names them.

    `speaker` is whatever the source's own metadata asserted, used when no
    frame line precedes the block. Kept here so a US agency that does use
    blockquotes runs through the same code path as GOV.UK, not a special case.
    """
    out: list[Block] = []
    frame: Optional[str] = None
    for kind, text in html_to_blocks(strip_noise(html)):
        if kind == "quote":
            if frame:
                out.append(Block("quote", text, frame, "structural"))
            else:
                out.append(Block("quote", text, speaker, "blockquote"))
            continue
        frame = frame_speaker(text)
        out.append(Block("text", text, None, "none"))
    return out


def detect_us_quotes(html: str, speaker: Optional[str] = None) -> list[Block]:
    """Find quoted spans, find the attributing speech verb, return Blocks.

    Handles, in this order of precedence:

      * attribution after the quote   -- "...," said Secretary Smith
      * attribution splitting a quote -- "...," Smith said, "..."
      * attribution before the quote  -- Secretary Smith said, "..."
      * a consecutive quoted sentence -- inherits the speaker beside it
      * a quote attributed to someone else -- comes back with THAT name

    The last case is the one that protects data quality: a press release
    quoting a union leader must not inherit the Secretary as speaker, so an
    explicit attribution always beats an inherited one.
    """
    out: list[Block] = []
    frame: Optional[str] = None
    for kind, para in html_to_blocks(strip_noise(html)):
        if kind == "quote":
            # Real markup beats punctuation. Keep the GOV.UK reading, including
            # the frame line, for any US agency that does use <blockquote>.
            if frame:
                out.append(Block("quote", para, frame, "structural"))
            else:
                out.append(Block("quote", para, speaker,
                                 "blockquote" if speaker is None else "structural"))
            continue
        frame = frame_speaker(para)
        out.extend(_paragraph_blocks(para))
    return carry_speakers_across_paragraphs(out)


def _paragraph_blocks(para: str) -> list[Block]:
    spans = _split_marks(para)
    if not any(t[0] for t in spans):
        return [Block("text", para, None, "none")] if para.strip() else []

    # Promote only quoted spans long enough to be an utterance; fold the rest
    # back into their neighbours, with the agency's own quotation marks, so
    # that no words are lost and no punctuation is invented.
    merged: list[tuple[bool, str]] = []
    for is_q, span, open_mark, close_mark in spans:
        keep = is_q and _long_enough(span)
        text = span if keep else (open_mark + span + close_mark)
        if merged and not merged[-1][0] and not keep:
            merged[-1] = (False, merged[-1][1] + text)
        else:
            merged.append((keep, text))
    if not any(q for q, _ in merged):
        return [Block("text", para, None, "none")]

    n = len(merged)
    speakers: list[Optional[str]] = [None] * n
    methods: list[str] = ["none"] * n

    # Pass 1 -- explicit attribution from the text immediately around a quote.
    for i, (is_q, _span) in enumerate(merged):
        if not is_q:
            continue
        after = merged[i + 1][1] if i + 1 < n and not merged[i + 1][0] else ""
        before = merged[i - 1][1] if i > 0 and not merged[i - 1][0] else ""
        who = _speaker_from(_AFTER, after) or _speaker_from(_BEFORE, before)
        if who:
            speakers[i] = who
            methods[i] = "speech_verb"

    # Pass 2 -- an interstitial fragment attributes the quote that FOLLOWS it
    # as well as the one before it: "...," Smith said, "...".
    for i, (is_q, span) in enumerate(merged):
        if is_q or not span.strip():
            continue
        who = _speaker_from(_AFTER, span)
        if not who:
            continue
        for j in (i - 1, i + 1):
            if 0 <= j < n and merged[j][0] and speakers[j] is None:
                speakers[j] = who
                methods[j] = "speech_verb"

    # Pass 3 -- a consecutive quoted span with no attribution of its own takes
    # the nearest attributed speaker in the same paragraph, looking backwards
    # then forwards. Explicit beats inherited, so this never overwrites the
    # verdicts above.
    last: Optional[str] = None
    for i, (is_q, _span) in enumerate(merged):
        if not is_q:
            continue
        if methods[i] == "speech_verb":
            last = speakers[i]
        elif speakers[i] is None and last is not None:
            speakers[i] = last
            methods[i] = "structural"
    last = None
    for i in range(n - 1, -1, -1):
        if not merged[i][0]:
            continue
        if methods[i] == "speech_verb":
            last = speakers[i]
        elif speakers[i] is None and last is not None:
            speakers[i] = last
            methods[i] = "structural"

    blocks: list[Block] = []
    for i, (is_q, span) in enumerate(merged):
        text = span.strip()
        if not text:
            continue
        blocks.append(Block(
            "quote" if is_q else "text",
            text,
            speakers[i] if is_q else None,
            methods[i] if is_q else "none",
        ))
    return blocks


def carry_speakers_across_paragraphs(blocks: list[Block]) -> list[Block]:
    """A quote block whose paragraph named nobody inherits the paragraph above.

    Multi-paragraph quotations attribute once, in the first paragraph. Any
    non-quote block that carries no attribution of its own clears the carry, so
    a later quotation under a different introduction is not captured by it.
    """
    carry: Optional[str] = None
    for b in blocks:
        if b.kind == "quote":
            if b.speaker is None and carry is not None:
                b.speaker = carry
                b.method = "structural"
            elif b.speaker is not None:
                carry = b.speaker
        elif (_speaker_from(_AFTER, b.text) is None
              and _speaker_from(_BEFORE, b.text) is None):
            carry = None
    return blocks


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def render(blocks: list[Block]) -> str:
    """Render to text with the same `> ` prefix the UK rewriter uses."""
    lines = []
    for b in blocks:
        lines.append((QUOTE_MARKER + b.text) if b.kind == "quote" else b.text)
    return "\n\n".join(lines)


def quote_speakers(blocks: list[Block]) -> list[str]:
    """Distinct speakers carried by quote blocks, in first-seen order."""
    seen: list[str] = []
    for b in blocks:
        if b.kind == "quote" and b.speaker and b.speaker not in seen:
            seen.append(b.speaker)
    return seen


# --------------------------------------------------------------------------
# Congressional hearing transcripts
# --------------------------------------------------------------------------
# A hearing is not a press release. It is a multi-speaker transcript in which
# the GPO prints the speaker's name at the head of every turn:
#
#     Secretary Turner. Thank you, Mr. Chairman. HUD is refocusing ...
#     Chairman Hill. Thank you, Mr. Secretary. My first question ...
#
# The 2026-01-21 HUD oversight hearing runs to 884 such turns across 46
# speakers, 389 of them the Secretary's. That is a larger body of one
# officeholder's own words than any press release in the corpus, and it is
# attributed by the official reporter rather than by anything this code infers,
# which is why `hearing_turn` sits at the top of METHODS.
#
# The marker is matched at the start of a line only. Inside running prose,
# "Secretary Turner." is an ordinary sentence ending and must not open a turn.

#: Honorifics and offices the GPO uses to open a turn.
_TURN_STYLE = (
    r"(?:Mr|Mrs|Ms|Miss|Dr|Hon|Chairman|Chairwoman|Chair|Vice Chairman|"
    r"Ranking Member|Secretary|Under Secretary|Deputy Secretary|Senator|"
    r"Representative|Administrator|Commissioner|Director|General|Admiral|"
    r"Governor|Judge|Justice|Ambassador|The Chairman|The Chairwoman)"
)

#: Three constraints, each put there by a fault found in a real transcript.
#:
#: 1. **The name token forbids a full stop.** Allowing one lets the pattern run
#:    past the end of the marker and into the speech: "Chairman Hill. Good
#:    morning" was captured as the speaker "Chairman Hill. Good", and 52 of 112
#:    apparent speakers in one transcript were fragments of that kind.
#:
#: 2. **The marker must be INDENTED.** GPO wraps transcript lines at about 72
#:    characters, so a name that happens to fall at the start of a wrapped line
#:    looks exactly like a turn. In CHRG-119hhrg63054 a member says "Welcome,
#:    / Secretary Noem. We are glad to meet you...", and with no indent rule
#:    the committee's welcome was split off and attributed to the Secretary --
#:    the witness credited with words spoken *to* her. Real turns carry a
#:    four-space indent; wrapped continuation lines start at column zero.
#:
#: 3. **Words inside the name are separated by spaces, never newlines.** `\s`
#:    spans line breaks, which let "Secretary." at the end of one line join
#:    "Chair Jordan." at the start of the next into a single seven-word
#:    speaker.
_TURN = re.compile(
    r"(?m)^[ \t]{2,8}(" + _TURN_STYLE + r"\.?"
    r"(?:[ \t]+[A-Z][A-Za-z'\-]{1,24}){1,3})\.\s",
)

#: A prepared statement header: "STATEMENT OF HON. SCOTT TURNER, SECRETARY, ..."
PREPARED_STATEMENT = re.compile(
    r"(?m)^\s*(?:PREPARED\s+)?STATEMENT OF\s+(?:HON\.?\s+)?([^,\n]{3,60})", re.I)


def split_hearing_turns(text: str) -> list[tuple[str, str]]:
    """Split a hearing transcript into `[(speaker, text)]` turns.

    Text before the first marker is returned under the empty speaker, so front
    matter -- the committee roster, the hearing title, the witness list -- is
    kept rather than silently dropped. Nothing is discarded; a caller that
    wants only one speaker filters afterwards.
    """
    if not text:
        return []
    marks = list(_TURN.finditer(text))
    if not marks:
        return [("", text.strip())] if text.strip() else []
    out: list[tuple[str, str]] = []
    head = text[:marks[0].start()].strip()
    if head:
        out.append(("", head))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[m.end():end].strip()
        if body:
            out.append((re.sub(r"\s+", " ", m.group(1)).strip().rstrip("."), body))
    return out


def hearing_blocks(text: str, speaker: str) -> list[Block]:
    """Blocks for one hearing, with `speaker`'s turns marked attributable.

    Every turn becomes a block so the transcript stays whole and verifiable
    against the published document. Only the turns whose printed name matches
    `speaker` are `quote` blocks carrying a speaker; everyone else's words are
    `text`, which is what keeps a committee member's question out of the
    officeholder's mouth.

    `names_match` does the comparison, so "Secretary Turner" matches
    "Scott Turner" on the surname with no forename conflict -- the same rule
    used everywhere else (H-11, I-10, I-13).
    """
    out: list[Block] = []
    for who, body in split_hearing_turns(text):
        mine = bool(who) and bool(speaker) and names_match(who, speaker)
        out.append(Block(
            kind="quote" if mine else "text",
            text=body,
            speaker=who if mine else None,
            method="hearing_turn" if mine else "none",
        ))
    return out
