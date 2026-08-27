"""
patch_attribution.py

Replaces the punctuation-based attribution rule with a structural one.

The problem
-----------
GOV.UK press releases contain NO quotation marks. A quotation is a
<blockquote>, introduced by a line naming the speaker:

    Education Secretary Bridget Phillipson said:
    > I believe - and this government believes - that background...
    > The SEND system designed 10 years ago...
    Wider reforms to create a sustainable... system include:
    Paul Whiteman, general secretary of the NAHT, said:
    > We welcome the publication of the government's white paper...

The old rule required a quote character, and counted U+2018/U+2019 as quote
characters. In British prose U+2019 IS the apostrophe, so every possessive
("Children's", "leaders'", "Government's") satisfied the test. Combined with a
cue word from the "said|added|told" list, that marked the third-party
ATTRIBUTION FRAMES as the speaker's own words - and never marked the actual
quotation, which has no such marks.

In the DfE pilot this produced zero observations from six press releases, and
the sentences it did mark belonged to a union leader, the Children's
Commissioner, and a campaign group. Had the model been less conservative,
their statements would have entered the dataset under the Secretary of State's
name, verbatim-exact and undetectable downstream.

The fix
-------
Attribution is now decided by document structure plus the speaker's name:

  * a paragraph beginning "> " is a quotation block;
  * it is attributable ONLY if the nearest preceding non-quote paragraph is a
    frame (ends with ":") that names the eligible speaker;
  * consecutive quote paragraphs inherit the frame above them;
  * with no speaker supplied, nothing is attributable - it fails closed.

The "> " marker is our own insertion, not the department's words, so it is
stripped from the unit text AND char_start is advanced past it. Because
reconstruct_quote() slices doc.text[char_start:char_end], the marker falls
outside the slice by construction and can never enter a quotation.

Requires documents produced by audit_text_fidelity.py --rewrite.

Run from the eps folder (the one with pyproject.toml):

    python scripts\\patch_attribution.py
"""

import re
import shutil
import sys
from pathlib import Path

NORMALISE = Path("src/eps/normalise.py")
LOCAL = Path("src/eps/ingest/local.py")

NEW_FUNC = '''# Double quotes only. U+2018/U+2019 are excluded deliberately: in British
# prose the right single quote IS the apostrophe, so counting it as a quotation
# mark makes every possessive look like quoted speech. validate.py already
# excludes them for the same reason.
_QUOTE_CHARS = '"\\u201c\\u201d'

# Our own blockquote marker, inserted when the source HTML is converted to
# text. It is not part of the document's words.
QUOTE_MARKER = "> "

# Titles and honorifics to ignore when matching a name against a frame.
_NAME_NOISE = {
    "the", "rt", "hon", "mp", "dr", "mr", "mrs", "ms", "miss", "sir", "dame",
    "lord", "lady", "baroness", "baron", "prof", "professor", "of", "for",
}


def _name_tokens(name: str) -> list[str]:
    toks = [t for t in re.split(r"[^A-Za-z\\u00c0-\\u024f]+", (name or "").lower()) if t]
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
'''


def patch_normalise():
    src = NORMALISE.read_text(encoding="utf-8")
    if "frame_names_speaker" in src:
        print("normalise.py already patched")
        return False

    start = src.find("_QUOTE_CHARS = ")
    if start < 0:
        sys.exit("ERROR: could not find _QUOTE_CHARS in normalise.py")
    # Everything from _QUOTE_CHARS up to the end of mark_attribution.
    end_anchor = src.find("def make_doc_id", start)
    if end_anchor < 0:
        sys.exit("ERROR: could not find make_doc_id in normalise.py")

    old_block = src[start:end_anchor]
    if "_ATTRIB_CUE" not in old_block or "def mark_attribution" not in old_block:
        sys.exit("ERROR: the block between _QUOTE_CHARS and make_doc_id is not "
                 "what this patch expects. Nothing changed.")

    keep = re.search(
        r"(SPEAKER_ONLY_TYPES = \{[^}]*\}\n)", old_block)
    if not keep:
        sys.exit("ERROR: could not find SPEAKER_ONLY_TYPES. Nothing changed.")

    new_block = (
        NEW_FUNC.split("# Titles and honorifics")[0]
        + "# Document types where the whole body is the speaker talking.\n"
        + keep.group(1)
        + "\n\n"
        + "# Titles and honorifics"
        + NEW_FUNC.split("# Titles and honorifics")[1]
        + "\n\n"
    )

    shutil.copy2(NORMALISE, NORMALISE.with_suffix(".py.bak2"))
    NORMALISE.write_text(src[:start] + new_block + src[end_anchor:],
                         encoding="utf-8")
    print(f"patched {NORMALISE} (backup: {NORMALISE.with_suffix('.py.bak2')})")
    return True


def patch_local():
    src = LOCAL.read_text(encoding="utf-8")
    if "speaker_hint" in src and "mark_attribution(segment(text, doc_id), doc_type," in src:
        print("local.py already patched")
        return False
    old = "units = mark_attribution(segment(text, doc_id), doc_type)"
    if src.count(old) != 1:
        sys.exit(f"ERROR: expected one call site in local.py, found "
                 f"{src.count(old)}. Nothing changed.")
    new = ('units = mark_attribution(\n'
           '        segment(text, doc_id),\n'
           '        doc_type,\n'
           '        (row.get("speaker_hint") or "").strip() or None,\n'
           '    )')
    shutil.copy2(LOCAL, LOCAL.with_suffix(".py.bak2"))
    LOCAL.write_text(src.replace(old, new), encoding="utf-8")
    print(f"patched {LOCAL} (backup: {LOCAL.with_suffix('.py.bak2')})")
    return True


def main():
    if not NORMALISE.is_file():
        sys.exit("ERROR: run this from the eps folder (the one with "
                 "pyproject.toml).")
    a = patch_normalise()
    b = patch_local()
    if a or b:
        print()
        print("Next:")
        print("  python -m pytest tests/ -q      # expect some failures - the")
        print("                                  # old tests assert the old rule")
        print("  eps ingest --run-dir runs/dfe-v2 --manifest manifest_dfe_v2.csv")


if __name__ == "__main__":
    main()
