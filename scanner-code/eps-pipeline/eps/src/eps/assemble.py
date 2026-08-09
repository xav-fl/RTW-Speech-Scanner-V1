"""Assembly of output tables.

The internal schema is wide (JEL at three levels, provenance, reject reasons).
The Section 6 release is a *projection* of it, so the release format can change
without re-running anything. Rows are sorted on a fixed key so that a diff
between two runs shows real disagreement rather than ordering noise.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from .models import Document, Observation, ScreeningRow

# Section 6, minus the relevance score (deferred by design).
RELEASE_COLUMNS = [
    "agency",
    "speaker",
    "document_title",
    "document_type",
    "date",
    "url",
    "direct_quote",
    "economics_topics",
]

INTERNAL_COLUMNS = RELEASE_COLUMNS + [
    "country",
    "doc_id",
    "unit_ids",
    "anchor",
    "delivery_status",
    "speaker_source",
    "jel_primary_major", "jel_primary_major_title",
    "jel_primary_sub", "jel_primary_sub_title",
    "jel_primary_detailed", "jel_primary_detailed_title",
    "jel_secondary_1", "jel_secondary_1_title",
    "jel_secondary_2", "jel_secondary_2_title",
    "raw_sha256", "text_sha256", "segmenter_version",
    "provider", "model_id", "prompt_version", "prompt_sha", "identity_mode", "run_id",
    "model_reason",
]


def _topics(obs: Observation) -> str:
    """Semicolon-separated labels, most specific level available per Section 7."""
    labels = []
    for a in [obs.primary] + list(obs.secondary):
        if a.is_empty():
            continue
        for level in ("detailed", "sub", "major"):
            if getattr(a, f"{level}_code"):
                labels.append(a.fmt(level))
                break
    return "; ".join(labels)


def observation_row(doc: Document, obs: Observation, speaker: str,
                    speaker_source: str = "") -> dict:
    sec = list(obs.secondary) + [None, None]
    return {
        "agency": doc.institution,
        "speaker": speaker,
        "document_title": doc.title,
        "document_type": doc.doc_type,
        "date": doc.pub_date.isoformat(),
        "url": doc.url,
        "direct_quote": obs.quote,
        "economics_topics": _topics(obs),
        "country": doc.country,
        "doc_id": doc.doc_id,
        "unit_ids": " ".join(obs.unit_ids),
        "anchor": obs.anchor or "",
        "delivery_status": doc.delivery_status,
        "speaker_source": speaker_source,
        "jel_primary_major": obs.primary.major_code,
        "jel_primary_major_title": obs.primary.major_title,
        "jel_primary_sub": obs.primary.sub_code,
        "jel_primary_sub_title": obs.primary.sub_title,
        "jel_primary_detailed": obs.primary.detailed_code,
        "jel_primary_detailed_title": obs.primary.detailed_title,
        "jel_secondary_1": sec[0].sub_code if sec[0] else "",
        "jel_secondary_1_title": sec[0].sub_title if sec[0] else "",
        "jel_secondary_2": sec[1].sub_code if sec[1] else "",
        "jel_secondary_2_title": sec[1].sub_title if sec[1] else "",
        "raw_sha256": doc.raw_sha256,
        "text_sha256": doc.text_sha256,
        "segmenter_version": doc.segmenter_version,
        "provider": obs.provider,
        "model_id": obs.model_id,
        "prompt_version": obs.prompt_version,
        "prompt_sha": obs.prompt_sha,
        "identity_mode": obs.identity_mode,
        "run_id": obs.run_id,
        # Post-hoc justification, for human review only. Not evidence about
        # how the selection was actually made.
        "model_reason": obs.reason,
    }


SORT_KEY = ("country", "agency", "date", "url", "unit_ids")


def write_dataset(rows: Iterable[dict], out_dir: str | Path) -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows, key=lambda r: tuple(str(r.get(k, "")) for k in SORT_KEY))

    internal = out_dir / "observations_internal.csv"
    with open(internal, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=INTERNAL_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    release = out_dir / "dataset.csv"
    with open(release, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=RELEASE_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    return release, internal


def write_screening_log(rows: Iterable[ScreeningRow], out_dir: str | Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "screening_log.csv"
    rows = sorted(rows, key=lambda r: (r.country, r.institution, r.pub_date, r.url))
    fields = list(ScreeningRow.__dataclass_fields__)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({f: getattr(r, f) for f in fields})
    return path


def write_reject_log(rows: Iterable[dict], out_dir: str | Path) -> Path:
    """Rejected observations, with the rule that rejected them."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "rejected.csv"
    fields = ["doc_id", "url", "unit_ids", "anchor", "reject_reason",
              "model_reason", "provider", "model_id", "prompt_version", "prompt_sha",
              "identity_mode", "run_id"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return path
