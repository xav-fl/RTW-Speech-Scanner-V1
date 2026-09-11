"""
audit_text_fidelity.py

Two jobs, in this order:

  --audit    fetch documents fresh from the GOV.UK Content API and compare them
             against the harvested .txt files, to measure how much text was
             corrupted during the original extraction.

  --rewrite  re-extract every document's text properly, into a NEW folder,
             leaving the originals untouched.

Why this exists
---------------
Two faults were found in the harvested text:

1. Missing spaces. The page says "Parents end up fighting"; the harvested file
   says "Parents endup fighting". Newlines in the source HTML were removed
   rather than replaced with a space. This breaks the pipeline's central
   guarantee: quotes are verbatim against the frozen text, but the frozen text
   no longer matches the page it cites.

2. Lost quote structure. GOV.UK marks ministerial quotations with <blockquote>
   and NO quotation marks. Flattening that to plain paragraphs destroys the
   only signal distinguishing the minister's words from departmental prose or
   from a union leader's response.

The rewriter preserves blockquotes by prefixing those lines with "> ", and
records who introduced each block, so attribution can be decided structurally
rather than guessed from punctuation.

Usage (from the harvest folder, alongside extraction_queue.csv):

    python audit_text_fidelity.py --audit --sample 12
    python audit_text_fidelity.py --rewrite --out documents_v2
"""

import argparse
import csv
import json
import re
import sys
import time
import urllib.request
from html import unescape
from pathlib import Path

CONTENT_API = "https://www.gov.uk/api/content"
UA = "eps-research/0.1 (academic research; contact via institution)"


# --------------------------------------------------------------------------
# HTML -> text, done carefully
# --------------------------------------------------------------------------

_BLOCK_OPEN = re.compile(r"<(p|li|h[1-6]|blockquote|div|tr)\b[^>]*>", re.I)
_BLOCK_CLOSE = re.compile(r"</(p|li|h[1-6]|blockquote|div|tr)\s*>", re.I)
_BR = re.compile(r"<br\s*/?>", re.I)
_TAG = re.compile(r"<[^>]+>")
_ABBR = re.compile(r"<abbr\b[^>]*>(.*?)</abbr>", re.I | re.S)


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


def render(blocks: list[tuple[str, str]]) -> str:
    lines = []
    for kind, text in blocks:
        lines.append(("> " + text) if kind == "quote" else text)
    return "\n\n".join(lines)


# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------

def fetch_content(url: str, timeout: int = 30) -> dict:
    path = re.sub(r"^https?://(www\.)?gov\.uk", "", url.split("?")[0]).rstrip("/")
    req = urllib.request.Request(CONTENT_API + path, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def body_html(doc: dict) -> str:
    details = doc.get("details") or {}
    body = details.get("body")
    if isinstance(body, str):
        return body
    for key in ("govspeak", "parts"):
        v = details.get(key)
        if isinstance(v, str):
            return v
    return ""


def speaker_names(doc: dict) -> list[str]:
    out = []
    for p in (doc.get("links") or {}).get("speaker", []) or []:
        t = p.get("title")
        if t:
            out.append(t)
    return out


# --------------------------------------------------------------------------
# Comparison
# --------------------------------------------------------------------------

WORD = re.compile(r"[A-Za-z][A-Za-z'\u2019-]+")


def strip_header(s: str) -> str:
    """Drop the harvest's metadata header (TITLE:/URL:/DATE:/... then '---').

    Those lines are the harness, not the page. Leaving them in makes tokens
    like 'govuk' look like corrupted body text.
    """
    m = re.search(r"^-{3,}\s*$", s, re.M)
    return s[m.end():] if m else s


def words(s: str) -> list[str]:
    return [w.lower() for w in WORD.findall(s)]


def compare(old_text: str, new_text: str) -> dict:
    ow, nw = words(old_text), words(new_text)
    oset, nset = set(ow), set(nw)
    # Words present fresh but missing from the harvest are the interesting
    # ones: usually half of a welded pair.
    missing = sorted(nset - oset)
    extra = sorted(oset - nset)
    welded = []
    for e in extra:
        if len(e) < 5:
            continue
        for i in range(2, len(e) - 1):
            if e[:i] in nset and e[i:] in nset:
                welded.append((e, e[:i] + " " + e[i:]))
                break
    return {
        "old_words": len(ow),
        "new_words": len(nw),
        "missing": missing,
        "extra": extra,
        "welded": welded,
    }


# --------------------------------------------------------------------------

def load_queue(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    return [r for r in rows
            if (r.get("is_primary") or "").strip().lower() in ("yes", "true", "1")
            and not (r.get("exclusion_reason") or "").strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", default="extraction_queue.csv")
    ap.add_argument("--docs-root", default=".")
    ap.add_argument("--audit", action="store_true")
    ap.add_argument("--rewrite", action="store_true")
    ap.add_argument("--out", default="documents_v2")
    ap.add_argument("--sample", type=int, default=12)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--url", default=None,
                    help="audit only queue rows whose url contains this string")
    ap.add_argument("--pause", type=float, default=0.4)
    args = ap.parse_args()

    if not (args.audit or args.rewrite):
        sys.exit("Choose --audit or --rewrite.")

    rows = load_queue(args.queue)
    root = Path(args.docs_root)

    if args.audit:
        import random
        if args.url:
            sample = [r for r in rows if args.url in r["url"]]
            if not sample:
                sys.exit(f"No queue row whose url contains {args.url!r}")
        else:
            random.seed(args.seed)
            sample = random.sample(rows, min(args.sample, len(rows)))
        n_bad = 0
        total_welded = 0
        print(f"auditing {len(sample)} of {len(rows)} documents\n")
        for r in sample:
            p = root / (r.get("text_file") or "").replace("\\", "/")
            if not p.is_file():
                print(f"  MISSING FILE  {p}")
                continue
            try:
                doc = fetch_content(r["url"])
            except Exception as exc:
                print(f"  fetch failed   {r['url']}  ({exc})")
                continue
            fresh = render(html_to_blocks(body_html(doc)))
            old = strip_header(p.read_text(encoding="utf-8", errors="replace"))
            d = compare(old, fresh)
            nq = fresh.count("\n> ") + (1 if fresh.startswith("> ") else 0)
            flag = "OK " if not d["welded"] else "BAD"
            if d["welded"]:
                n_bad += 1
                total_welded += len(d["welded"])
            print(f"  {flag} {len(d['welded']):3d} welded  {nq:2d} quote-blocks  "
                  f"{r['normalised_document_type']:14s} {r['document_title'][:38]}")
            for a, b in d["welded"][:4]:
                print(f"        {a!r} should be {b!r}")
            time.sleep(args.pause)
        print(f"\n{n_bad}/{len(sample)} documents show welded words; "
              f"{total_welded} instances found in the sample.")
        if n_bad:
            print("The frozen corpus does not match the pages it cites. "
                  "Re-extract with --rewrite before running extraction again.")
        return

    # rewrite
    outdir = root / args.out
    outdir.mkdir(parents=True, exist_ok=True)
    manifest_out = outdir / "rewrite_log.csv"
    written = failed = 0
    with open(manifest_out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["url", "new_file", "quote_blocks", "speakers", "status"])
        for i, r in enumerate(rows, 1):
            name = Path((r.get("text_file") or f"doc{i}.txt")).name
            dest = outdir / name
            try:
                doc = fetch_content(r["url"])
                blocks = html_to_blocks(body_html(doc))
                dest.write_text(render(blocks), encoding="utf-8")
                nq = sum(1 for k, _ in blocks if k == "quote")
                w.writerow([r["url"], str(dest), nq,
                            "; ".join(speaker_names(doc)), "ok"])
                written += 1
            except Exception as exc:
                w.writerow([r["url"], "", 0, "", f"error: {exc}"])
                failed += 1
            if i % 25 == 0:
                print(f"  {i}/{len(rows)} ...")
            time.sleep(args.pause)
    print(f"\nwrote {written} files to {outdir}, {failed} failed")
    print(f"log: {manifest_out}")


if __name__ == "__main__":
    main()
