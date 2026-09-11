"""HTML to text, done carefully. Shared by every source adapter.

`_clean_inline()` and `html_to_blocks()` are copied unchanged from
`harvest-code/harvest-v3/audit_text_fidelity.py`, which is where the fault they
guard against was found and fixed (B-05, B-06 in the decision report). They are
here rather than there so that every adapter written from now on inherits the
fix instead of getting a fresh chance to repeat it.

The rule that matters more than the code:

    Every tag becomes a SPACE, never an empty string.

Dropping a tag without leaving a space welds two words together. The UK harvest
failed this way and the frozen text stopped matching the pages it cited.

Standard library only, deliberately: the standalone harvesters run without the
packaged pipeline's dependencies installed.
"""

from __future__ import annotations

import re
from html import unescape

_BLOCK_OPEN = re.compile(r"<(p|li|h[1-6]|blockquote|div|tr)\b[^>]*>", re.I)
_BLOCK_CLOSE = re.compile(r"</(p|li|h[1-6]|blockquote|div|tr)\s*>", re.I)
_BR = re.compile(r"<br\s*/?>", re.I)
_TAG = re.compile(r"<[^>]+>")
_ABBR = re.compile(r"<abbr\b[^>]*>(.*?)</abbr>", re.I | re.S)

# Not in the original: US adapters read whole pages rather than an API's body
# field, so script and style payloads reach the converter. Removing them is a
# pre-step, not a change to the conversion itself.
_NOISE = re.compile(
    r"<(script|style|noscript|template)\b[^>]*>.*?</\1\s*>", re.I | re.S
)
_COMMENT = re.compile(r"<!--.*?-->", re.S)


def _clean_inline(s: str) -> str:
    """Strip inline tags, unescape entities, normalise whitespace.

    Every tag becomes a SPACE, not an empty string. That single choice is what
    the original extractor got wrong: dropping a tag or a newline without
    leaving a space silently welds two words together.
    """
    s = _ABBR.sub(r"\1", s)          # keep the abbreviation, drop the expansion
    s = _TAG.sub(" ", s)
    s = unescape(s)
    s = s.replace("\u00a0", " ")     # non-breaking space -> ordinary space
    s = re.sub(r"[ \t\r\n]+", " ", s)
    # Stripping a tag leaves a space, which can land before punctuation
    # ("ISPs ."). Pull those back; never merge two words to do it.
    s = re.sub(r" +([,.;:!?%)\]])", r"\1", s)
    s = re.sub(r"([(\[]) +", r"\1", s)
    return s.strip()


def html_to_blocks(html: str) -> list[tuple[str, str]]:
    """Return [(kind, text)] where kind is 'quote' or 'text'.

    Blockquote depth is tracked so ministerial quotations stay distinguishable
    from surrounding departmental prose.
    """
    out: list[tuple[str, str]] = []
    depth = 0
    pos = 0
    buf: list[str] = []

    def flush():
        nonlocal buf
        text = _clean_inline("".join(buf))
        if text:
            out.append(("quote" if depth > 0 else "text", text))
        buf = []

    html = _BR.sub("\n", html)

    for m in re.finditer(r"</?[a-zA-Z][^>]*>", html):
        buf.append(html[pos:m.start()])
        tag = m.group(0)
        pos = m.end()
        name = re.match(r"</?\s*([a-zA-Z0-9]+)", tag)
        name = name.group(1).lower() if name else ""
        if name == "blockquote":
            flush()
            depth += 1 if not tag.startswith("</") else -1
            depth = max(depth, 0)
        elif name in ("p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "div"):
            flush()
        else:
            buf.append(" ")
    buf.append(html[pos:])
    flush()
    return out


def strip_noise(html: str) -> str:
    """Remove script, style and comment payloads before conversion.

    `html_to_blocks()` turns every tag into a space but keeps the text between
    them, so a <script> body would otherwise arrive in the corpus as prose.
    GOV.UK's Content API returned body HTML with none of this in it; agency
    pages are scraped whole, so they do.
    """
    return _NOISE.sub(" ", _COMMENT.sub(" ", html or ""))
