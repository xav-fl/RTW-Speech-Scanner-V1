"""Run the extraction step of the eps pipeline through your Codex CLI.

    python run_extract.py --model <model> --effort <level>

Reads only this folder; writes only to output/. See README.md.

Every document gets its own result file in output/results/ the moment it is
finished, so the run can be stopped at any point and the same command picks up
where it left off: finished documents are skipped, failed ones are retried.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
RESULTS = OUTPUT / "results"
LOGS = OUTPUT / "logs"
SETTINGS = OUTPUT / "run_settings.json"
SUMMARY = OUTPUT / "run_summary.json"
CHECKSUMS = ROOT / "CHECKSUMS.sha256"
REFERENCE = ROOT / "reference_units.json"
HARVESTS = ROOT / "harvests" / "harvests.json"

#: A finished document; anything else is retried on the next run.
DONE = {"complete", "not_sent"}

EXIT_OK, EXIT_CHECK_FAILED, EXIT_FAILURES, EXIT_STOPPED = 0, 1, 2, 3

#: This many failed documents in a row means something is wrong with every
#: call (a mistyped model name, say), not with the documents: stop and say so
#: rather than record the same failure thousands of times.
MAX_CONSECUTIVE_FAILURES = 5


# --- small helpers ---------------------------------------------------------


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(message: str) -> None:
    print(message, flush=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    with open(LOGS / "run.log", "a", encoding="utf-8") as fh:
        fh.write(f"{now()}  {message}\n")


def stop(message: str, code: int = EXIT_CHECK_FAILED) -> "NoReturn":
    print("\n" + message, file=sys.stderr, flush=True)
    raise SystemExit(code)


def write_json(path: Path, data) -> None:
    """Write atomically: a crash leaves either the old file or the new one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --- the two start-up checks -----------------------------------------------


def check_checksums() -> None:
    if not CHECKSUMS.exists():
        stop("This folder is incomplete: CHECKSUMS.sha256 is missing.\n"
             "Unzip the bundle again into a new folder and run from there.")
    bad: list[str] = []
    for line in CHECKSUMS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, rel = line.split("  ", 1)
        path = ROOT / rel
        if not path.is_file():
            bad.append(f"missing: {rel}")
        elif sha256_file(path) != digest:
            bad.append(f"changed: {rel}")
    if bad:
        stop(f"{len(bad)} file(s) in this folder are missing or changed, for "
             f"example:\n  " + "\n  ".join(bad[:5]) +
             "\nUnzip the bundle again into a new, empty folder and run from "
             "there. Do not edit the files inside it.")


def check_codex_login(executable: str) -> None:
    try:
        result = subprocess.run([executable, "login", "status"],
                                capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        stop(f"Could not run Codex ({exc}).\n"
             "Install the Codex CLI (see README step 2), open a new terminal, "
             "and run the same command again.")
    if result.returncode != 0:
        stop("Codex says you are not signed in.\n"
             "Run:  codex login\n"
             "then run the same command again.")


# --- documents ---------------------------------------------------------------


def harvest_lists() -> list[dict]:
    return json.loads(HARVESTS.read_text(encoding="utf-8"))


def ingest(manifest: Path) -> list:
    """The documents a manifest names, built in memory exactly as `eps ingest`
    builds them. Paths in the manifest are relative to the manifest."""
    from eps.harvest.local import ingest_row, read_manifest, validate_row

    docs = []
    for row in read_manifest(manifest):
        row = dict(row)
        row["path"] = str((manifest.parent / row["path"]).resolve())
        problems = validate_row(row, 0)
        if problems:
            raise RuntimeError(f"{manifest.name}: {problems[0]}")
        docs.append(ingest_row(row, None))
    return docs


def unit_digest(doc) -> list:
    h = hashlib.sha256()
    for u in doc.units:
        h.update(f"{u.unit_id}\t{int(u.attributable)}\t{u.text}\n".encode("utf-8"))
    return [len(doc.units), sum(u.attributable for u in doc.units), h.hexdigest()[:16]]


def load_all() -> tuple[list[dict], dict]:
    """[(list name, [doc_id, ...])] in run order, and doc_id -> Document."""
    lists, docs = [], {}
    for entry in harvest_lists():
        ids = []
        for d in ingest(ROOT / "harvests" / entry["manifest"]):
            docs.setdefault(d.doc_id, d)
            ids.append(d.doc_id)
        lists.append({"name": entry["name"], "doc_ids": ids})
    return lists, docs


def check_against_reference(docs: dict) -> None:
    """Compare the documents built here with the ones built when the bundle
    was made. Differences are logged, never fatal."""
    if not REFERENCE.exists():
        log("ingest check: no reference file; skipped")
        return
    ref = json.loads(REFERENCE.read_text(encoding="utf-8"))
    mine = {doc_id: unit_digest(d) for doc_id, d in docs.items()}
    missing = sorted(set(ref) - set(mine))
    extra = sorted(set(mine) - set(ref))
    differ = sorted(k for k in set(ref) & set(mine) if ref[k] != mine[k])
    write_json(LOGS / "ingest_check.json",
               {"checked_at": now(), "documents": len(mine),
                "missing": missing, "extra": extra, "different_units": differ})
    if missing or extra or differ:
        log(f"ingest check: {len(missing)} missing, {len(extra)} unexpected and "
            f"{len(differ)} different document(s) against the reference "
            f"(details in output/logs/ingest_check.json); continuing")
    else:
        log(f"ingest check: all {len(mine)} documents match the reference")


# --- providers ---------------------------------------------------------------


def fake_codex(delay: float):
    """A stand-in for the `codex` program, for testing the bundle without
    Codex. It answers like Codex does, through the real provider code, and
    never selects anything a person would rely on."""
    def run(args, stdin_text, cwd, timeout):
        from eps import cli_schemas

        if args[1:] == ["--version"]:
            return 0, "fake-codex (bundle acceptance test)\n", ""
        time.sleep(delay)
        configs = [args[i + 1] for i, a in enumerate(args) if a == "-c"]
        instructions = next(c for c in configs
                            if c.startswith("model_instructions_file="))
        system = Path(instructions.split("=", 1)[1].strip("'")).read_text(encoding="utf-8")
        if cli_schemas.call_kind(system) == "select":
            ids = [line.split(":", 1)[0] for line in stdin_text.splitlines()
                   if ".P" in line.split(":", 1)[0] and "not selectable" not in line]
            answer = {"observations": [
                {"unit_ids": ids[:1], "anchor": None, "reason": "acceptance test"}]
                if ids else []}
        else:
            answer = {"mechanism": "acceptance test",
                      "codes": [{"code": "J24", "strength": 1}]}
        out = Path(args[args.index("-o") + 1])
        out.write_text(json.dumps(answer), encoding="utf-8")
        return 0, "", ""
    return run


def make_provider(args):
    from eps.providers import CodexCLIProvider

    if args.provider == "fake":
        p = CodexCLIProvider(model="fake", effort="low", timeout=args.timeout,
                             log_path=LOGS / "calls.jsonl",
                             executable="fake-codex", run=fake_codex(args.fake_delay))
        p.name = "fake-codex"
        return p
    return CodexCLIProvider(model=args.model, effort=args.effort,
                            timeout=args.timeout, log_path=LOGS / "calls.jsonl")


def save_prompt_snapshot(provider, list_name: str) -> None:
    """What Codex will send the model, as `codex debug prompt-input` reports
    it under the same settings. Best effort: a failure is logged, not fatal."""
    if provider.name != "codex":
        return
    from eps.extract import EXTRACT_SYSTEM

    instructions = provider.files / "instructions-snapshot.md"
    instructions.write_text(EXTRACT_SYSTEM, encoding="utf-8")
    cmd = [provider.executable,
           "-m", provider.model,
           "-c", f"model_reasoning_effort='{provider.effort}'",
           "-c", f"model_instructions_file='{instructions}'",
           "-c", "project_doc_max_bytes=0",
           "-c", "web_search='disabled'",
           "-c", "features.shell_tool=false",
           "-c", "features.multi_agent=false",
           "-c", "features.apps=false",
           "debug", "prompt-input", "(document text goes here)"]
    target = LOGS / f"prompt_input_{list_name}.txt"
    try:
        r = subprocess.run(cmd, cwd=provider.workdir, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=120)
        target.write_text(f"$ {' '.join(cmd)}\nexit {r.returncode}\n\n"
                          f"{r.stdout}\n--- stderr ---\n{r.stderr}", encoding="utf-8")
        log(f"prompt snapshot for {list_name}: exit {r.returncode} -> {target.name}")
    except Exception as exc:
        log(f"prompt snapshot for {list_name} failed ({exc}); continuing")


# --- settings guard ----------------------------------------------------------


def check_settings(provider) -> dict:
    from eps.extract import PROMPT_VERSION, prompt_fingerprint

    settings = {"provider": provider.name, "model": provider.model,
                "effort": provider.effort, "prompt_version": PROMPT_VERSION,
                "prompt_fingerprint": prompt_fingerprint()}
    if SETTINGS.exists():
        previous = json.loads(SETTINGS.read_text(encoding="utf-8"))
        keep = {k: previous.get(k) for k in settings}
        if keep != settings:
            changed = ", ".join(f"{k} was {keep[k]!r}, now {settings[k]!r}"
                                for k in settings if keep[k] != settings[k])
            stop("This folder already holds a run made with different settings "
                 f"({changed}).\nTo continue that run, use the same --model and "
                 "--effort as before. To start a new run instead, unzip the "
                 "bundle into a new folder.")
    else:
        write_json(SETTINGS, {**settings, "started_at": now()})
    return settings


# --- the run -----------------------------------------------------------------


def result_path(doc_id: str) -> Path:
    return RESULTS / f"{doc_id}.json"


def read_status(doc_id: str) -> str | None:
    p = result_path(doc_id)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8")).get("status")


def process(doc, list_name, extractor, provider, officeholders) -> dict:
    """Extract one document and return its result record. Raises
    ProviderStopped (signed out, usage limit) for the caller to stop on."""
    from eps.providers import CLICallFailed, ProviderStopped
    from eps.validate import resolve_speaker

    base = {"doc_id": doc.doc_id, "url": doc.url, "harvest": list_name,
            "provider": provider.name, "model": provider.model,
            "effort": provider.effort, "tool_version": provider.tool_version}
    if not any(u.attributable for u in doc.units):
        return {**base, "status": "not_sent", "reason": "nothing selectable",
                "observations": [], "finished_at": now()}
    speaker, _source, warning = resolve_speaker(doc, officeholders)
    if speaker is None:
        return {**base, "status": "not_sent", "reason": "no speaker",
                "detail": warning, "observations": [], "finished_at": now()}

    first_call = len(provider.call_log)
    provider.context = {"harvest": list_name, "doc_id": doc.doc_id}
    try:
        obs = extractor.extract(doc, speaker, run_id=f"codex-bundle:{list_name}")
    except ProviderStopped:
        raise
    except CLICallFailed as exc:
        return {**base, "status": "failed", "failure_class": exc.failure_class,
                "detail": exc.detail[:1000], "calls": provider.call_log[first_call:],
                "finished_at": now()}
    except Exception as exc:  # a bug, not a model failure: still named
        return {**base, "status": "failed", "failure_class": "internal_error",
                "detail": f"{type(exc).__name__}: {exc}"[:1000],
                "calls": provider.call_log[first_call:], "finished_at": now()}
    finally:
        provider.context = {}
    return {**base, "status": "complete", "speaker": speaker,
            "observations": [asdict(o) for o in obs],
            "calls": provider.call_log[first_call:], "finished_at": now()}


def summarise(lists: list[dict], stopped: str | None, attempted: int) -> dict:
    per_list = []
    for entry in lists:
        counts: dict[str, int] = {}
        for doc_id in entry["doc_ids"]:
            p = result_path(doc_id)
            if not p.exists():
                key = "not yet done"
            else:
                r = json.loads(p.read_text(encoding="utf-8"))
                key = (f"failed: {r['failure_class']}" if r["status"] == "failed"
                       else f"not sent: {r['reason']}" if r["status"] == "not_sent"
                       else "complete")
            counts[key] = counts.get(key, 0) + 1
        per_list.append({"harvest": entry["name"], "documents": len(entry["doc_ids"]),
                         "counts": dict(sorted(counts.items()))})
    summary = {"written_at": now(), "stopped": stopped,
               "attempted_this_session": attempted, "harvests": per_list}
    write_json(SUMMARY, summary)
    return summary


def print_summary(summary: dict) -> None:
    log(f"documents attempted this session: {summary['attempted_this_session']}")
    for h in summary["harvests"]:
        log(f"  {h['harvest']} ({h['documents']} documents)")
        for key, n in h["counts"].items():
            log(f"      {n:>5}  {key}")


def run(args) -> int:
    from eps.extract import Extractor, ResponseCache
    from eps.pipeline import load_officeholders, load_taxonomy
    from eps.providers import ProviderStopped

    provider = make_provider(args)
    settings = check_settings(provider)
    log(f"run started: provider={settings['provider']} model={settings['model']} "
        f"effort={settings['effort']} prompt={settings['prompt_version']} "
        f"({settings['prompt_fingerprint']}) tool={provider.tool_version}")

    lists, docs = load_all()
    check_against_reference(docs)
    extractor = Extractor(load_taxonomy(), provider=provider,
                          cache=ResponseCache(OUTPUT / "cache"))
    officeholders = load_officeholders()

    attempted, stopped, detail = 0, None, ""
    consecutive_failures = 0
    seen: set[str] = set()
    try:
        for entry in lists:
            todo = [d for d in entry["doc_ids"]
                    if d not in seen and read_status(d) not in DONE]
            seen.update(entry["doc_ids"])
            log(f"{entry['name']}: {len(entry['doc_ids'])} documents, "
                f"{len(todo)} to do")
            if not todo:
                continue
            save_prompt_snapshot(provider, entry["name"])
            for i, doc_id in enumerate(todo, 1):
                if args.limit and attempted >= args.limit:
                    stopped = f"--limit {args.limit} reached"
                    break
                try:
                    result = process(docs[doc_id], entry["name"], extractor,
                                     provider, officeholders)
                except ProviderStopped as exc:
                    stopped = getattr(exc, "failure_class", exc.reason)
                    detail = exc.detail
                    break
                write_json(result_path(doc_id), result)
                if result["status"] != "not_sent":
                    attempted += 1
                if result["status"] == "failed":
                    consecutive_failures += 1
                    log(f"  ! {doc_id} failed ({result['failure_class']}): "
                        f"{result['detail'][:200]}")
                    if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                        stopped = "repeated failures"
                        detail = (f"the last {consecutive_failures} documents all "
                                  f"failed, most recently with "
                                  f"{result['failure_class']}: {result['detail'][:300]}")
                        break
                elif result["status"] == "complete":
                    consecutive_failures = 0
                if i % 10 == 0 or i == len(todo):
                    log(f"  {entry['name']}: {i}/{len(todo)}")
            if stopped:
                break
    except KeyboardInterrupt:
        stopped = "interrupted"
    finally:
        provider.close()

    summary = summarise(lists, stopped, attempted)
    print_summary(summary)
    failed = sum(n for h in summary["harvests"] for k, n in h["counts"].items()
                 if k.startswith("failed"))

    if stopped == "usage_limit":
        log("STOPPED: Codex reported a usage limit. Nothing is lost. Run the "
            "same command again later and it continues where it left off.")
        return EXIT_STOPPED
    if stopped == "auth_failure":
        log("STOPPED: Codex says you are signed out. Run `codex login`, then "
            "the same command again; it continues where it left off.")
        return EXIT_STOPPED
    if stopped == "interrupted":
        log("STOPPED by you. Run the same command again to continue.")
        return EXIT_STOPPED
    if stopped and stopped.startswith("--limit"):
        log(f"STOPPED: {stopped}.")
        return EXIT_STOPPED
    if stopped == "repeated failures":
        log(f"STOPPED: {detail}\nThis usually means the --model or --effort "
            "is not available to your account (README step 5). Fix that and run "
            "the same command again; finished documents are kept.")
        return EXIT_STOPPED
    if stopped:
        log(f"STOPPED: {stopped}: {detail[:300]}\nRun the same command again "
            "to continue; finished documents are kept.")
        return EXIT_STOPPED
    if failed:
        log(f"FINISHED with {failed} failed document(s). Run the same command "
            "again to retry only those.")
        return EXIT_FAILURES
    log("FINISHED: every document is done. Zip the output folder and upload it "
        "(README step 8).")
    return EXIT_OK


def write_reference(path: Path) -> int:
    """Used when the bundle is built: record what ingest produces here."""
    _lists, docs = load_all()
    write_json(path, {doc_id: unit_digest(d) for doc_id, d in sorted(docs.items())})
    print(f"{len(docs)} documents -> {path}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Run eps extraction through the Codex CLI. See README.md.")
    p.add_argument("--model", help="the OpenAI model Codex should use (README step 5)")
    p.add_argument("--effort", help="the reasoning effort (README step 5)")
    p.add_argument("--provider", choices=["codex", "fake"], default="codex",
                   help="'fake' tests the bundle without calling Codex")
    p.add_argument("--limit", type=int, default=0,
                   help="stop after this many documents (testing)")
    p.add_argument("--timeout", type=float, default=900, help=argparse.SUPPRESS)
    p.add_argument("--fake-delay", type=float, default=0.5, help=argparse.SUPPRESS)
    p.add_argument("--write-reference", type=Path, help=argparse.SUPPRESS)
    args = p.parse_args(argv)

    sys.path.insert(0, str(ROOT / "eps" / "src"))
    if args.write_reference:
        return write_reference(args.write_reference)

    from_codex = args.provider == "codex"
    if from_codex and not (args.model and args.effort):
        stop("Choose a model and a reasoning effort first (README step 5), "
             "then run:\n  python run_extract.py --model <model> --effort <level>")

    check_checksums()
    if from_codex:
        check_codex_login(shutil.which("codex") or "codex")

    try:
        import lxml  # noqa: F401  # the one compiled dependency
        import eps.extract  # noqa: F401
    except ImportError as exc:
        stop(f"A required package is missing ({exc.name}). Follow README "
             "step 5 to set up the environment, then run again.")
    try:
        from eps.providers import CodexCLIProvider
        if from_codex and args.effort not in CodexCLIProvider.EFFORTS:
            stop(f"--effort must be one of: {', '.join(CodexCLIProvider.EFFORTS)}")
    except ImportError:  # pragma: no cover - covered by the check above
        pass
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
