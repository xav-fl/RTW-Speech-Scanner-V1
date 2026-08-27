"""Deterministic normalisation and segmentation.

Everything here must be reproducible: the same input bytes must always give the
same units with the same IDs. SEGMENTER_VERSION is part of the document
identity — bump it if you change any rule below, because unit IDs from an older
version will no longer point at the same text.
"""

from __future__ import annotations

import re
import unicodedata

from lxml import html as lxml_html

from .models import Unit, sha256

SEGMENTER_VERSION = "seg-1.0.0"

# Block-level tags whose boundaries we treat as paragraph breaks.
_BLOCK_TAGS = {
    "p", "div", "li", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6",
    "tr", "td", "th", "section", "article", "figcaption", "dd", "dt", "pre",
}
_DROP_TAGS = {"script", "style", "nav", "header", "footer", "aside", "form", "noscript"}

# Abbreviations after which a full stop does not end a sentence. Deliberately
# conservative and explicit rather than model-based, so it never drifts.
_ABBREV = {
    "mr", "mrs", "ms", "dr", "prof", "sen", "rep", "gov", "sec", "hon", "rt",
    "st", "jr", "sr", "no", "vs", "etc", "eg", "ie", "cf", "al", "approx",
    "dept", "univ", "inst", "fig", "vol", "pp", "ch", "art", "para", "sect",
    "u.s", "u.k", "e.g", "i.e", "a.m", "p.m", "mp", "mps", "cbe", "obe",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct",
    "nov", "dec",
}

_SENT_END = re.compile(r"([.!?][\"'\u2019\u201d\)\]]*)(\s+)")
_WS = re.compile(r"[^\S\n]+")
_MULTI_NL = re.compile(r"\n{2,}")
_SINGLE_NL = re.compile(r"(?<!\n)\n(?!\n)")


def normalise_text(text: str) -> str:
    """NFC-normalise, collapse intra-line whitespace, keep paragraph breaks."""
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00a0", " ").replace("\u200b", "")
    text = _WS.sub(" ", text)
    lines = [ln.strip() for ln in text.split("\n")]
    text = "\n".join(lines)
    text = _MULTI_NL.sub("\n\n", text)
    # A single newline inside a block is soft-wrapping in the source markup,
    # not a paragraph break. Collapse it to a space so quotes come out as one
    # continuous line; only blank-line-separated blocks stay separate.
    text = _SINGLE_NL.sub(" ", text)
    text = _WS.sub(" ", text)
    return text.strip()


def html_to_text(raw_html: str) -> str:
    """Extract paragraph-preserving plain text from an HTML fragment or page.

    Paragraph boundaries matter: the field guide requires them preserved, and
    they are the outer level of the unit-ID scheme.
    """
    if not raw_html or not raw_html.strip():
        return ""
    try:
        tree = lxml_html.fromstring(raw_html)
    except Exception:
        return normalise_text(re.sub(r"<[^>]+>", " ", raw_html))

    for el in tree.iter():
        if el.tag in _DROP_TAGS:
            el.drop_tree()

    parts: list[str] = []

    def walk(el):
        if el.tag in _DROP_TAGS:
            return
        is_block = el.tag in _BLOCK_TAGS
        if is_block:
            parts.append("\n\n")
        if el.text:
            parts.append(el.text)
        for child in el:
            walk(child)
            if child.tail:
                parts.append(child.tail)
        if el.tag == "br":
            parts.append("\n")
        if is_block:
            parts.append("\n\n")

    walk(tree)
    return normalise_text("".join(parts))


def _ends_with_abbrev(chunk: str) -> bool:
    m = re.search(r"([A-Za-z\.]+)\.$", chunk.strip())
    if not m:
        return False
    word = m.group(1).lower().rstrip(".")
    if word in _ABBREV:
        return True
    # Single initial, e.g. "J." in "J. D. Vance"
    if len(word) == 1:
        return True
    return False


def split_sentences(paragraph: str) -> list[tuple[int, int]]:
    """Return (start, end) offsets of sentences within `paragraph`."""
    if not paragraph.strip():
        return []
    spans: list[tuple[int, int]] = []
    start = 0
    for m in _SENT_END.finditer(paragraph):
        end = m.end(1)
        candidate = paragraph[start:end]
        if _ends_with_abbrev(candidate):
            continue
        # Don't split on a decimal point or a numbered-list marker.
        if re.search(r"\d\.$", candidate) and m.end(2) < len(paragraph) \
                and paragraph[m.end(2)].isdigit():
            continue
        spans.append((start, end))
        start = m.end(2)
    if start < len(paragraph):
        tail = paragraph[start:].rstrip()
        if tail:
            spans.append((start, start + len(tail)))
    return spans


def segment(text: str, doc_id: str) -> list[Unit]:
    """Split normalised text into sentence units with stable IDs and offsets."""
    units: list[Unit] = []
    cursor = 0
    para_idx = 0
    for para in text.split("\n\n"):
        para_start = text.find(para, cursor)
        if para_start == -1:  # pragma: no cover - defensive
            para_start = cursor
        cursor = para_start + len(para)
        if not para.strip():
            continue
        para_idx += 1
        for sent_idx, (s, e) in enumerate(split_sentences(para), start=1):
            sent = para[s:e].strip()
            if not sent:
                continue
            abs_start = para_start + s + (len(para[s:e]) - len(para[s:e].lstrip()))
            units.append(
                Unit(
                    unit_id=f"{doc_id}.P{para_idx:03d}.S{sent_idx:03d}",
                    para_idx=para_idx,
                    sent_idx=sent_idx,
                    text=sent,
                    char_start=abs_start,
                    char_end=abs_start + len(sent),
                )
            )
    return units


# --- attribution -----------------------------------------------------------

_QUOTE_CHARS = '"\u201c\u201d\u2018\u2019'
_ATTRIB_CUE = re.compile(
    r"\b(said|says|added|told|commented|explained|continued|noted|stated)\b",
    re.I,
)

# Document types where the whole body is the speaker talking.
SPEAKER_ONLY_TYPES = {"speech", "statement", "op_ed", "letter", "testimony"}


def mark_attribution(units: list[Unit], doc_type: str) -> list[Unit]:
    """Flag which units can carry the speaker's own words.

    For a speech the whole body is the speaker. For a press release only the
    quoted passages are; the surrounding departmental prose reads exactly like
    a policy statement but is not attributable to anyone. Getting this wrong is
    the single largest source of false positives, so it is done in code rather
    than left to the model.
    """
    if doc_type in SPEAKER_ONLY_TYPES:
        return units

    out: list[Unit] = []
    for u in units:
        has_quote = any(c in u.text for c in _QUOTE_CHARS)
        # A sentence with an attribution cue and a quotation mark, or a
        # sentence that is wholly inside quotation marks, is attributable.
        attributable = has_quote and (
            bool(_ATTRIB_CUE.search(u.text))
            or u.text.lstrip()[:1] in _QUOTE_CHARS
        )
        out.append(
            Unit(
                unit_id=u.unit_id,
                para_idx=u.para_idx,
                sent_idx=u.sent_idx,
                text=u.text,
                char_start=u.char_start,
                char_end=u.char_end,
                attributable=attributable,
            )
        )
    return out


def make_doc_id(url: str, raw_bytes_hash: str) -> str:
    return "D" + sha256(f"{url}|{raw_bytes_hash}")[:10]
