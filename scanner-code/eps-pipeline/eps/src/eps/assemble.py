"""Assembly of output tables.

The internal schema is wide (JEL at three levels, provenance, reject reasons).
The Section 6 release is a *projection* of it, so the release format can change
without re-running anything -- the rolled-up JEL columns were added to the
release this way, from levels the internal table already held. Rows are sorted on a fixed key so that a diff
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
    # The same quote with bracketed editorial insertions naming referents it
    # leaves implicit ("Today's action [standardizing grant requirements]").
    # Equal to direct_quote wherever the context stage added nothing, so the
    # column is always readable on its own. See context.py.
    "quote_in_context",
    "economics_topics",
    "jel_major_categories",
    "jel_subcategories",
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
    "match_strength_1", "match_strength_2", "match_strength_3",
    "raw_sha256", "text_sha256", "segmenter_version",
    "provider", "model_id", "prompt_version", "prompt_sha", "identity_mode", "run_id",
    "model_reason",
    "model_mechanism",
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


def _topics_at(obs: Observation, level: str) -> str:
    """The same assignments rolled up to one level, code and AEA title.

    `economics_topics` gives whatever level the model reached, so a reader meets
    `I38` with no indication that it sits under welfare policy under health and
    education. These columns supply the parents. Repeats are dropped: two
    assignments under the same major say the major once, so the column reads as
    context rather than as a padded restatement of the codes.
    """
    labels = []
    for a in [obs.primary] + list(obs.secondary):
        label = a.fmt(level)
        if label and label not in labels:
            labels.append(label)
    return "; ".join(labels)


def observation_row(doc: Document, obs: Observation, speaker: str,
                    speaker_source: str = "",
                    quote_in_context: str | None = None) -> dict:
    """One output row. `quote_in_context` defaults to the quote unmodified, so
    a build that never ran the context stage still writes a usable column."""
    sec = list(obs.secondary) + [None, None]
    return {
        "agency": doc.institution,
        "speaker": speaker,
        "document_title": doc.title,
        "document_type": doc.doc_type,
        "date": doc.pub_date.isoformat(),
        "url": doc.url,
        "direct_quote": obs.quote,
        "quote_in_context": quote_in_context if quote_in_context else obs.quote,
        "economics_topics": _topics(obs),
        "jel_major_categories": _topics_at(obs, "major"),
        "jel_subcategories": _topics_at(obs, "sub"),
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
        # The three-character code, not its parent. These columns used to
        # record sub_code, so a reader saw `H5` where the classifier had said
        # `H54`; the parents are in jel_subcategories already.
        "jel_secondary_1": sec[0].detailed_code if sec[0] else "",
        "jel_secondary_1_title": sec[0].detailed_title if sec[0] else "",
        "jel_secondary_2": sec[1].detailed_code if sec[1] else "",
        "jel_secondary_2_title": sec[1].detailed_title if sec[1] else "",
        "match_strength_1": obs.primary.match_strength or "",
        "match_strength_2": sec[0].match_strength if sec[0] else "",
        "match_strength_3": sec[1].match_strength if sec[1] else "",
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
        # The phrase the model named before picking a code, on the same terms.
        "model_mechanism": obs.mechanism,
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


CONTEXT_LOG_COLUMNS = [
    "quote_id", "url", "final_status", "direct_quote", "quote_in_context",
    "triage_expressions", "anchors", "insertions", "evidence", "model_note",
    "warnings", "triage_prompt_version", "resolve_prompt_version", "model",
    "run_timestamp",
]


def write_context_log(rows: Iterable, out_dir: str | Path) -> Path:
    """One row per quote that entered the context stage, with its final status.

    The three parallel `anchors` / `insertions` / `evidence` columns are joined
    on ` | ` in the same order, so a reviewer can read an insertion against the
    passage that licensed it without opening the document.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "context_log.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CONTEXT_LOG_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({
                "quote_id": r.quote_id,
                "url": r.url,
                "final_status": r.final_status,
                "direct_quote": r.direct_quote,
                "quote_in_context": r.quote_in_context,
                "triage_expressions": " | ".join(r.triage_expressions),
                "anchors": " | ".join(i.anchor for i in r.insertions),
                "insertions": " | ".join(i.insertion for i in r.insertions),
                "evidence": " | ".join(i.evidence for i in r.insertions),
                "model_note": r.model_note,
                "warnings": " | ".join(r.warnings),
                "triage_prompt_version": r.triage_prompt_version,
                "resolve_prompt_version": r.resolve_prompt_version,
                "model": r.model,
                "run_timestamp": r.run_timestamp,
            })
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
