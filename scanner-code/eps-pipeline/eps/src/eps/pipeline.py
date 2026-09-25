"""Orchestration.

Stage boundaries are deliberate and the corpus is frozen between them:

  harvest  ->  raw/                (bytes + manifest, no model involved)
  extract  ->  cache/ + docs       (a model stage, cached by input hash)
  context  ->  out/context_log.csv (a model stage, cached by input hash)
  build    ->  out/                (validation + assembly, fully deterministic)

`build` can be re-run any number of times without touching the network or a
model, which is what makes iterating on the validators cheap. `context` is a
stage of its own rather than part of `build` for exactly that reason: it calls
a model, and folding it into `build` would cost that property. It writes its
decisions to a file, and `build` joins them in by quote ID.

Intention tagging (intention.py) is the exception: the brief places it inside
`build`, on the final kept rows. Its responses go through the run's cache, so
a re-build replays them offline and for free once they exist; `--skip-intention`
restores a build that makes no model call at all.
"""

from __future__ import annotations

import csv
import json
import os
import pickle
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Optional

from .assemble import (
    apply_intentions, observation_row, write_context_log, write_dataset,
    write_reject_log, write_screening_log,
)
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


# --- context ---------------------------------------------------------------


def run_context(
    documents: list[Document],
    extractions: dict[str, list],
    contextualiser,
    officeholders: OfficeholderTable,
    out_dir: str | Path,
    min_quote_chars: int | None = None,
    max_quote_chars: int | None = None,
) -> tuple[dict[str, str], dict]:
    """Add editorial context to the quotes that will reach the dataset.

    Runs over exactly the rows `build` would keep, so a quote that validation
    rejects is never paid for. Returns (quote_id -> quote_in_context, summary)
    and writes `context_log.csv`; `build` joins the mapping in by quote ID.
    """
    from .context import Status, summarise

    rows = _kept_rows(documents, extractions, officeholders,
                      min_quote_chars, max_quote_chars)
    results = contextualiser.run(rows, documents)

    if len(results) != len(rows):  # pragma: no cover - defended, never seen
        raise RuntimeError(
            f"context stage returned {len(results)} rows for {len(rows)} in"
        )

    write_context_log(results, out_dir)
    mapping = {r.quote_id: r.quote_in_context for r in results}
    summary = {
        "rows_in": len(rows),
        "rows_out": len(results),
        "by_status": summarise(results),
        "resolved": sum(1 for r in results if r.final_status == Status.RESOLVED),
    }
    return mapping, summary


def _kept_rows(documents, extractions, officeholders,
               min_quote_chars=None, max_quote_chars=None) -> list[dict]:
    """The validated rows `build` would write, without writing them."""
    active = load_active_codes()
    kwargs = {}
    if min_quote_chars is not None:
        kwargs["min_chars"] = min_quote_chars
    if max_quote_chars is not None:
        kwargs["max_chars"] = max_quote_chars

    rows: list[dict] = []
    for doc in documents:
        validated, speaker, speaker_source, _ = validate_observations(
            doc, extractions.get(doc.doc_id, []), active, officeholders, **kwargs
        )
        for obs in validated:
            if obs.valid:
                rows.append(observation_row(doc, obs, speaker or "", speaker_source))
    return rows


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
    context: dict[str, str] | None = None,
    intention_tagger=None,
) -> dict:
    """Validate extracted observations and write all output tables.

    `extractions` maps doc_id -> list[Observation]. Documents with no entry are
    still logged, so a genuine zero is distinguishable from a document that was
    never processed.

    `context` maps quote_id -> quote_in_context, from `run_context`. When it
    is omitted, the context stage's log in `out_dir` (`context_log.csv`) is
    read instead, so a re-build keeps the context already added. With neither,
    every `quote_in_context` equals its `direct_quote`, which is what the
    column means when no context was added, and a warning says so.

    `intention_tagger` is an `intention.IntentionTagger`. It is the one model
    step inside `build`: it runs on the final kept rows, after context is
    joined, and its responses go through the run's cache, so a re-build replays
    them instead of calling again. None skips tagging — the intention column
    is then blank and summary.json says so. The CLI passes a tagger unless
    told `--skip-intention`.
    """
    if intention_tagger is not None:
        _warn_if_no_key(intention_tagger)
    context_source = "given"
    if context is None:
        context = load_context_log(Path(out_dir) / CONTEXT_LOG)
        context_source = CONTEXT_LOG
        if context is None:
            print(f"  ! quote_in_context not joined: {CONTEXT_LOG} not found "
                  "for this run", file=sys.stderr)
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

    context_summary = {"source": context_source if context is not None else "none",
                       "unmatched": join_context(rows, context)}
    if context is not None and context_summary["unmatched"]:
        print(f"  ! quote_in_context: {context_summary['unmatched']} kept quote(s) "
              f"have no row in the context log; their plain quote is kept",
              file=sys.stderr)

    intention = tag_intentions(rows, documents, intention_tagger, out_dir)
    _print_not_tagged(intention)

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
        "context": context_summary,
        "intention": intention,
        "files": {
            "dataset": str(release),
            "internal": str(internal),
            "screening_log": str(log),
            "rejected": str(rej),
            "intention_log": str(Path(out_dir, "intention_log.jsonl")),
        },
    }
    Path(out_dir, "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return summary


#: Written by the context stage beside the release; read back by `build`.
CONTEXT_LOG = "context_log.csv"


def load_context_log(path: str | Path) -> dict[str, str] | None:
    """quote_id -> quote_in_context from a context stage's log, or None when
    the run has no log. Shared by `build` and `eps tag-intention`."""
    path = Path(path)
    if not path.exists():
        return None
    with open(path, newline="", encoding="utf-8") as fh:
        return {r["quote_id"]: r["quote_in_context"] for r in csv.DictReader(fh)}


def join_context(rows: list[dict], context: dict[str, str] | None) -> int:
    """Set each row's quote_in_context from `context`, keyed on quote ID.

    A row with no entry keeps its plain quote. Returns how many rows that was,
    so a log that has drifted from the extraction shows up as a number rather
    than as quietly unannotated quotes. With no context at all, returns 0.
    """
    from .context import quote_id

    if context is None:
        return 0
    unmatched = 0
    for row in rows:
        value = context.get(quote_id(row))
        if value is None:
            unmatched += 1
        row["quote_in_context"] = value or row["direct_quote"]
    return unmatched


#: The environment variable each provider reads its key from.
PROVIDER_KEYS = {"anthropic": "ANTHROPIC_API_KEY", "mistral": "MISTRAL_API_KEY"}


def _warn_if_no_key(tagger) -> None:
    """Tagging without a key still works for answers already in the cache, so
    this warns rather than stopping the build."""
    var = PROVIDER_KEYS.get(getattr(tagger.provider, "name", ""))
    if var and not os.environ.get(var):
        print(f"  ! {var} is not set: intention answers already in the cache will "
              "replay, but any other quote will be recorded as 'Not tagged' "
              "(provider_error). Set the key, or pass --skip-intention to skip "
              "tagging.", file=sys.stderr)


def _print_not_tagged(summary: dict) -> None:
    if summary.get("status") != "tagged":
        return
    print(f"intention  Not tagged: {summary['not_tagged']} of {summary['quotes']}")
    for reason, n in summary["failure_reasons"].items():
        print(f"    {n:>4}  {reason}")


def tag_intentions(rows: list[dict], documents: list[Document], tagger,
                   out_dir: str | Path) -> dict:
    """Tag the kept rows in place and write `intention_log.jsonl`.

    Returns the summary recorded in summary.json. When `tagger` is None the
    columns are left blank and the log is written empty, so a log from an
    earlier build cannot be mistaken for this one's.
    """
    from .intention import summarise, write_intention_log

    if tagger is None:
        apply_intentions(rows, None)
        write_intention_log([], out_dir)
        return {"status": "skipped"}
    results = tagger.run(rows, documents)
    apply_intentions(rows, results)
    write_intention_log(results, out_dir)
    return summarise(results)


def _counts(values: Iterable[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))
