"""Orchestration.

Stage boundaries are deliberate and the corpus is frozen between them:

  harvest  ->  raw/            (bytes + manifest, no model involved)
  extract  ->  cache/ + docs   (the only model stage, cached by input hash)
  build    ->  out/            (validation + assembly, fully deterministic)

`build` can be re-run any number of times without touching the network or a
model, which is what makes iterating on the validators cheap.
"""

from __future__ import annotations

import csv
import json
import pickle
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Optional

from .assemble import observation_row, write_dataset, write_reject_log, write_screening_log
from .jel import ACTIVE_CODES_FILE, ActiveJELList, JELTaxonomy
from .models import Document, ScreeningRow
from .validate import OfficeholderTable, validate_observations

REFERENCE_DIR = Path(__file__).parent / "reference"
# The dated JEL list sits outside the package with the other supplied reference
# data, and is versioned by filename rather than rebuilt.
DATA_REFERENCE_DIR = Path(__file__).parent.parent.parent / "data" / "reference"


@dataclass
class Institution:
    institution: str
    country: str
    govuk_slug: str = ""
    us_domain: str = ""


def load_institutions(path: Optional[Path] = None) -> list[Institution]:
    path = path or REFERENCE_DIR / "institutions.csv"
    with open(path, newline="", encoding="utf-8") as fh:
        return [
            Institution(
                institution=r["institution"].strip(),
                country=r["country"].strip(),
                govuk_slug=r.get("govuk_slug", "").strip(),
                us_domain=r.get("us_domain", "").strip(),
            )
            for r in csv.DictReader(fh)
        ]


def load_officeholders(path: Optional[Path] = None) -> OfficeholderTable:
    path = path or REFERENCE_DIR / "officeholders.csv"
    rows = []
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rows.append(
                {
                    "institution": r["institution"].strip(),
                    "person": r["person"].strip(),
                    "role": r.get("role", "").strip(),
                    "start_date": _d(r.get("start_date")),
                    "end_date": _d(r.get("end_date")),
                }
            )
    return OfficeholderTable(rows)


def load_taxonomy(path: Optional[Path] = None) -> JELTaxonomy:
    return JELTaxonomy.load(path or REFERENCE_DIR / "jel_codes.csv")


def load_active_codes(path: Optional[Path] = None) -> ActiveJELList:
    """The 845 active three-character codes the classifier selects from."""
    return ActiveJELList.load(path or DATA_REFERENCE_DIR / ACTIVE_CODES_FILE)


def _d(value: Optional[str]) -> Optional[date]:
    value = (value or "").strip()
    if not value:
        return None
    return date.fromisoformat(value)


# --- document persistence --------------------------------------------------


def save_documents(docs: Iterable[Document], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        pickle.dump(list(docs), fh)
    return path


def load_documents(path: str | Path) -> list[Document]:
    with open(path, "rb") as fh:
        return pickle.load(fh)


# --- build -----------------------------------------------------------------


def build(
    documents: list[Document],
    extractions: dict[str, list],
    taxonomy: JELTaxonomy,
    officeholders: OfficeholderTable,
    out_dir: str | Path,
    run_id: str = "",
    min_quote_chars: int | None = None,
    max_quote_chars: int | None = None,
) -> dict:
    """Validate extracted observations and write all output tables.

    `extractions` maps doc_id -> list[Observation]. Documents with no entry are
    still logged, so a genuine zero is distinguishable from a document that was
    never processed.
    """
    # `taxonomy` is still accepted for callers that pass it; JEL validation runs
    # against the dated active list.
    active = load_active_codes()

    rows: list[dict] = []
    rejects: list[dict] = []
    screening: list[ScreeningRow] = []
    warnings: list[dict] = []

    for doc in documents:
        obs_list = extractions.get(doc.doc_id, [])
        kwargs = {}
        if min_quote_chars is not None:
            kwargs["min_chars"] = min_quote_chars
        if max_quote_chars is not None:
            kwargs["max_chars"] = max_quote_chars
        validated, speaker, speaker_source, warning = validate_observations(
            doc, obs_list, active, officeholders, **kwargs
        )
        if warning:
            warnings.append({"doc_id": doc.doc_id, "url": doc.url, "warning": warning})

        kept = 0
        for obs in validated:
            if obs.valid:
                rows.append(observation_row(doc, obs, speaker or "", speaker_source))
                kept += 1
            else:
                rejects.append(
                    {
                        "doc_id": doc.doc_id,
                        "url": doc.url,
                        "unit_ids": " ".join(obs.unit_ids),
                        "anchor": obs.anchor or "",
                        "reject_reason": obs.reject_reason,
                        "model_reason": obs.reason,
                        "provider": obs.provider,
                        "model_id": obs.model_id,
                        "prompt_version": obs.prompt_version,
                        "prompt_sha": obs.prompt_sha,
                        "identity_mode": obs.identity_mode,
                        "run_id": obs.run_id or run_id,
                    }
                )

        exclusion = ""
        if speaker is None:
            exclusion = ("no speaker: add a row to officeholders.csv, or fill in "
                         "speaker_hint in the manifest")
        elif not obs_list:
            exclusion = "no qualifying passage"
        elif kept == 0:
            exclusion = "all candidate passages failed validation"

        screening.append(
            ScreeningRow(
                doc_id=doc.doc_id,
                institution=doc.institution,
                country=doc.country,
                url=doc.url,
                title=doc.title,
                doc_type=doc.doc_type,
                pub_date=doc.pub_date.isoformat(),
                speaker=speaker or "",
                speaker_source=speaker_source,
                eligible=speaker is not None,
                exclusion_reason=exclusion,
                n_observations=kept,
                retrieved_at=doc.retrieved_at.isoformat() if doc.retrieved_at else "",
                segmenter_version=doc.segmenter_version,
                prompt_version=obs_list[0].prompt_version if obs_list else "",
                model_id=obs_list[0].model_id if obs_list else "",
            )
        )

    release, internal = write_dataset(rows, out_dir)
    log = write_screening_log(screening, out_dir)
    rej = write_reject_log(rejects, out_dir)

    summary = {
        "documents_screened": len(documents),
        "documents_with_observations": sum(1 for s in screening if s.n_observations),
        "observations_kept": len(rows),
        "observations_rejected": len(rejects),
        "speaker_warnings": warnings,
        "speaker_sources": _counts(
            s.speaker_source for s in screening if s.speaker_source),
        "reject_reasons": _counts(r["reject_reason"] for r in rejects),
        "by_institution": _counts(r["agency"] for r in rows),
        "files": {
            "dataset": str(release),
            "internal": str(internal),
            "screening_log": str(log),
            "rejected": str(rej),
        },
    }
    Path(out_dir, "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return summary


def _counts(values: Iterable[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))
