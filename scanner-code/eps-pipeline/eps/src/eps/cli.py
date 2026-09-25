"""Command line interface.

    eps fetch-jel

    # either supply your own documents...
    eps ingest --dir docs/ --write-template manifest.csv
    eps ingest --run-dir runs/dfe --manifest manifest.csv

    # ...or harvest them
    eps harvest --run-dir runs/dfe --country UK \
                --institution "Department for Education" \
                --start 2026-01-01 --end 2026-07-31
    eps extract --run-dir runs/dfe
    eps build   --run-dir runs/dfe            # --skip-intention: no model call

    # re-tag intentions on an existing run, without re-extracting
    eps tag-intention --run-dir runs/dfe

Harvest, extract and build are separate commands on purpose: the corpus is
frozen after harvest, model calls are cached after extract, and build can then
be re-run as often as you like, offline and for free.
"""

from __future__ import annotations

import argparse
import json
import pickle
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from .extract import DEFAULT_MODEL, IDENTITY_MODES, Extractor, ResponseCache
from .providers import PROVIDERS, ProviderStopped, get_provider
from .validate import resolve_speaker
from .harvest.govuk import GovUKHarvester
from .harvest.local import (
    IngestError, MANIFEST_COLUMNS, SUPPORTED, ingest_manifest, write_template,
)
from .harvest.store import RawStore
from .harvest.us import USHarvester, USSource
from .jel import fetch_from_aea, write_csv
from .pipeline import (
    REFERENCE_DIR, build, load_documents, load_institutions, load_officeholders,
    load_taxonomy, save_documents,
)


def _date(s: str) -> date:
    return date.fromisoformat(s)


def cmd_fetch_jel(args) -> int:
    codes = fetch_from_aea()
    if not codes:
        print("No codes parsed. Inspect the AEA page markup.", file=sys.stderr)
        return 1
    out = Path(args.out or REFERENCE_DIR / "jel_codes.csv")
    write_csv(codes, out)
    levels = {1: 0, 2: 0, 3: 0}
    for c in codes:
        levels[c.level] = levels.get(c.level, 0) + 1
    print(f"Wrote {len(codes)} codes to {out}")
    print(f"  majors {levels[1]}  subcategories {levels[2]}  detailed {levels[3]}")
    if levels[1] < 18 or levels[3] < 500:
        print("WARNING: looks short. Check the parser against the live page.",
              file=sys.stderr)
    return 0


def _load_us_sources(institution: str) -> list[USSource]:
    try:
        import yaml
    except ImportError:
        print("pyyaml not installed; US sources unavailable", file=sys.stderr)
        return []
    path = REFERENCE_DIR / "us_sources.yaml"
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return [
        USSource.from_dict(d) for d in data
        if d.get("institution", "").strip().lower() == institution.strip().lower()
    ]


def cmd_ingest(args) -> int:
    """Build a corpus from documents you supply, rather than by scraping."""
    if args.write_template:
        root = Path(args.dir or ".")
        if not root.is_dir():
            print(f"{root} is not a directory", file=sys.stderr)
            return 1
        paths = [p for p in root.rglob("*") if p.is_file()]
        n = write_template(paths, Path(args.write_template), country=args.country or "")
        print(f"Wrote a template for {n} files to {args.write_template}")
        print(f"Fill in: {', '.join(MANIFEST_COLUMNS[1:7])}")
        print(f"Supported types: {' '.join(sorted(SUPPORTED))}")
        if n == 0:
            print("No supported files found.", file=sys.stderr)
            return 1
        return 0

    if not args.manifest or not args.run_dir:
        print("give --manifest and --run-dir, or --dir with --write-template",
              file=sys.stderr)
        return 1

    run_dir = Path(args.run_dir)
    store = None if args.no_store else RawStore(run_dir / "raw")
    try:
        docs, errors = ingest_manifest(Path(args.manifest), store, strict=not args.lenient)
    except IngestError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    for e in errors:
        print(f"  ! {e}", file=sys.stderr)

    if not docs:
        print("No documents ingested.", file=sys.stderr)
        return 1

    save_documents(docs, run_dir / "documents.pkl")
    total_units = sum(len(d.units) for d in docs)
    selectable = sum(1 for d in docs for u in d.units if u.attributable)
    print(f"{len(docs)} documents, {total_units} units "
          f"({selectable} selectable) -> {run_dir / 'documents.pkl'}")
    by_type: dict[str, int] = {}
    for d in docs:
        by_type[d.doc_type] = by_type.get(d.doc_type, 0) + 1
    for t, n in sorted(by_type.items()):
        print(f"    {n:>4}  {t}")
    if errors:
        print(f"\n{len(errors)} row(s) skipped.", file=sys.stderr)
    return 0


def cmd_harvest(args) -> int:
    run_dir = Path(args.run_dir)
    store = RawStore(run_dir / "raw")
    wanted = {i.strip().lower() for i in (args.institution or [])}
    selected = [
        i for i in load_institutions()
        if (not args.country or i.country == args.country)
        and (not wanted or i.institution.lower() in wanted)
    ]
    if not selected:
        print("No institutions matched.", file=sys.stderr)
        return 1

    docs = []
    for inst in selected:
        if inst.country == "UK":
            if not inst.govuk_slug:
                print(f"skip {inst.institution}: no GOV.UK slug")
                continue
            h = GovUKHarvester(store)
            print(f"harvesting {inst.institution} ...", flush=True)
            n = 0
            for result in h.search(inst.govuk_slug, args.start, args.end):
                link = result.get("link", "")
                if not link.startswith("/"):
                    continue
                try:
                    doc = h.fetch(link, inst.institution)
                except Exception as exc:
                    print(f"  ! {link}: {exc}", file=sys.stderr)
                    continue
                if doc and doc.text.strip():
                    docs.append(doc)
                    n += 1
                if args.limit and n >= args.limit:
                    break
            print(f"  {n} documents")
        else:
            sources = _load_us_sources(inst.institution)
            if not sources:
                print(f"skip {inst.institution}: no entry in us_sources.yaml")
                continue
            h = USHarvester(store)
            for src in sources:
                print(f"harvesting {src.institution} <- {src.index_url}", flush=True)
                n = 0
                for url in h.enumerate_links(src):
                    try:
                        doc = h.fetch(url, src)
                    except Exception as exc:
                        print(f"  ! {url}: {exc}", file=sys.stderr)
                        continue
                    if not doc or not doc.text.strip():
                        continue
                    if not (args.start <= doc.pub_date <= args.end):
                        continue
                    docs.append(doc)
                    n += 1
                    if args.limit and n >= args.limit:
                        break
                print(f"  {n} documents")

    path = save_documents(docs, run_dir / "documents.pkl")
    print(f"\n{len(docs)} documents -> {path}")
    return 0


def cmd_extract(args) -> int:
    run_dir = Path(args.run_dir)
    docs = load_documents(run_dir / "documents.pkl")
    officeholders = load_officeholders()
    model = args.model or ({"mistral": "mistral-large-latest"}.get(args.provider) or DEFAULT_MODEL)
    provider = get_provider(args.provider, model)
    extractor = Extractor(
        load_taxonomy(), provider=provider, cache=ResponseCache(run_dir / "cache"),
        identity_mode=args.identity_mode,
    )
    print(f"provider={args.provider}  model={model}  identity_mode={args.identity_mode}")

    # RESUMING. Every model response is saved in run_dir/cache the moment it
    # arrives, keyed by its exact inputs. Re-running this command therefore
    # replays everything already paid for at no cost and only calls the API for
    # what is missing -- after running out of credit, a crash, Ctrl+C, or a
    # closed window. The status file is written as "incomplete" before the first
    # call, so a run killed outright is never mistaken for a finished one.
    status_path = run_dir / EXTRACT_STATUS
    _write_status(status_path, complete=False, state="running", model=model,
                  prompt_version=extractor.prompt_version, run_id=args.run_id,
                  documents=len(docs))

    results: dict[str, list] = {}
    skipped = 0
    failed_ids: list[str] = []
    stopped: tuple[str, str] | None = None
    try:
        for i, doc in enumerate(docs, 1):
            # A document with no attributable unit is not sent to the model.
            # Every line of it is marked "not selectable", and validation
            # rejects any observation built from a non-attributable unit, so
            # nothing the model could return would reach the dataset. In the US
            # and UK corpora that is 4,526 of 6,607 documents -- roughly half
            # the cost and two thirds of the running time, for identical results.
            if not any(u.attributable for u in doc.units):
                results[doc.doc_id] = []
                skipped += 1
                continue
            speaker, source, warning = resolve_speaker(doc, officeholders)
            if warning:
                print(f"  ! {warning}", file=sys.stderr)
            if speaker is None:
                results[doc.doc_id] = []
                continue
            try:
                results[doc.doc_id] = extractor.extract(doc, speaker, run_id=args.run_id)
            except ProviderStopped as exc:
                # Out of credit, spend limit, or a bad key: every remaining
                # document would fail the same way. Stop, and leave this
                # document unrecorded so the next run does it.
                stopped = (exc.reason, exc.detail)
                break
            except Exception as exc:
                # A failure specific to this document. Recorded as no candidates
                # so one bad page cannot stop a long run, and listed in the
                # status file so the run is not reported complete.
                print(f"  ! {doc.url}: {exc}", file=sys.stderr)
                results[doc.doc_id] = []
                failed_ids.append(doc.doc_id)
            if i % 10 == 0:
                print(f"  {i}/{len(docs)}", flush=True)
    except KeyboardInterrupt:
        stopped = ("interrupted", "stopped with Ctrl+C")

    remaining = [d.doc_id for d in docs if d.doc_id not in results]
    complete = stopped is None and not failed_ids
    with open(run_dir / "extractions.pkl", "wb") as fh:
        pickle.dump(results, fh)
    _write_status(status_path, complete=complete,
                  state="complete" if complete else ("stopped" if stopped else "finished with failures"),
                  stopped_reason=stopped[0] if stopped else None,
                  stopped_detail=(stopped[1][:500] if stopped else None),
                  model=model, prompt_version=extractor.prompt_version,
                  run_id=args.run_id, documents=len(docs),
                  documents_done=len(results) - len(failed_ids),
                  remaining_doc_ids=remaining, failed_doc_ids=failed_ids)

    print(f"{sum(len(v) for v in results.values())} candidates from {len(results)} of "
          f"{len(docs)} docs ({skipped} skipped, nothing selectable; "
          f"{len(failed_ids)} FAILED)")
    if stopped:
        print(f"\nRUN STOPPED: {stopped[0]}", file=sys.stderr)
        print(f"  {stopped[1][:300]}", file=sys.stderr)
        print(f"  {len(docs) - len(remaining):,} of {len(docs):,} documents done; "
              f"{len(remaining):,} remaining. Progress is saved.", file=sys.stderr)
        print("  To continue: fix the cause (e.g. top up credit), set the key "
              "again, and re-run this same command. Documents already done are "
              "replayed from saved responses at no cost.", file=sys.stderr)
    elif failed_ids:
        print(f"  !! {len(failed_ids)} document(s) failed. Re-run the same command "
              f"to retry only these.", file=sys.stderr)

    # The API's own token counts for this run (responses replayed from the local
    # cache cost nothing and do not appear). `cache read` should dwarf `cache
    # write`: if it is zero while classification calls were made, prompt caching
    # is broken and the run is costing several times what it should.
    usage = getattr(provider, "usage", None)
    if usage and usage.get("calls"):
        print(f"api calls {usage['calls']}: input {usage['input_tokens']:,}  "
              f"cache write {usage['cache_creation_input_tokens']:,}  "
              f"cache read {usage['cache_read_input_tokens']:,}  "
              f"output {usage['output_tokens']:,} tokens")
        cost = provider.cost_usd() if hasattr(provider, "cost_usd") else None
        if cost is not None:
            print(f"cost of this run: ${cost:,.2f}")
    if stopped:
        return 3
    return 2 if failed_ids else 0


#: Written by `extract` in the run directory; read by `build`.
EXTRACT_STATUS = "extract_status.json"


def _write_status(path: Path, **fields) -> None:
    fields["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path.write_text(json.dumps(fields, indent=2), encoding="utf-8")


def _extract_is_usable(run_dir: Path, allow_incomplete: bool) -> bool:
    """A dataset built from an unfinished extract looks exactly like a finished
    one with fewer quotes, so it is refused unless asked for explicitly."""
    status_path = run_dir / EXTRACT_STATUS
    if status_path.exists():
        status = json.loads(status_path.read_text(encoding="utf-8"))
        if not status.get("complete"):
            left = len(status.get("remaining_doc_ids") or [])
            bad = len(status.get("failed_doc_ids") or [])
            why = status.get("stopped_reason") or status.get("state")
            print(f"The extract for {run_dir} is not complete ({why}; "
                  f"{left:,} documents not done, {bad:,} failed).", file=sys.stderr)
            if not allow_incomplete:
                print("Re-run the same extract command to finish it, or pass "
                      "--allow-incomplete to build a partial dataset anyway.",
                      file=sys.stderr)
                return False
            print("Building a PARTIAL dataset, as requested.", file=sys.stderr)
    return True


def _load_extractions(run_dir: Path) -> dict:
    ext_path = run_dir / "extractions.pkl"
    if not ext_path.exists():
        return {}
    with open(ext_path, "rb") as fh:
        return pickle.load(fh)


def _intention_tagger(run_dir: Path, provider_name: str = "anthropic",
                      model: str | None = None):
    """The tagger, on extraction's default provider and model unless told
    otherwise, caching into the run's own cache like every other model step."""
    import os

    from .intention import IntentionTagger

    model = model or ({"mistral": "mistral-large-latest"}.get(provider_name)
                      or DEFAULT_MODEL)
    if provider_name == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
        print("  ! ANTHROPIC_API_KEY is not set: only intention tags already in "
              "the cache can be replayed; any other quote will be 'Not tagged' "
              "(provider_error). Set the key, or pass --skip-intention.",
              file=sys.stderr)
    return IntentionTagger(provider=get_provider(provider_name, model),
                           cache=ResponseCache(run_dir / "cache"))


def _print_intention(summary: dict) -> None:
    if summary.get("status") == "skipped":
        print("intention  skipped (--skip-intention): columns left blank")
        return
    print(f"intention  {summary['tagged']} tagged, {summary['not_tagged']} not tagged, "
          f"{summary['unclear']} unclear  "
          f"(prompt {summary['prompt_version']}, model {summary['model']})")
    for reason, n in summary["failure_reasons"].items():
        print(f"    {n:>4}  {reason}")


def cmd_build(args) -> int:
    run_dir = Path(args.run_dir)
    if not _extract_is_usable(run_dir, args.allow_incomplete):
        return 2

    docs = load_documents(run_dir / "documents.pkl")
    extractions = _load_extractions(run_dir)
    tagger = None if args.skip_intention else _intention_tagger(run_dir)

    summary = build(
        docs, extractions, load_taxonomy(), load_officeholders(),
        run_dir / "out", run_id=args.run_id,
        min_quote_chars=args.min_quote_chars,
        max_quote_chars=args.max_quote_chars,
        intention_tagger=tagger,
    )
    for src, n in summary.get("speaker_sources", {}).items():
        print(f"speaker from {src}: {n} document(s)")
    for w in summary.get("speaker_warnings", []):
        print(f"  ! {w['warning']}", file=sys.stderr)
    print(f"screened   {summary['documents_screened']}")
    print(f"kept       {summary['observations_kept']}")
    print(f"rejected   {summary['observations_rejected']}")
    for reason, n in summary["reject_reasons"].items():
        print(f"    {n:>4}  {reason}")
    _print_intention(summary["intention"])
    print(f"\n-> {summary['files']['dataset']}")
    return 0


def _load_context_log(path: Path) -> dict[str, str]:
    """quote_id -> quote_in_context from a context stage's log, if there is one."""
    if not path.exists():
        return {}
    import csv

    with open(path, newline="", encoding="utf-8") as fh:
        return {r["quote_id"]: r["quote_in_context"] for r in csv.DictReader(fh)}


def _released_quotes(path: Path) -> list[tuple[str, str]]:
    import csv

    with open(path, newline="", encoding="utf-8") as fh:
        return sorted((r["url"], r["direct_quote"]) for r in csv.DictReader(fh))


def cmd_tag_intention(args) -> int:
    """Re-tag an existing run's kept quotes without re-extracting.

    Rebuilds from the run's stored documents and extractions, with the context
    stage's `quote_in_context` joined back in from `out/context_log.csv`, so the
    release it writes is the existing one plus the three intention columns.
    """
    from .intention import write_trial_files

    run_dir = Path(args.run_dir)
    if not _extract_is_usable(run_dir, args.allow_incomplete):
        return 2
    out_dir = Path(args.out_dir) if args.out_dir else run_dir / "out"
    previous = run_dir / "out" / "dataset.csv"
    before = _released_quotes(previous) if previous.exists() else None

    docs = load_documents(run_dir / "documents.pkl")
    context = _load_context_log(run_dir / "out" / "context_log.csv")
    tagger = _intention_tagger(run_dir, args.provider, args.model)
    print(f"tagging with provider={args.provider}  model={tagger.model}  "
          f"prompt={tagger.prompt_version} ({tagger.fingerprint})")

    summary = build(
        docs, _load_extractions(run_dir), load_taxonomy(), load_officeholders(),
        out_dir, run_id=args.run_id,
        min_quote_chars=args.min_quote_chars,
        max_quote_chars=args.max_quote_chars,
        context=context or None,
        intention_tagger=tagger,
    )
    print(f"kept       {summary['observations_kept']}"
          f"{'  (context joined from context_log.csv)' if context else ''}")
    _print_intention(summary["intention"])

    # Tagging must never add or remove a quote. The rebuild is deterministic,
    # so any difference from the existing release means the inputs changed.
    if before is not None and _released_quotes(Path(summary["files"]["dataset"])) != before:
        print(f"  ! the rebuilt quotes differ from {previous}: check that the "
              "run's inputs and the --min/--max-quote-chars settings match the "
              "original build.", file=sys.stderr)

    if args.trial_files:
        for path in write_trial_files(out_dir).values():
            print(f"-> {path}")
    print(f"\n-> {summary['files']['dataset']}")
    print(f"-> {summary['files']['intention_log']}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="eps", description="Economics policy statements pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("fetch-jel", help="rebuild the JEL taxonomy from AEA")
    q.add_argument("--out")
    q.set_defaults(func=cmd_fetch_jel)

    q = sub.add_parser("ingest", help="build a corpus from your own files")
    q.add_argument("--run-dir")
    q.add_argument("--manifest", help="CSV describing the documents")
    q.add_argument("--dir", help="folder to scaffold a manifest from")
    q.add_argument("--write-template", metavar="CSV",
                   help="write a manifest template for --dir and exit")
    q.add_argument("--country", choices=["UK", "US"],
                   help="prefill the country column in the template")
    q.add_argument("--lenient", action="store_true",
                   help="skip bad rows instead of failing")
    q.add_argument("--no-store", action="store_true",
                   help="do not copy source files into the run's raw store")
    q.set_defaults(func=cmd_ingest)

    q = sub.add_parser("harvest", help="download documents (no model involved)")
    q.add_argument("--run-dir", required=True)
    q.add_argument("--country", choices=["UK", "US"])
    q.add_argument("--institution", action="append")
    q.add_argument("--start", type=_date, required=True)
    q.add_argument("--end", type=_date, required=True)
    q.add_argument("--limit", type=int, default=0)
    q.set_defaults(func=cmd_harvest)

    q = sub.add_parser("extract", help="run the model over the frozen corpus")
    q.add_argument("--run-dir", required=True)
    q.add_argument("--provider", choices=list(PROVIDERS), default="anthropic",
                   help="which API to call")
    q.add_argument("--model", default=None,
                   help="override the default model for the chosen provider")
    q.add_argument("--identity-mode", choices=list(IDENTITY_MODES), default="blind",
                   help="whether the model is told the speaker and institution")
    q.add_argument("--run-id", default="")
    q.set_defaults(func=cmd_extract)

    q = sub.add_parser("build", help="validate and write output tables")
    q.add_argument("--run-dir", required=True)
    q.add_argument("--run-id", default="")
    q.add_argument("--min-quote-chars", type=int, default=None)
    q.add_argument("--max-quote-chars", type=int, default=None)
    q.add_argument("--allow-incomplete", action="store_true",
                   help="build even though the extract stopped or had failures")
    q.add_argument("--skip-intention", action="store_true",
                   help="do not tag intentions; the three columns are left blank")
    q.set_defaults(func=cmd_build)

    q = sub.add_parser("tag-intention",
                       help="re-tag an existing run's quotes (no re-extraction)")
    q.add_argument("--run-dir", required=True)
    q.add_argument("--out-dir", default=None,
                   help="where to write the rebuilt release (default: RUN_DIR/out)")
    q.add_argument("--provider", choices=list(PROVIDERS), default="anthropic",
                   help="which API to call")
    q.add_argument("--model", default=None,
                   help="override the default model for the chosen provider")
    q.add_argument("--run-id", default="")
    q.add_argument("--min-quote-chars", type=int, default=None)
    q.add_argument("--max-quote-chars", type=int, default=None)
    q.add_argument("--allow-incomplete", action="store_true",
                   help="tag even though the extract stopped or had failures")
    q.add_argument("--trial-files", action="store_true",
                   help="also write the label counts, failures and review sample")
    q.set_defaults(func=cmd_tag_intention)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
