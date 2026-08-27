"""JEL taxonomy handling.

The taxonomy is frozen to a local CSV and the model selects from it rather than
recalling codes from memory. That makes invented codes and mangled titles
impossible instead of merely discouraged.

Run `eps fetch-jel` to (re)build reference/jel_codes.csv from the AEA page. The
file shipped in the repo is a bootstrap: verify it against the live page before
using it for production, as the field guide requires.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .models import JELAssignment

AEA_URL = "https://www.aeaweb.org/econlit/jelCodes.php?view=jel"


@dataclass(frozen=True)
class JELCode:
    code: str
    title: str
    level: int  # 1 = major (J), 2 = subcategory (J2), 3 = detailed (J24)
    parent: str


class JELTaxonomy:
    def __init__(self, codes: list[JELCode]):
        self.by_code: dict[str, JELCode] = {c.code: c for c in codes}
        self.codes = codes

    # -- construction -------------------------------------------------------

    @classmethod
    def load(cls, path: str | Path) -> "JELTaxonomy":
        codes: list[JELCode] = []
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                codes.append(
                    JELCode(
                        code=row["code"].strip(),
                        title=row["title"].strip(),
                        level=int(row["level"]),
                        parent=row.get("parent", "").strip(),
                    )
                )
        if not codes:
            raise ValueError(f"no JEL codes loaded from {path}")
        return cls(codes)

    # -- lookup -------------------------------------------------------------

    def majors(self) -> list[JELCode]:
        return [c for c in self.codes if c.level == 1]

    def subcategories(self, major: str) -> list[JELCode]:
        return [c for c in self.codes if c.level == 2 and c.parent == major]

    def detailed(self, sub: str) -> list[JELCode]:
        return [c for c in self.codes if c.level == 3 and c.parent == sub]

    def title(self, code: str) -> Optional[str]:
        c = self.by_code.get(code)
        return c.title if c else None

    # -- validation ---------------------------------------------------------

    def check(self, a: JELAssignment) -> tuple[bool, str]:
        """Codes must exist, titles must match exactly, hierarchy must be
        consistent (J24 sits under J2 sits under J)."""
        levels = [
            (1, a.major_code, a.major_title),
            (2, a.sub_code, a.sub_title),
            (3, a.detailed_code, a.detailed_title),
        ]
        seen: dict[int, str] = {}
        for level, code, title in levels:
            if not code:
                continue
            known = self.by_code.get(code)
            if known is None:
                return False, f"unknown JEL code {code!r}"
            if known.level != level:
                return False, f"{code!r} is not a level-{level} code"
            if title and title.strip() != known.title:
                return False, f"title for {code!r} does not match the AEA title"
            seen[level] = code

        if 3 in seen and 2 in seen:
            if self.by_code[seen[3]].parent != seen[2]:
                return False, f"{seen[3]!r} does not sit under {seen[2]!r}"
        if 2 in seen and 1 in seen:
            if self.by_code[seen[2]].parent != seen[1]:
                return False, f"{seen[2]!r} does not sit under {seen[1]!r}"
        if 3 in seen and 2 not in seen:
            return False, "detailed code given without its parent subcategory"
        if 2 in seen and 1 not in seen:
            return False, "subcategory given without its major category"
        return True, ""

    def fill_titles(self, a: JELAssignment) -> JELAssignment:
        """Populate titles from the frozen taxonomy, so the model never has to
        reproduce them (and cannot corrupt them)."""
        if a.major_code:
            a.major_title = self.title(a.major_code) or a.major_title
        if a.sub_code:
            a.sub_title = self.title(a.sub_code) or a.sub_title
        if a.detailed_code:
            a.detailed_title = self.title(a.detailed_code) or a.detailed_title
        return a


# --- fetching --------------------------------------------------------------

_CODE_RE = re.compile(r"^([A-Z])(\d)?(\d)?$")


def fetch_from_aea(url: str = AEA_URL, timeout: int = 60) -> list[JELCode]:
    """Scrape the AEA JEL page into a flat code/title/level/parent list.

    The AEA page renders the hierarchy as nested lists whose items begin with
    the code followed by the title. This parser is intentionally permissive
    about markup and strict about code shape; inspect the output before use.
    """
    import requests
    from lxml import html as lxml_html

    resp = requests.get(url, timeout=timeout, headers={"User-Agent": "eps/0.1"})
    resp.raise_for_status()
    tree = lxml_html.fromstring(resp.text)

    found: dict[str, JELCode] = {}
    for el in tree.iter():
        # Comments and processing instructions are nodes too, and
        # text_content() rejects them. Their .tag is a callable
        # rather than a string, which is how lxml distinguishes them.
        if not isinstance(el.tag, str):
            continue
        text = " ".join((el.text_content() or "").split())
        if not text or len(text) > 400:
            continue
        m = re.match(r"^([A-Z]\d{0,2})\s*[-–—:]\s*(.+)$", text)
        if not m:
            continue
        code, title = m.group(1), m.group(2).strip()
        if not _CODE_RE.match(code):
            continue
        level = len(code) if len(code) <= 3 else 0
        if level not in (1, 2, 3):
            continue
        # Keep the shortest rendering of each code (avoids nested duplicates
        # where a parent element contains its children's text).
        if code in found and len(found[code].title) <= len(title):
            continue
        parent = code[:-1] if level > 1 else ""
        found[code] = JELCode(code=code, title=title, level=level, parent=parent)

    return sorted(found.values(), key=lambda c: (c.code))


def write_csv(codes: list[JELCode], path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["code", "title", "level", "parent"])
        for c in codes:
            w.writerow([c.code, c.title, c.level, c.parent])
