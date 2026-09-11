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
_ACTIVE_CODE_RE = re.compile(r"^[A-Z]\d{2}$")


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


# --- the active three-character list ----------------------------------------
#
# Everything above is the hierarchical taxonomy, which the rest of the pipeline
# still uses. Classification no longer does: it picks a three-character code
# straight from the flat list below, and the parents are derived here by lookup
# rather than asked of the model.

ACTIVE_CODES_FILE = "jel_codes_active_20260828.csv"


@dataclass(frozen=True)
class ActiveCode:
    """One active three-character code, with the parents it belongs to.

    The parent columns are for lookup and monitoring only. They are never shown
    to the model: seeing the hierarchy is what invites picking a branch before
    picking a code, which is the behaviour this list replaces.
    """

    code: str
    title: str
    sub_code: str
    sub_title: str
    major_code: str
    major_title: str
    is_residual: bool


class ActiveJELList:
    """The dated list of active codes the classifier selects from.

    Presents the same `check()` contract as `JELTaxonomy`, so `validate_jel`
    works against either without knowing which it was handed.
    """

    def __init__(self, codes: list[ActiveCode], source: str = ""):
        if not codes:
            raise ValueError("no active JEL codes loaded")
        self.codes = codes
        self.source = source
        self.by_code: dict[str, ActiveCode] = {c.code: c for c in codes}

    @classmethod
    def load(cls, path: str | Path) -> "ActiveJELList":
        path = Path(path)
        codes: list[ActiveCode] = []
        # utf-8-sig: the file is plain UTF-8, but a BOM would otherwise end up
        # inside the first column name.
        with open(path, newline="", encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                code = r["jel_code"].strip()
                if not _ACTIVE_CODE_RE.match(code):
                    raise ValueError(f"{path}: {code!r} is not a three-character code")
                codes.append(ActiveCode(
                    code=code,
                    title=r["jel_title"].strip(),
                    sub_code=r["subcategory_code"].strip(),
                    sub_title=r["subcategory_title"].strip(),
                    major_code=r["major_code"].strip(),
                    major_title=r["major_title"].strip(),
                    is_residual=r.get("is_residual", "").strip().lower() == "true",
                ))
        dupes = len(codes) - len({c.code for c in codes})
        if dupes:
            raise ValueError(f"{path}: {dupes} duplicate code(s)")
        return cls(codes, source=path.name)

    def __contains__(self, code: str) -> bool:
        return code in self.by_code

    def __len__(self) -> int:
        return len(self.codes)

    # -- what the model sees ------------------------------------------------

    def prompt_lines(self) -> str:
        """The list as the model receives it: code and title, nothing else."""
        return "\n".join(f"{c.code} \u2014 {c.title}" for c in self.codes)

    # -- what the model never has to supply ---------------------------------

    def assignment(self, code: str, match_strength: int = 0) -> JELAssignment:
        """Build a full assignment from a three-character code by lookup.

        Every code on the list carries both parents, so this cannot fail for a
        code that is on the list. Callers must refuse codes that are not.
        """
        c = self.by_code[code]
        return JELAssignment(
            major_code=c.major_code, major_title=c.major_title,
            sub_code=c.sub_code, sub_title=c.sub_title,
            detailed_code=c.code, detailed_title=c.title,
            match_strength=match_strength,
        )

    # -- validation ---------------------------------------------------------

    def check(self, a: JELAssignment) -> tuple[bool, str]:
        """Codes must be on the list, at three characters, with the parents
        this list gives them rather than whatever a caller filled in."""
        if not a.detailed_code:
            return False, "no three-character JEL code"
        known = self.by_code.get(a.detailed_code)
        if known is None:
            return False, f"{a.detailed_code!r} is not on the active list"
        for label, got, want in (
            ("detailed title", a.detailed_title, known.title),
            ("subcategory", a.sub_code, known.sub_code),
            ("subcategory title", a.sub_title, known.sub_title),
            ("major", a.major_code, known.major_code),
            ("major title", a.major_title, known.major_title),
        ):
            if got and got.strip() != want:
                return False, f"{a.detailed_code}: {label} does not match the active list"
        if a.match_strength not in (1, 2, 3):
            return False, (f"{a.detailed_code}: match strength {a.match_strength!r} "
                           f"is not 1, 2 or 3")
        return True, ""
