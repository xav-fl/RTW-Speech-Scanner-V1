#!/usr/bin/env python3
"""
GOV.UK harvester for the economics-relevant policy statements project.

Pulls every speech / statement / press release published by the UK ministerial
departments in a date window, fetches the full text of each, and attributes it
to a named speaker where GOV.UK records one.

Outputs two files:
  screening_log.csv  -- one row per document inspected (Section 6 of the guide)
  documents/*.txt    -- full plain text of each document, for the extraction step

Standard library only. No pip install needed.

Usage:
    python govuk_harvest.py --start 2026-01-01 --end 2026-07-31 --out ./harvest
"""

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser

SEARCH_API = "https://www.gov.uk/api/search.json"
CONTENT_API = "https://www.gov.uk/api/content"
UA = "academic-research-harvester/1.0 (economics policy statements project)"

# GOV.UK content_store_document_type -> the normalised labels in Section 4 of the guide.
# Add or remove keys here to widen/narrow the net.
DOC_TYPE_MAP = {
    "speech": "speech",
    "authored_article": "op_ed",
    "written_statement": "statement",
    "oral_statement": "statement",
    "government_response": "statement",
    "press_release": "press_release",
    "news_story": "press_release",
    "correspondence": "letter",
    "transcript": "interview_transcript",
}


# ---------------------------------------------------------------- HTTP helpers

def get_json(url, params=None, retries=4):
    if params:
        url = url + "?" + urllib.parse.urlencode(params, doseq=True)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            if attempt == retries - 1:
                sys.stderr.write("FAILED %s -- %s\n" % (url, e))
                return None
            time.sleep(2 ** attempt)
    return None


class TextExtractor(HTMLParser):
    """Strip HTML to readable text, keeping paragraph boundaries.

    Paragraph boundaries matter: the guide requires preserving them, and quotes
    must be contiguous within a block."""

    BLOCK = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6",
             "blockquote", "tr", "br", "section"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)

    def text(self):
        raw = "".join(self.parts)
        raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
        raw = re.sub(r"\n\s*\n\s*", "\n\n", raw)
        return raw.strip()


def html_to_text(html):
    p = TextExtractor()
    p.feed(html or "")
    return p.text()


# ------------------------------------------------------- organisation lookup

def resolve_departments():
    """Map each canonical department name to its GOV.UK slug.

    Deliberately does NOT filter on organisation_type. When GOV.UK closes a
    department it frequently reclassifies it from 'ministerial_department' to
    'other', so a type filter drops exactly the merged predecessors we need
    (DBT and DSIT). Matching against the canonical list is what bounds the
    result, so genuinely historical departments never get through."""
    available, offset = {}, 0
    while True:
        data = get_json(SEARCH_API, {
            "filter_format": "organisation",
            "count": 1000,
            "start": offset,
            "fields": ["title", "slug", "organisation_state"],
            "order": "title",
        })
        if not data:
            break
        batch = data.get("results", [])
        for r in batch:
            key = normalise_institution(r.get("title", ""))
            if not key or not r.get("slug"):
                continue
            # Keep EVERY slug for a name. GOV.UK carries both 'wales-office' and
            # 'office-of-the-secretary-of-state-for-wales' as separate records
            # with content split between them; picking one silently loses the
            # other. Live organisations sort first.
            entry = {
                "title": r.get("title", ""),
                "slug": r.get("slug", ""),
                "state": r.get("organisation_state", ""),
            }
            bucket = available.setdefault(key, [])
            if entry["slug"] not in [b["slug"] for b in bucket]:
                bucket.append(entry)
                bucket.sort(key=lambda b: b["state"] == "closed")
        offset += len(batch)
        if len(batch) < 1000 or offset >= data.get("total", 0):
            break
        time.sleep(0.3)

    resolved, unresolved = [], []
    for name in CANONICAL_UK_DEPARTMENTS:
        hits = available.get(normalise_institution(name)) or []
        if hits:
            resolved.append({
                "canonical": name,
                "title": hits[0]["title"],
                "slug": hits[0]["slug"],
                "slugs": [h["slug"] for h in hits],
                "state": hits[0]["state"],
            })
        else:
            unresolved.append(name)
    return resolved, unresolved


# --------------------------------------------------------------- search step

def search_documents(slug, start_date, end_date, doc_types, page_size=200):
    """Page through every matching document for one organisation."""
    results, offset = [], 0
    while True:
        data = get_json(SEARCH_API, {
            "filter_organisations": slug,
            "filter_content_store_document_type": list(doc_types),
            "filter_public_timestamp": "from:%s,to:%s" % (start_date, end_date),
            "count": page_size,
            "start": offset,
            "order": "-public_timestamp",
            "fields": ["title", "link", "public_timestamp",
                       "content_store_document_type", "description"],
        })
        if not data:
            break
        batch = data.get("results", [])
        results.extend(batch)
        offset += len(batch)
        if len(batch) < page_size or offset >= data.get("total", 0):
            break
        time.sleep(0.3)
    return results


# -------------------------------------------------------------- content step

def fetch_content(path):
    """Fetch one document's full record from the Content API."""
    return get_json(CONTENT_API + path)


def extract_speakers(content):
    """Return speaker names GOV.UK explicitly links to the document.

    Speeches carry links.speaker; this is authoritative attribution and is far
    more reliable than parsing the body. Press releases usually carry nothing,
    which is why press releases need the name-matching fallback downstream."""
    names = []
    links = (content or {}).get("links", {}) or {}
    for key in ("speaker", "people", "ministers"):
        for person in links.get(key, []) or []:
            title = person.get("title")
            if title and title not in names:
                names.append(title)
    details = (content or {}).get("details", {}) or {}
    if isinstance(details.get("speaker"), str) and details["speaker"] not in names:
        names.append(details["speaker"])
    return names


def body_text(content):
    details = (content or {}).get("details", {}) or {}
    body = details.get("body")
    if isinstance(body, str) and body.strip():
        return html_to_text(body)
    # Some formats split the body into parts.
    chunks = []
    for part in details.get("parts", []) or []:
        chunks.append(part.get("title", ""))
        chunks.append(html_to_text(part.get("body", "")))
    return "\n\n".join(c for c in chunks if c).strip()


# ---------------------------------------------------------- officeholder map

def load_officeholders(path):
    """Read the officeholders CSV. Uses the csv module rather than splitting on
    commas -- several institution names contain commas inside quoted fields."""
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if (row.get("country") or "").strip() != "United Kingdom":
                continue
            rows.append({
                "institution": (row.get("institution") or "").strip(),
                "officeholder": (row.get("officeholder") or "").strip(),
                "start_date": (row.get("start_date") or "").strip(),
                "end_date": (row.get("end_date") or "").strip(),
            })
    return rows


HONORIFICS = r"""(?:^|\s)(?:The|Rt\.?\s*Hon\.?|Right\s+Honourable|Sir|Dame|Lord|
Lady|Baroness|Baron|Earl|Viscount|Mr|Mrs|Ms|Miss|Dr|Prof(?:essor)?|Rev)\b\.?"""

POST_NOMINALS = {
    "mp", "msp", "ms", "mla", "qc", "kc", "cbe", "obe", "mbe", "gbe", "kbe",
    "dbe", "cb", "kcb", "gcb", "cmg", "kcmg", "gcmg", "cvo", "kcvo", "gcvo",
    "dl", "jp", "frs", "phd", "md", "esq", "bem", "vc", "gc", "pc",
}


def normalise_name(name):
    """Reduce a name to comparable lowercase tokens.

    GOV.UK returns 'The Rt Hon Bridget Phillipson MP' while the officeholders
    CSV holds 'Bridget Phillipson'. Both must reduce to the same tokens, so
    strip bracketed peerage titles, leading honorifics, and post-nominals."""
    if not name:
        return []
    name = re.sub(r"\(.*?\)", " ", name)
    name = re.sub(HONORIFICS, " ", name, flags=re.IGNORECASE | re.VERBOSE)
    name = re.sub(r"[^\w\s'-]", " ", name)
    tokens = [t.lower().strip("'-") for t in name.split() if t.strip("'-")]
    return [t for t in tokens if t not in POST_NOMINALS]


def names_match(a, b):
    """True if two names plausibly refer to the same person.

    Surname must match, plus either a shared forename or one name carrying no
    forename at all (e.g. 'Baroness Smith of Cluny')."""
    ta, tb = normalise_name(a), normalise_name(b)
    if not ta or not tb:
        return False
    if ta[-1] != tb[-1]:
        return False
    fa, fb = set(ta[:-1]), set(tb[:-1])
    if not fa or not fb:
        return True
    return bool(fa & fb)


# The frozen list from Section 2 of the field guide. The harvest iterates over
# THIS, not over whatever GOV.UK currently returns, so a department that
# publishes nothing still appears in the outputs as an explicit zero.
#
# DBIST is listed in addition to the guide's 24 because GOV.UK merged DBT and
# DSIT into it at the 2026-07-20 reshuffle. Documents published before that date
# remain filed under the old DBT and DSIT slugs, so all three must be harvested
# to cover January-July. Whether DBIST is one unit of observation or two is a
# question for the PI; collecting all three defers that decision rather than
# foreclosing it.
CANONICAL_UK_DEPARTMENTS = [
    "Attorney General's Office",
    "Cabinet Office",
    "Department for Business and Trade",
    "Department for Culture, Media and Sport",
    "Department for Education",
    "Department for Energy Security and Net Zero",
    "Department for Environment, Food and Rural Affairs",
    "Department for Science, Innovation and Technology",
    "Department for Transport",
    "Department for Work and Pensions",
    "Department of Health and Social Care",
    "Foreign, Commonwealth and Development Office",
    "HM Treasury",
    "Home Office",
    "Ministry of Defence",
    "Ministry of Housing, Communities and Local Government",
    "Ministry of Justice",
    "Northern Ireland Office",
    "Office of the Advocate General for Scotland",
    "Office of the Leader of the House of Commons",
    "Office of the Leader of the House of Lords",
    "Scotland Office",
    "UK Export Finance",
    "Wales Office",
    "Department for Business, Innovation, Science and Trade",
]

INSTITUTION_ALIASES = {
    # GOV.UK's official title -> the canonical name used in the guide and CSV.
    "office of the secretary of state for scotland": "scotland office",
    "office of the secretary of state for wales": "wales office",
    "the office of the leader of the house of commons":
        "office of the leader of the house of commons",
    "the office of the leader of the house of lords":
        "office of the leader of the house of lords",
    "office of the advocate general": "office of the advocate general for scotland",
}

# Applied ONLY when looking up an officeholder, never when resolving slugs.
# DBIST has no officeholder row of its own; Jonathan Reynolds heads both it and
# DBT from 2026-07-20, so borrowing DBT's row gives correct attribution. Keeping
# this separate stops DBIST and DBT collapsing into one slug.
OFFICEHOLDER_ALIASES = {
    "department for business innovation science and trade":
        "department for business and trade",
}


def normalise_institution(name):
    """Reduce an institution name to a comparable key.

    GOV.UK writes 'Department for Environment, Food & Rural Affairs' where the
    guide's frozen list writes '...Food and Rural Affairs'. Both must reduce to
    the same key, so fold ampersands, drop punctuation, and apply known aliases
    where GOV.UK's official title differs from the canonical name entirely."""
    if not name:
        return ""
    key = name.lower().strip()
    key = key.replace("&", " and ")
    key = re.sub(r"[^\w\s]", " ", key)
    key = re.sub(r"\s+", " ", key).strip()
    return INSTITUTION_ALIASES.get(key, key)


def eligible_on(officeholders, institution, date_iso):
    """Which officeholder(s) held this institution on this date."""
    target = normalise_institution(institution)
    target = OFFICEHOLDER_ALIASES.get(target, target)
    out = []
    for r in officeholders:
        if normalise_institution(r["institution"]) != target:
            continue
        if r["start_date"] and date_iso < r["start_date"]:
            continue
        if r["end_date"] and date_iso > r["end_date"]:
            continue
        out.append(r["officeholder"])
    return out


# ---------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-01-01")
    ap.add_argument("--end", default="2026-07-31")
    ap.add_argument("--out", default="./harvest")
    ap.add_argument("--officeholders", default=None,
                    help="Path to officeholders_2026.csv (optional but recommended)")
    ap.add_argument("--only", default=None,
                    help="Substring of one department title, to pilot a single department")
    ap.add_argument("--allow-partial", action="store_true",
                    help="Proceed even if some departments cannot be resolved")
    args = ap.parse_args()

    os.makedirs(os.path.join(args.out, "documents"), exist_ok=True)

    departments, unresolved = resolve_departments()
    if not departments:
        sys.exit("Could not fetch the department list. Check network access to gov.uk.")
    if args.only:
        departments = [d for d in departments
                       if args.only.lower() in d["canonical"].lower()]

    print("Departments resolved: %d of %d canonical"
          % (len(departments), len(CANONICAL_UK_DEPARTMENTS)))
    for d in departments:
        note = "  [CLOSED ORG]" if d["state"] == "closed" else ""
        print("  %-56s %s%s" % (d["canonical"][:56], ", ".join(d["slugs"]), note))
    if unresolved:
        print("\n  !! Could not resolve a GOV.UK slug for:")
        for name in unresolved:
            print("       %s" % name)
        if not args.allow_partial:
            sys.exit("\nStopping: %d department(s) unresolved. A partial harvest\n"
                     "would look complete downstream. Fix the names, or pass\n"
                     "--allow-partial if you intend to proceed anyway."
                     % len(unresolved))
        print("     Proceeding anyway (--allow-partial).\n")

    officeholders = load_officeholders(args.officeholders) if args.officeholders else []

    # Fail fast: check every department resolves to an officeholder before
    # spending an hour downloading. An unmatched name silently produces a
    # department with no eligible speaker and therefore no observations.
    if officeholders:
        csv_keys = {normalise_institution(o["institution"]) for o in officeholders}

        def _oh_key(name):
            k = normalise_institution(name)
            return OFFICEHOLDER_ALIASES.get(k, k)

        unmatched = [d for d in departments if _oh_key(d["canonical"]) not in csv_keys]
        print("\nOfficeholder coverage: %d of %d departments matched"
              % (len(departments) - len(unmatched), len(departments)))
        if unmatched:
            print("\n  !! NO OFFICEHOLDER RECORD FOR THESE -- they will produce")
            print("     no eligible speakers. Add an alias to INSTITUTION_ALIASES")
            print("     or a row to the CSV before running the full harvest.\n")
            for d in unmatched:
                print("       %s" % d["title"])
            unused = csv_keys - {_oh_key(d["canonical"]) for d in departments}
            if unused:
                print("\n     Unmatched CSV institution names (possible near-misses):")
                for u in sorted(unused):
                    print("       %s" % u)
            print("")

    log_path = os.path.join(args.out, "screening_log.csv")
    fields = ["institution", "govuk_slug", "document_title", "govuk_document_type",
              "normalised_document_type", "date", "url", "linked_speakers",
              "expected_officeholder", "speaker_match", "word_count",
              "text_file", "retrieval_date", "exclusion_reason"]

    retrieval_date = time.strftime("%Y-%m-%d")
    n_docs = 0

    with open(log_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()

        for dept in departments:
            hits, seen_links = [], set()
            for slug in dept.get("slugs") or [dept["slug"]]:
                for h in search_documents(slug, args.start, args.end,
                                          DOC_TYPE_MAP.keys()):
                    if h.get("link") and h["link"] not in seen_links:
                        seen_links.add(h["link"])
                        hits.append(h)
            variants = ("  (%d slugs)" % len(dept.get("slugs") or [])
                        if len(dept.get("slugs") or []) > 1 else "")
            print("%-55s %4d documents%s"
                  % (dept["canonical"][:55], len(hits), variants))

            # Section 5 requires a zero to be distinguishable from a department
            # that was never checked. Without this row, a silent department
            # simply vanishes from the log and from every downstream report.
            if not hits:
                writer.writerow({
                    "institution": dept["canonical"], "govuk_slug": dept["slug"],
                    "document_title": "", "govuk_document_type": "",
                    "normalised_document_type": "", "date": "", "url": "",
                    "linked_speakers": "", "expected_officeholder": "",
                    "speaker_match": "", "word_count": 0, "text_file": "",
                    "retrieval_date": retrieval_date,
                    "exclusion_reason": "no_documents_in_window",
                })
                fh.flush()

            for hit in hits:
                link = hit.get("link", "")
                if not link.startswith("/"):
                    continue
                date_iso = (hit.get("public_timestamp") or "")[:10]
                gov_type = hit.get("content_store_document_type", "")

                content = fetch_content(link)
                time.sleep(0.3)

                if content is None:
                    writer.writerow({
                        "institution": dept["canonical"], "govuk_slug": dept["slug"],
                        "document_title": hit.get("title", ""),
                        "govuk_document_type": gov_type,
                        "normalised_document_type": DOC_TYPE_MAP.get(gov_type, "other"),
                        "date": date_iso,
                        "url": "https://www.gov.uk" + link,
                        "linked_speakers": "", "expected_officeholder": "",
                        "speaker_match": "", "word_count": 0, "text_file": "",
                        "retrieval_date": retrieval_date,
                        "exclusion_reason": "content_api_unreachable",
                    })
                    continue

                speakers = extract_speakers(content)
                text = body_text(content)
                expected = eligible_on(officeholders, dept["canonical"], date_iso)

                # Attribution: an explicit GOV.UK speaker link is strong evidence.
                # Otherwise fall back to whether the officeholder's surname appears
                # in the body -- weak, and flagged as such for human triage.
                if speakers and expected:
                    match = "linked" if any(
                        names_match(s, e) for s in speakers for e in expected
                    ) else "linked_mismatch"
                elif expected and any(
                    normalise_name(e) and normalise_name(e)[-1] in text.lower()
                    for e in expected
                ):
                    match = "name_in_body"
                elif expected:
                    match = "no_match"
                else:
                    match = "no_officeholder_record"

                slug = re.sub(r"[^a-z0-9]+", "-", link.strip("/").lower())[:120]
                fname = os.path.join("documents", "%s__%s.txt" % (date_iso, slug))
                with open(os.path.join(args.out, fname), "w", encoding="utf-8") as tf:
                    tf.write("TITLE: %s\n" % hit.get("title", ""))
                    tf.write("URL: https://www.gov.uk%s\n" % link)
                    tf.write("DATE: %s\n" % date_iso)
                    tf.write("GOVUK_TYPE: %s\n" % gov_type)
                    tf.write("LINKED_SPEAKERS: %s\n" % "; ".join(speakers))
                    tf.write("\n---\n\n")
                    tf.write(text)

                writer.writerow({
                    "institution": dept["canonical"], "govuk_slug": dept["slug"],
                    "document_title": hit.get("title", ""),
                    "govuk_document_type": gov_type,
                    "normalised_document_type": DOC_TYPE_MAP.get(gov_type, "other"),
                    "date": date_iso,
                    "url": "https://www.gov.uk" + link,
                    "linked_speakers": "; ".join(speakers),
                    "expected_officeholder": "; ".join(expected),
                    "speaker_match": match,
                    "word_count": len(text.split()),
                    "text_file": fname,
                    "retrieval_date": retrieval_date,
                    "exclusion_reason": "",
                })
                n_docs += 1
                fh.flush()

    print("\nDone. %d documents written." % n_docs)
    print("Screening log: %s" % log_path)


if __name__ == "__main__":
    main()
