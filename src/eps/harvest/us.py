"""US agency harvester.

There is no federal equivalent of the GOV.UK APIs, so each agency needs a small
adapter. Rather than 24 bespoke scripts, adapters are declared as data in
reference/us_sources.yaml and driven by this module: give it a listing URL, a
CSS selector for the links, and selectors for the article title and body.

Adding an agency should mean adding a few lines of YAML, not writing code.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterator, Optional

import requests
from lxml import html as lxml_html

from ..models import DOC_TYPES, Document, sha256
from ..normalise import (
    SEGMENTER_VERSION, html_to_text, make_doc_id, mark_attribution, segment,
)
from .store import RawStore, canonical_url

_DATE_PATTERNS = [
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "%Y-%m-%d"),
    (re.compile(r"\b([A-Z][a-z]+ \d{1,2}, \d{4})\b"), "%B %d, %Y"),
    (re.compile(r"\b(\d{1,2} [A-Z][a-z]+ \d{4})\b"), "%d %B %Y"),
]

# Titles that signal prepared rather than delivered remarks.
_AS_PREPARED = re.compile(r"as\s+prepared\s+for\s+delivery|prepared\s+remarks", re.I)
_AS_DELIVERED = re.compile(r"as\s+delivered|transcript", re.I)


@dataclass
class USSource:
    institution: str
    index_url: str  # listing page, may contain {page}
    link_selector: str  # CSS selector for article links on the listing
    body_selector: str  # CSS selector for the article body
    title_selector: str = "h1"
    date_selector: str = ""  # optional; falls back to scanning the page
    doc_type: str = "press_release"
    max_pages: int = 20
    kind: str = "html"  # "html" or "rss"

    @classmethod
    def from_dict(cls, d: dict) -> "USSource":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


class USHarvester:
    def __init__(
        self,
        store: RawStore,
        session: Optional[requests.Session] = None,
        pause: float = 0.5,
    ):
        self.store = store
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "eps-harvester/0.1"})
        self.pause = pause

    def enumerate_links(self, src: USSource) -> Iterator[str]:
        seen: set[str] = set()
        for page in range(1, src.max_pages + 1):
            url = src.index_url.format(page=page) if "{page}" in src.index_url \
                else src.index_url
            resp = self.session.get(url, timeout=60)
            if resp.status_code != 200:
                return
            if src.kind == "rss":
                links = re.findall(r"<link>\s*([^<\s]+)\s*</link>", resp.text)
            else:
                tree = lxml_html.fromstring(resp.content)
                tree.make_links_absolute(url)
                links = [
                    a.get("href") for a in tree.cssselect(src.link_selector)
                    if a.get("href")
                ]
            new = [l for l in links if l not in seen]
            if not new:
                return
            for l in new:
                seen.add(l)
                yield l
            if "{page}" not in src.index_url:
                return
            time.sleep(self.pause)

    def fetch(self, url: str, src: USSource) -> Optional[Document]:
        resp = self.session.get(url, timeout=60)
        if resp.status_code != 200:
            return None
        raw = resp.content
        digest = self.store.put(
            url, raw,
            {"institution": src.institution, "source_index": src.index_url},
        )
        return self.build_document(raw, url, src, digest)

    @staticmethod
    def build_document(
        raw: bytes, url: str, src: USSource, raw_digest: str
    ) -> Optional[Document]:
        tree = lxml_html.fromstring(raw)

        body_nodes = tree.cssselect(src.body_selector)
        if not body_nodes:
            return None
        body_html = "".join(lxml_html.tostring(n, encoding="unicode")
                            for n in body_nodes)
        text = html_to_text(body_html)
        if not text.strip():
            return None

        title_nodes = tree.cssselect(src.title_selector)
        title = " ".join(title_nodes[0].text_content().split()) if title_nodes else ""

        pub_date = _extract_date(tree, src.date_selector)

        doc_type = src.doc_type if src.doc_type in DOC_TYPES else "other"
        canon = canonical_url(url)
        doc_id = make_doc_id(canon, raw_digest)
        units = mark_attribution(segment(text, doc_id), doc_type)

        haystack = f"{title} {text[:2000]}"
        if _AS_PREPARED.search(haystack):
            delivery = "as_prepared"
        elif _AS_DELIVERED.search(haystack):
            delivery = "as_delivered"
        else:
            delivery = "unknown"

        return Document(
            doc_id=doc_id,
            institution=src.institution,
            country="US",
            url=canon,
            title=title,
            doc_type=doc_type,
            pub_date=pub_date,
            delivery_status=delivery,
            raw_sha256=raw_digest,
            text_sha256=sha256(text),
            segmenter_version=SEGMENTER_VERSION,
            retrieved_at=datetime.now(timezone.utc),
            source_index=src.index_url,
            text=text,
            units=units,
        )


def _extract_date(tree, selector: str) -> date:
    candidates: list[str] = []
    if selector:
        candidates += [n.text_content() for n in tree.cssselect(selector)]
    for node in tree.cssselect("time"):
        candidates.append(node.get("datetime") or node.text_content())
    for name in ("article:published_time", "publishdate", "date", "DC.date"):
        for node in tree.cssselect(f'meta[property="{name}"], meta[name="{name}"]'):
            candidates.append(node.get("content") or "")
    candidates.append(tree.text_content()[:4000])

    for blob in candidates:
        if not blob:
            continue
        for pattern, fmt in _DATE_PATTERNS:
            m = pattern.search(blob)
            if not m:
                continue
            raw = m.group(0) if fmt != "%Y-%m-%d" else m.group(0)[:10]
            try:
                return datetime.strptime(raw, fmt).date()
            except ValueError:
                continue
    return date(1900, 1, 1)
