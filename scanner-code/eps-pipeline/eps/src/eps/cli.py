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
    eps build   --run-dir runs/dfe

Harvest, extract and build are separate commands on purpose: the corpus is
frozen after harvest, model calls are cached after extract, and build can then
be re-run as often as you like, offline and for free.
"""

from __future__ import annotations

import argparse
import pickle
import sys
from datetime import date
from pathlib import Path

from .extract import DEFAULT_MODEL, IDENTITY_MODES, Extractor, ResponseCache
from .providers import PROVIDERS, get_provider
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

    results: dict[str, list] = {}
    for i, doc in enumerate(docs, 1):
        speaker, source, warning = resolve_speaker(doc, officeholders)
        if warning:
            print(f"  ! {warning}", file=sys.stderr)
        if speaker is None:
            results[doc.doc_id] = []
            continue
        try:
            results[doc.doc_id] = extractor.extract(doc, speaker, run_id=args.run_id)
        except Exception as exc:
            print(f"  ! {doc.url}: {exc}", file=sys.stderr)
            results[doc.doc_id] = []
        if i % 10 == 0:
            print(f"  {i}/{len(docs)}", flush=True)

    with open(run_dir / "extractions.pkl", "wb") as fh:
        pickle.dump(results, fh)
    print(f"{sum(len(v) for v in results.values())} candidates from {len(docs)} docs")
    return 0


def cmd_build(args) -> int:
    run_dir = Path(args.run_dir)
    docs = load_documents(run_dir / "documents.pkl")
    ext_path = run_dir / "extractions.pkl"
    extractions = {}
    if ext_path.exists():
        with open(ext_path, "rb") as fh:
            extractions = pickle.load(fh)

    summary = build(
        docs, extractions, load_taxonomy(), load_officeholders(),
        run_dir / "out", run_id=args.run_id,
        min_quote_chars=args.min_quote_chars,
        max_quote_chars=args.max_quote_chars,
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
    print(f"\n-> {summary['files']['dataset']}")
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
    q.set_defaults(func=cmd_build)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
