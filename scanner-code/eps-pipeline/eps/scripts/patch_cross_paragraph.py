"""
patch_cross_paragraph.py

Relaxes the single-paragraph restriction in reconstruct_quote(), but only for
document types where the whole text is the speaker's own words (speeches).

Why: GOV.UK speeches use very short paragraphs, so a single policy claim often
runs across three or four of them. The old rule rejected every such passage.
Press releases keep the old behaviour, because there consecutive paragraphs can
each carry a separate quoted remark, and joining them would put the
department's attribution frame inside the quote.

Because sent_idx restarts at 1 in each paragraph, the contiguity check has to
be rewritten at the same time - otherwise lifting the paragraph rule would let
through spans that skip material.

Run from the eps folder (the one with pyproject.toml):

    python scripts\\patch_cross_paragraph.py

It writes a .bak backup first and refuses to change anything it does not
recognise.
"""

import re
import shutil
import sys
from pathlib import Path

TARGET = Path("src/eps/validate.py")

OLD_PATTERN = re.compile(
    r"[ \t]*if len\(\{u\.para_idx for u in units\}\) > 1:\n"
    r"[ \t]*return \"\", RejectReason\.CROSS_PARAGRAPH\n"
    r"\s*\n"
    r"[ \t]*for a, b in zip\(units, units\[1:\]\):\n"
    r"[ \t]*if b\.sent_idx != a\.sent_idx \+ 1:\n"
    r"[ \t]*return \"\", RejectReason\.NON_CONTIGUOUS\n"
)

NEW_BLOCK = '''    # A speech is the speaker's own words throughout, so a claim running across
    # consecutive short paragraphs is one passage and may be quoted as one. The
    # guide asks for meaningful paragraph boundaries to be preserved, which
    # presupposes a quote may contain one.
    #
    # Press releases keep the stricter rule. There, two consecutive paragraphs
    # can each carry a separate quoted remark, both attributable, and
    # trim_to_quoted_span() takes the OUTERMOST quote marks - so a joined span
    # would silently return  A." She added: "B  with the department's
    # attribution frame inside the quotation.
    allow_cross_para = doc.doc_type in SPEAKER_ONLY_TYPES

    if not allow_cross_para and len({u.para_idx for u in units}) > 1:
        return "", RejectReason.CROSS_PARAGRAPH

    # sent_idx restarts inside each paragraph, so "the next sentence" means
    # either the next sentence of this paragraph, or the first sentence of the
    # next paragraph when this unit was the last of its own. Bounds are taken
    # from the whole document so a skipped sentence cannot masquerade as a
    # paragraph break.
    _bounds: dict[int, tuple[int, int]] = {}
    for _u in doc.units:
        _lo, _hi = _bounds.get(_u.para_idx, (_u.sent_idx, _u.sent_idx))
        _bounds[_u.para_idx] = (min(_lo, _u.sent_idx), max(_hi, _u.sent_idx))

    for a, b in zip(units, units[1:]):
        same_para = b.para_idx == a.para_idx and b.sent_idx == a.sent_idx + 1
        next_para = (
            b.para_idx == a.para_idx + 1
            and a.sent_idx == _bounds.get(a.para_idx, (0, 0))[1]
            and b.sent_idx == _bounds.get(b.para_idx, (0, 0))[0]
        )
        if not (same_para or next_para):
            return "", RejectReason.NON_CONTIGUOUS
'''


def main():
    if not TARGET.is_file():
        sys.exit(f"ERROR: cannot find {TARGET}. Run this from the eps folder "
                 f"(the one containing pyproject.toml).")

    src = TARGET.read_text(encoding="utf-8")

    if "allow_cross_para" in src:
        sys.exit("Already patched - nothing to do.")

    matches = list(OLD_PATTERN.finditer(src))
    if len(matches) != 1:
        sys.exit(
            f"ERROR: expected to find the paragraph/contiguity block exactly "
            f"once, found {len(matches)}. The file differs from what this "
            f"patch was written against; nothing has been changed."
        )

    backup = TARGET.with_suffix(".py.bak")
    shutil.copy2(TARGET, backup)

    patched = src[:matches[0].start()] + NEW_BLOCK + src[matches[0].end():]
    TARGET.write_text(patched, encoding="utf-8")

    print(f"backed up  -> {backup}")
    print(f"patched    -> {TARGET}")
    print()
    print("Removed:")
    print("    single-paragraph restriction for all document types")
    print("Added:")
    print("    cross-paragraph spans allowed for SPEAKER_ONLY_TYPES only")
    print("    contiguity check that understands paragraph boundaries")
    print()
    print("Next:  eps build --run-dir runs/dfe-pilot     (free, uses the cache)")


if __name__ == "__main__":
    main()
