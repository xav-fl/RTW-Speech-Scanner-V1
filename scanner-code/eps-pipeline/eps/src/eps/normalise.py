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

# Double quotes only. U+2018/U+2019 are excluded deliberately: in British
# prose the right single quote IS the apostrophe, so counting it as a quotation
# mark makes every possessive look like quoted speech. validate.py already
# excludes them for the same reason.
_QUOTE_CHARS = '"\u201c\u201d'

# Our own blockquote marker, inserted when the source HTML is converted to
# text. It is not part of the document's words.
QUOTE_MARKER = "> "

# Document types where the whole body is the speaker talking.
SPEAKER_ONLY_TYPES = {"speech", "statement", "op_ed", "letter", "testimony"}


# Titles and honorifics to ignore when matching a name against a frame.
_NAME_NOISE = {
    "the", "rt", "hon", "mp", "dr", "mr", "mrs", "ms", "miss", "sir", "dame",
    "lord", "lady", "baroness", "baron", "prof", "professor", "of", "for",
}


def _name_tokens(name: str) -> list[str]:
    toks = [t for t in re.split(r"[^A-Za-z\u00c0-\u024f]+", (name or "").lower()) if t]
    return [t for t in toks if t not in _NAME_NOISE and len(t) > 1]


def frame_names_speaker(frame_text: str, speaker: str) -> bool:
    """True when every distinctive token of `speaker` appears in `frame_text`.

    Surname alone is too loose - a document may quote a different person of the
    same surname - so all tokens must appear. Titles around the name are
    ignored, so "Education Secretary Bridget Phillipson said:" matches
    "Bridget Phillipson" while "Paul Whiteman ... said:" does not.
    """
    toks = _name_tokens(speaker)
    if len(toks) < 2:
        return False
    hay = (frame_text or "").lower()
    return all(t in hay for t in toks)


def mark_attribution(
    units: list[Unit],
    doc_type: str,
    speaker: str | None = None,
) -> list[Unit]:
    """Flag which units can carry the speaker's own words.

    For a speech the whole body is the speaker. For a press release only the
    blockquoted passages are, and only those introduced by a frame naming the
    eligible speaker. Getting this wrong is the single largest source of false
    positives, so it is done in code rather than left to the model.
    """
    if doc_type in SPEAKER_ONLY_TYPES:
        return units

    # Group unit indices by paragraph, preserving order.
    paras: dict[int, list[int]] = {}
    for i, u in enumerate(units):
        paras.setdefault(u.para_idx, []).append(i)
    order = sorted(paras)

    is_quote = {
        p: units[paras[p][0]].text.lstrip().startswith(QUOTE_MARKER.strip())
        and units[paras[p][0]].text.startswith(QUOTE_MARKER)
        for p in order
    }

    attributable_para: dict[int, bool] = {}
    last_frame: str | None = None
    prev_quote_ok = False
    for p in order:
        if is_quote[p]:
            # Consecutive quote paragraphs belong to the same frame.
            attributable_para[p] = prev_quote_ok if last_frame is None else (
                bool(speaker) and frame_names_speaker(last_frame, speaker)
            )
            prev_quote_ok = attributable_para[p]
        else:
            attributable_para[p] = False
            text = " ".join(units[i].text for i in paras[p]).strip()
            last_frame = text if text.endswith(":") else None
            prev_quote_ok = False

    out: list[Unit] = []
    for p in order:
        for n, i in enumerate(paras[p]):
            u = units[i]
            text, start = u.text, u.char_start
            # Only the first sentence of a block carries the marker.
            if is_quote[p] and n == 0 and text.startswith(QUOTE_MARKER):
                shift = len(QUOTE_MARKER)
                text = text[shift:]
                start = start + shift
            out.append(
                Unit(
                    unit_id=u.unit_id,
                    para_idx=u.para_idx,
                    sent_idx=u.sent_idx,
                    text=text,
                    char_start=start,
                    char_end=u.char_end,
                    attributable=attributable_para[p],
                )
            )
    return out


def make_doc_id(url: str, raw_bytes_hash: str) -> str:
    return "D" + sha256(f"{url}|{raw_bytes_hash}")[:10]
