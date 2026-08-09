"""GOV.UK harvester.

Two public APIs, no authentication:

  Search API   https://www.gov.uk/api/search.json  — enumerate documents by
               organisation, document type and publication date range.
  Content API  https://www.gov.uk/api/content/<path> — fetch one document as
               structured JSON, including a pre-rendered HTML body.

Using the Content API rather than scraping the rendered page gives stable
fields for title, publication date, document type and associated people, and
avoids parsing page furniture.
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timezone
from typing import Iterator, Optional

import requests

from ..models import Document, DOC_TYPES
from ..normalise import (
    SEGMENTER_VERSION, html_to_text, make_doc_id, mark_attribution, segment,
)
from ..models import sha256
from .store import RawStore, canonical_url

SEARCH_URL = "https://www.gov.uk/api/search.json"
CONTENT_URL = "https://www.gov.uk/api/content"
PAGE_SIZE = 200  # Search API allows more, but keep responses small and stable.

# GOV.UK content_store_document_type -> our normalised label (Section 4).
GOVUK_TYPE_MAP = {
    "speech": "speech",
    "authored_article": "op_ed",
    "written_statement": "statement",
    "oral_statement": "statement",
    "press_release": "press_release",
    "news_story": "press_release",
    "government_response": "statement",
    "correspondence": "letter",
    "open_letter": "letter",
    "transcript": "interview_transcript",
    "policy_paper": "other",
    "guidance": "other",
    "detailed_guide": "other",
    "consultation_outcome": "other",
}

DEFAULT_TYPES = [
    "speech", "authored_article", "written_statement", "oral_statement",
    "press_release", "news_story", "correspondence", "open_letter",
    "transcript",
]

# GOV.UK marks speeches with a delivery type; map to our recorded field.
DELIVERY_MAP = {
    "speech": "as_delivered",
    "transcript": "as_delivered",
    "written_statement_to_parliament": "as_prepared",
    "authored_article": "as_prepared",
    "speech_as_delivered": "as_delivered",
    "speech_as_prepared": "as_prepared",
}


class GovUKHarvester:
    def __init__(
        self,
        store: RawStore,
        session: Optional[requests.Session] = None,
        pause: float = 0.2,
    ):
        self.store = store
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "eps-harvester/0.1"})
        self.pause = pause

    # -- enumeration --------------------------------------------------------

    def search(
        self,
        organisation_slug: str,
        start: date,
        end: date,
        doc_types: Optional[list[str]] = None,
    ) -> Iterator[dict]:
        """Yield search results for one organisation and date window."""
        doc_types = doc_types or DEFAULT_TYPES
        offset = 0
        while True:
            params = [
                ("filter_organisations", organisation_slug),
                ("filter_public_timestamp",
                 f"from:{start.isoformat()},to:{end.isoformat()}"),
                ("count", str(PAGE_SIZE)),
                ("start", str(offset)),
                ("order", "-public_timestamp"),
                ("fields", "link"),
                ("fields", "title"),
                ("fields", "public_timestamp"),
                ("fields", "content_store_document_type"),
                ("fields", "organisations"),
                ("fields", "people"),
            ]
            for t in doc_types:
                params.append(("filter_content_store_document_type", t))

            resp = self.session.get(SEARCH_URL, params=params, timeout=60)
            resp.raise_for_status()
            payload = resp.json()
            results = payload.get("results", [])
            if not results:
                return
            for r in results:
                yield r
            offset += len(results)
            if offset >= int(payload.get("total", 0)):
                return
            time.sleep(self.pause)

    # -- fetching -----------------------------------------------------------

    def fetch(self, link: str, institution: str) -> Optional[Document]:
        """Fetch one document via the Content API and build a Document."""
        path = link if link.startswith("/") else "/" + link
        url = f"{CONTENT_URL}{path}"
        resp = self.session.get(url, timeout=60)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        raw = resp.content
        item = json.loads(raw.decode("utf-8"))

        digest = self.store.put(
            url, raw, {"institution": institution, "source_index": "govuk_content_api"}
        )
        return self.build_document(item, institution, digest, page_url=f"https://www.gov.uk{path}")

    # -- construction (pure, so it can be unit-tested from fixtures) --------

    @staticmethod
    def build_document(
        item: dict,
        institution: str,
        raw_digest: str,
        page_url: Optional[str] = None,
    ) -> Document:
        details = item.get("details", {}) or {}
        body = details.get("body") or ""
        if isinstance(body, list):  # some schemas return a list of renderings
            body = next(
                (b.get("content", "") for b in body
                 if b.get("content_type") == "text/html"),
                "",
            )

        text = html_to_text(body)
        govuk_type = item.get("document_type") or ""
        doc_type = GOVUK_TYPE_MAP.get(govuk_type, "other")
        if doc_type not in DOC_TYPES:
            doc_type = "other"

        pub = (
            item.get("first_published_at")
            or item.get("public_updated_at")
            or item.get("published_at")
            or ""
        )
        pub_date = _parse_date(pub)

        url = canonical_url(page_url or item.get("base_path", ""))
        doc_id = make_doc_id(url, raw_digest)

        units = mark_attribution(segment(text, doc_id), doc_type)

        speaker_hint = None
        people = ((item.get("links") or {}).get("people") or [])
        if people:
            speaker_hint = people[0].get("title")

        delivery = DELIVERY_MAP.get(
            details.get("delivery_type") or govuk_type, "unknown"
        )

        return Document(
            doc_id=doc_id,
            institution=institution,
            country="UK",
            url=url,
            title=item.get("title", ""),
            doc_type=doc_type,
            pub_date=pub_date,
            delivery_status=delivery,
            speaker_hint=speaker_hint,
            raw_sha256=raw_digest,
            text_sha256=sha256(text),
            segmenter_version=SEGMENTER_VERSION,
            retrieved_at=datetime.now(timezone.utc),
            source_index="govuk_content_api",
            text=text,
            units=units,
        )


def _parse_date(value: str) -> date:
    if not value:
        return date(1900, 1, 1)
    value = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
