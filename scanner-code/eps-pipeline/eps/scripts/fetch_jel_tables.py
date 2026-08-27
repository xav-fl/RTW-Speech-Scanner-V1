"""
fetch_jel_tables.py

Replacement for `eps fetch-jel`, which fails because it expects the AEA page to
render each entry as  "I22 - Educational Finance"  on one line. It does not.
The page uses TABLES, with the code in one cell and the title in the next:

    | A1 |  General Economics                   |         |
    |    |  A10                                 | General |

so a regex looking for a dash between code and title matches nothing, which is
why fetch-jel reported "No codes parsed" rather than crashing.

Run from the eps folder (the one with pyproject.toml):

    python scripts\\fetch_jel_tables.py

Add --dry-run to see what it would write without touching the file.
Add --diagnose if it finds nothing, to dump the actual table structure.
"""

import argparse
import csv
import re
import shutil
import sys
from pathlib import Path

AEA_URL = "https://www.aeaweb.org/econlit/jelCodes.php?view=jel"
OUT = Path("src/eps/reference/jel_codes.csv")

CODE_RE = re.compile(r"^([A-Z])(\d{0,2})$")


def cell_texts(row):
    out = []
    for td in row:
        if not isinstance(td.tag, str):
            continue
        out.append(" ".join((td.text_content() or "").split()))
    return out


def parse(html_text, diagnose=False):
    from lxml import html as lxml_html

    tree = lxml_html.fromstring(html_text)
    found = {}
    rows_seen = 0
    samples = []

    for row in tree.iter("tr"):
        cells = cell_texts(row)
        rows_seen += 1
        if diagnose and len(samples) < 25 and any(cells):
            samples.append(cells)

        # Find a cell that is exactly a JEL code, and take the next non-empty
        # cell as its title. This handles both layouts on the page: the code
        # may sit in the first or the second column depending on depth.
        for i, c in enumerate(cells):
            m = CODE_RE.match(c)
            if not m:
                continue
            title = next((t for t in cells[i + 1:] if t), "")
            if not title or CODE_RE.match(title):
                continue
            code = c
            level = len(code)
            if level not in (1, 2, 3):
                continue
            # Some three-character codes (B00, C00) have no two-character
            # parent on the page. Fall back to the major letter rather than
            # recording a parent that does not exist.
            if level == 3:
                parent = code[:2]
            elif level == 2:
                parent = code[:1]
            else:
                parent = ""
            prev = found.get(code)
            if prev and len(prev["title"]) >= len(title):
                continue
            found[code] = {
                "code": code,
                "title": title,
                "level": str(level),
                "parent": parent,
            }
            break

    if diagnose:
        print(f"\n--- {rows_seen} table rows seen; first rows with content ---")
        for s in samples:
            print("   ", s)
        print()

    # Repair level-3 parents whose two-character parent does not exist.
    for c in found.values():
        if c["level"] == "3" and c["parent"] not in found:
            c["parent"] = c["code"][:1]

    return sorted(found.values(), key=lambda c: c["code"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--diagnose", action="store_true")
    ap.add_argument("--url", default=AEA_URL)
    args = ap.parse_args()

    try:
        import requests
    except ImportError:
        sys.exit("ERROR: requests is not installed. Run: pip install requests")

    print(f"fetching {args.url}")
    resp = requests.get(args.url, timeout=60,
                        headers={"User-Agent": "eps/0.1 (research)"})
    resp.raise_for_status()

    codes = parse(resp.text, diagnose=args.diagnose)

    levels = {}
    for c in codes:
        levels[c["level"]] = levels.get(c["level"], 0) + 1
    print(f"parsed {len(codes)} codes: "
          + ", ".join(f"level {k} = {v}" for k, v in sorted(levels.items())))

    if len(codes) < 200:
        print("\nThat is fewer than expected (the real taxonomy has 800+ "
              "entries). Nothing has been written.")
        print("Re-run with --diagnose to see the actual table structure.")
        sys.exit(1)

    # Spot-check the codes the field guide's own examples use.
    by_code = {c["code"]: c for c in codes}
    print("\nSpot check against the field guide's examples:")
    for code in ("I22", "I26", "J24", "R31", "D83"):
        c = by_code.get(code)
        print(f"   {code}: {c['title'] if c else 'MISSING'}")

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return

    if OUT.is_file():
        backup = OUT.with_suffix(".csv.bak")
        shutil.copy2(OUT, backup)
        print(f"\nbacked up existing file -> {backup}")
        with open(OUT, newline="", encoding="utf-8-sig") as fh:
            header = next(csv.reader(fh))
    else:
        header = ["code", "title", "level", "parent"]

    missing = [h for h in header if h not in ("code", "title", "level", "parent")]
    if missing:
        sys.exit(f"ERROR: the existing file has columns this script does not "
                 f"produce: {missing}. Nothing written.")

    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=header)
        w.writeheader()
        for c in codes:
            w.writerow({h: c.get(h, "") for h in header})

    print(f"wrote {OUT}: {len(codes)} codes")
    print("\nNext:  eps build --run-dir runs/dfe-pilot")


if __name__ == "__main__":
    main()
