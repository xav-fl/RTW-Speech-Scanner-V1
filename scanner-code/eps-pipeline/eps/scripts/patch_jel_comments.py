"""
patch_jel_comments.py

Fixes: ValueError: Input object is not an XML element: HtmlComment

tree.iter() walks every node in the document, including HTML comments and
processing instructions. text_content() only works on real elements, so the
loop dies on the first comment in the AEA page's markup.

In lxml, a comment's .tag is a callable rather than a string, which is the
standard way to tell them apart.

Run from the eps folder (the one with pyproject.toml):

    python scripts\\patch_jel_comments.py
"""

import re
import shutil
import sys
from pathlib import Path

TARGET = Path("src/eps/jel.py")

OLD = re.compile(
    r"([ \t]*)for el in tree\.iter\(\):\n"
    r"([ \t]*)text = \" \"\.join\(\(el\.text_content\(\) or \"\"\)\.split\(\)\)\n"
)


def main():
    if not TARGET.is_file():
        sys.exit(f"ERROR: cannot find {TARGET}. Run this from the eps folder "
                 f"(the one containing pyproject.toml).")

    src = TARGET.read_text(encoding="utf-8")

    if "isinstance(el.tag, str)" in src:
        sys.exit("Already patched - nothing to do.")

    matches = list(OLD.finditer(src))
    if len(matches) != 1:
        sys.exit(
            f"ERROR: expected to find the iteration line exactly once, found "
            f"{len(matches)}. Nothing has been changed."
        )

    m = matches[0]
    outer, inner = m.group(1), m.group(2)
    new = (
        f"{outer}for el in tree.iter():\n"
        f"{inner}# Comments and processing instructions are nodes too, and\n"
        f"{inner}# text_content() rejects them. Their .tag is a callable\n"
        f"{inner}# rather than a string, which is how lxml distinguishes them.\n"
        f"{inner}if not isinstance(el.tag, str):\n"
        f"{inner}    continue\n"
        f"{inner}text = \" \".join((el.text_content() or \"\").split())\n"
    )

    backup = TARGET.with_suffix(".py.bak")
    shutil.copy2(TARGET, backup)
    TARGET.write_text(src[:m.start()] + new + src[m.end():], encoding="utf-8")

    print(f"backed up  -> {backup}")
    print(f"patched    -> {TARGET}")
    print()
    print("Next:  eps fetch-jel")


if __name__ == "__main__":
    main()
