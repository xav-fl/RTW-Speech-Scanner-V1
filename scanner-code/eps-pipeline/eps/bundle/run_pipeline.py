"""Run the eps pipeline, extract and build, through your Codex CLI.

    python run_pipeline.py --model <model> --effort <level>
    python run_pipeline.py --check          # set-up check only; starts nothing

Reads only this folder; writes only to output/. See README.md.

1. Extract. Every document gets its own result file in output/results/ the
   moment it is finished, so the run can be stopped at any point and the same
   command picks up where it left off: finished documents are skipped, failed
   ones are retried.
2. Build, once every document is extracted. For each full harvest (UK, US):
   the context stage, intention tagging, validation and the output tables,
   written to output/build/<harvest>/. Every model answer is cached as it
   arrives, so a build that stops is re-run for free up to where it stopped.
"""

from __future__ import annotations

import argparse
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
BUILD = OUTPUT / "build"
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
    """[{name, doc_ids, build}] in run order, and doc_id -> Document."""
    lists, docs = [], {}
    for entry in harvest_lists():
        ids = []
        for d in ingest(ROOT / "harvests" / entry["manifest"]):
            docs.setdefault(d.doc_id, d)
            ids.append(d.doc_id)
        lists.append({"name": entry["name"], "doc_ids": ids,
                      "build": bool(entry.get("build"))})
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


def _fake_answer(kind: str, stdin_text: str) -> dict:
    """What the stand-in for Codex answers. Valid, and meaningless."""
    if kind == "select":
        # The longest selectable sentence: likelier to pass validation than a
        # greeting, so the build stages get something to work on.
        lines = [line for line in stdin_text.splitlines()
                 if ".P" in line.split(":", 1)[0] and "not selectable" not in line]
        if not lines:
            return {"observations": []}
        pick = max(lines, key=len).split(":", 1)[0]
        return {"observations": [
            {"unit_ids": [pick], "anchor": None, "reason": "acceptance test"}]}
    if kind == "classify":
        return {"mechanism": "acceptance test",
                "codes": [{"code": "J24", "strength": 1}]}
    if kind == "triage":
        ids = [line.split(":", 1)[1].strip() for line in stdin_text.splitlines()
               if line.startswith("quote_id:")]
        return {"items": [{"quote_id": q, "needs_context": False, "expressions": []}
                          for q in ids]}
    if kind == "resolve":
        ids = [line.split(":", 1)[1].strip() for line in stdin_text.splitlines()
               if line.startswith("quote_id:")]
        return {"items": [{"quote_id": q, "status": "not_needed", "insertions": [],
                           "note": "acceptance test"} for q in ids]}
    # intention: the cue must be words from the QUOTE
    quote = (stdin_text.split("\nQUOTE\n", 1)[1].splitlines()[0]
             if "\nQUOTE\n" in stdin_text else "")
    cue = " ".join(quote.split()[:3]) or "acceptance"
    return {"broad": "unclear", "sub": None, "evidence_type": None,
            "secondary_broad": None, "secondary_sub": None, "cue": cue,
            "has_quantified_target": False, "target_cue": None,
            "claims_causal_effect": False, "causal_cue": None,
            "rationale": "acceptance test"}


def fake_codex(delay: float):
    """A stand-in for the `codex` program, for testing the bundle without
    Codex. It answers like Codex does, through the real provider code, and
    never produces anything a person would rely on."""
    def run(args, stdin_text, cwd, timeout):
        from eps import cli_schemas

        if args[1:] == ["--version"]:
            return 0, "fake-codex (bundle acceptance test)\n", ""
        time.sleep(delay)
        configs = [args[i + 1] for i, a in enumerate(args) if a == "-c"]
        instructions = next(c for c in configs
                            if c.startswith("model_instructions_file="))
        system = Path(instructions.split("=", 1)[1].strip("'")).read_text(encoding="utf-8")
        answer = _fake_answer(cli_schemas.call_kind(system), stdin_text)
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


def make_workers(args) -> list:
    """One provider per worker, each with its own empty working folder, so
    parallel calls never share a file. The first is also used for the steps
    that run one call at a time."""
    return [make_provider(args) for _ in range(max(1, args.workers))]


class WorkerPool:
    """Runs model work on up to N workers at once, one provider each.

    Results are handed back to the main thread, which alone writes files and
    keeps counts, so nothing on disk is written by two threads. At most N
    items are in flight, which keeps a stop (usage limit, Ctrl+C) prompt:
    nothing new starts after it, and what was running is allowed to finish.
    """

    def __init__(self, workers: list):
        import queue
        from concurrent.futures import ThreadPoolExecutor

        self.free = queue.Queue()
        for w in workers:
            self.free.put(w)
        self.size = len(workers)
        self.executor = ThreadPoolExecutor(max_workers=self.size)
        self.pending: dict = {}

    def submit(self, key, fn, *args) -> list:
        """Start fn(worker, *args); return [(key, outcome)] for anything that
        finished meanwhile. Waits for a free slot first."""
        done = []
        while len(self.pending) >= self.size:
            done += self._collect(block=True)

        def task():
            worker = self.free.get()
            try:
                return fn(worker, *args)
            finally:
                self.free.put(worker)

        self.pending[self.executor.submit(task)] = key
        return done + self._collect(block=False)

    def drain(self) -> list:
        done = []
        while self.pending:
            done += self._collect(block=True)
        return done

    def _collect(self, block: bool) -> list:
        from concurrent.futures import FIRST_COMPLETED, wait

        if not self.pending:
            return []
        finished, _ = wait(list(self.pending), timeout=None if block else 0,
                           return_when=FIRST_COMPLETED)
        out = []
        for fut in finished:
            key = self.pending.pop(fut)
            try:
                out.append((key, fut.result()))
            except BaseException as exc:  # handed to the caller to judge
                out.append((key, exc))
        return out

    def abandon(self) -> None:
        """Ctrl+C: kill running Codex processes and start nothing more."""
        from eps.providers import kill_running

        kill_running()
        self.executor.shutdown(wait=False, cancel_futures=True)

    def close(self) -> None:
        self.executor.shutdown(wait=True)


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
    # Settings lock once a document has been completed with them. Before that
    # nothing would be mixed, so a first attempt with a model the account
    # cannot use (every call fails) does not trap the run on that model.
    locked = RESULTS.exists() and any(
        json.loads(p.read_text(encoding="utf-8")).get("status") == "complete"
        for p in RESULTS.glob("*.json"))
    if SETTINGS.exists() and locked:
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


# --- stage 1: extract --------------------------------------------------------


def result_path(doc_id: str) -> Path:
    return RESULTS / f"{doc_id}.json"


def read_result(doc_id: str) -> dict | None:
    p = result_path(doc_id)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def read_status(doc_id: str) -> str | None:
    r = read_result(doc_id)
    return r.get("status") if r else None


def not_sent(doc, list_name, provider, officeholders) -> tuple[dict | None, str | None]:
    """(result, speaker): a finished 'not sent' result for a document the
    model is never shown, or (None, speaker) for one it must see."""
    from eps.validate import resolve_speaker

    base = {"doc_id": doc.doc_id, "url": doc.url, "harvest": list_name,
            "provider": provider.name, "model": provider.model,
            "effort": provider.effort}
    if not any(u.attributable for u in doc.units):
        return {**base, "status": "not_sent", "reason": "nothing selectable",
                "observations": [], "finished_at": now()}, None
    speaker, _source, warning = resolve_speaker(doc, officeholders)
    if speaker is None:
        return {**base, "status": "not_sent", "reason": "no speaker",
                "detail": warning, "observations": [], "finished_at": now()}, None
    return None, speaker


def extract_doc(worker, doc, speaker, list_name) -> dict:
    """Extract one document on one worker and return its result record.
    Raises ProviderStopped (signed out, usage limit) for the caller."""
    from eps.providers import CLICallFailed, ProviderStopped

    extractor, provider = worker
    base = {"doc_id": doc.doc_id, "url": doc.url, "harvest": list_name,
            "provider": provider.name, "model": provider.model,
            "effort": provider.effort, "tool_version": provider.tool_version}
    first_call = len(provider.call_log)
    provider.context = {"stage": "extract", "harvest": list_name, "doc_id": doc.doc_id}
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


def extract_all(lists, docs, workers, officeholders, limit) -> tuple:
    """Work through every list in order on the worker pool, then retry what
    failed once. Returns (stopped, detail, attempted).

    `workers` are (extractor, provider) pairs. Documents the model never sees
    are settled here at once; the rest go to the pool. Only this thread
    writes result files, as each document finishes.
    """
    from eps.providers import ProviderStopped

    provider0 = workers[0][1]
    state = {"stopped": None, "detail": "", "consecutive": 0, "finished": 0}
    attempted = 0

    def handle(done: list) -> None:
        for doc_id, outcome in done:
            if isinstance(outcome, ProviderStopped):
                if state["stopped"] is None:
                    state["stopped"] = getattr(outcome, "failure_class", outcome.reason)
                    state["detail"] = outcome.detail
                continue  # left unrecorded, so the next run does it again
            if isinstance(outcome, BaseException):
                raise outcome
            write_json(result_path(doc_id), outcome)
            state["finished"] += 1
            if outcome["status"] == "failed":
                state["consecutive"] += 1
                log(f"  ! {doc_id} failed ({outcome['failure_class']}): "
                    f"{outcome['detail'][:200]}")
                if (state["consecutive"] >= MAX_CONSECUTIVE_FAILURES
                        and state["stopped"] is None):
                    state["stopped"] = "repeated failures"
                    state["detail"] = (
                        f"the last {state['consecutive']} documents all failed, "
                        f"most recently with {outcome['failure_class']}: "
                        f"{outcome['detail'][:300]}")
            else:
                state["consecutive"] = 0
            if state["finished"] % 10 == 0:
                log(f"  {state['finished']} documents finished this session")

    pool = WorkerPool(workers)
    try:
        for pass_no in (1, 2):
            seen: set[str] = set()
            for entry in lists:
                todo = [d for d in entry["doc_ids"]
                        if d not in seen and read_status(d) not in DONE]
                seen.update(entry["doc_ids"])
                if pass_no == 2 and not todo:
                    continue
                log(f"{entry['name']}: " + ("retrying failed documents" if pass_no == 2
                    else f"{len(entry['doc_ids'])} documents, {len(todo)} to do"))
                if todo and pass_no == 1:
                    save_prompt_snapshot(provider0, entry["name"])
                for doc_id in todo:
                    if state["stopped"]:
                        break
                    result, speaker = not_sent(docs[doc_id], entry["name"],
                                               provider0, officeholders)
                    if result is not None:
                        write_json(result_path(doc_id), result)
                        continue
                    if limit and attempted >= limit:
                        state["stopped"] = f"--limit {limit} reached"
                        break
                    attempted += 1
                    handle(pool.submit(doc_id, extract_doc, docs[doc_id],
                                       speaker, entry["name"]))
                handle(pool.drain())
                if state["stopped"]:
                    return state["stopped"], state["detail"], attempted
    except KeyboardInterrupt:
        pool.abandon()
        raise
    finally:
        pool.close()
    return state["stopped"], state["detail"], attempted


# --- stage 2: build ----------------------------------------------------------


def observation_from_dict(d: dict):
    from eps.models import JELAssignment, Observation

    d = dict(d)
    d["primary"] = JELAssignment(**d.get("primary") or {})
    d["secondary"] = [JELAssignment(**s) for s in d.get("secondary") or []]
    return Observation(**d)


def tag_intentions_in_parallel(name, documents, extractions, mapping, workers,
                               officeholders, cache) -> str | None:
    """Ask for every kept quote's intention on the worker pool, ahead of the build.

    The intention tagger in the pipeline works through quotes one at a time.
    This sends the same requests, through the same tagger code, several at
    once; each answer lands in the shared response cache, and the build that
    follows then reads every one from there instead of calling again. The
    rows are the ones the build will tag (validated, with the context stage's
    quote_in_context joined in), so the requests are identical. If any differ,
    the build simply makes those calls itself: this changes only how long the
    build takes, never what it produces.

    Returns the failure class of a stop (usage limit, signed out), or None.
    """
    from eps.context import quote_id
    from eps.intention import IntentionTagger
    from eps.pipeline import _kept_rows, join_context
    from eps.providers import ProviderStopped

    rows = _kept_rows(documents, extractions, officeholders)
    join_context(rows, mapping)
    by_qid: dict[str, dict] = {}
    for row in rows:
        row["quote_id"] = row.get("quote_id") or quote_id(row)
        by_qid.setdefault(row["quote_id"], row)
    doc_map = {d.doc_id: d for d in documents}
    ts = now()
    taggers = [IntentionTagger(provider=provider, cache=cache)
               for _extractor, provider in workers]
    log(f"{name}: tagging intentions for {len(by_qid)} quotes on {len(taggers)} workers")

    def tag(tagger, row):
        tagger.provider.context = {"stage": "intention", "harvest": name}
        try:
            return tagger.tag_one(row, doc_map.get(str(row.get("doc_id", ""))), ts)
        finally:
            tagger.provider.context = {}

    stopped = None
    pool = WorkerPool(taggers)
    try:
        for qid, row in by_qid.items():
            if stopped:
                break
            for _key, outcome in pool.submit(qid, tag, row):
                if isinstance(outcome, ProviderStopped) and stopped is None:
                    stopped = getattr(outcome, "failure_class", outcome.reason)
                elif isinstance(outcome, BaseException) and not isinstance(outcome, ProviderStopped):
                    raise outcome
        for _key, outcome in pool.drain():
            if isinstance(outcome, ProviderStopped) and stopped is None:
                stopped = getattr(outcome, "failure_class", outcome.reason)
    except KeyboardInterrupt:
        pool.abandon()
        raise
    finally:
        pool.close()
    return stopped


def build_one(entry: dict, docs: dict, workers: list, officeholders) -> dict:
    """Context, intention tagging, validation and tables for one harvest.

    Neither the context stage nor the intention tagger lets a usage limit
    escape: both record the affected quotes as failed and carry on. So a stop
    is read from the provider's own call log instead, and the build is then
    reported as stopped rather than finished, to be re-run later.

    With more than one worker, intentions are asked for in parallel first
    (tag_intentions_in_parallel); the build then finds them in the cache.
    """
    from eps.context import Contextualiser
    from eps.extract import ResponseCache
    from eps.intention import IntentionTagger
    from eps.pipeline import build, load_taxonomy, run_context
    from eps.providers import CLI_STOPPING

    name = entry["name"]
    out_dir = BUILD / name
    documents = [docs[d] for d in entry["doc_ids"]]
    extractions = {d: [observation_from_dict(o)
                       for o in (read_result(d) or {}).get("observations") or []]
                   for d in entry["doc_ids"]}
    cache = ResponseCache(OUTPUT / "cache")
    provider = workers[0][1]
    first_calls = [len(p.call_log) for _e, p in workers]

    def stopped_class() -> str | None:
        for (_e, p), first in zip(workers, first_calls):
            for c in p.call_log[first:]:
                if c.get("failure_class") in CLI_STOPPING:
                    return c["failure_class"]
        return None

    log(f"{name}: context stage")
    provider.context = {"stage": "context", "harvest": name}
    try:
        mapping, ctx = run_context(documents, extractions,
                                   Contextualiser(provider=provider, cache=cache),
                                   officeholders, out_dir)
        if stopped_class():
            return {"harvest": name, "status": "stopped", "stopped": stopped_class()}

        if len(workers) > 1:
            if tag_intentions_in_parallel(name, documents, extractions, mapping,
                                          workers, officeholders, cache) \
                    or stopped_class():
                return {"harvest": name, "status": "stopped", "stopped": stopped_class()}

        log(f"{name}: intention tagging and output tables")
        provider.context = {"stage": "intention", "harvest": name}
        summary = build(documents, extractions, load_taxonomy(), officeholders,
                        out_dir, run_id=f"codex-bundle:{name}", context=mapping,
                        intention_tagger=IntentionTagger(provider=provider, cache=cache))
    finally:
        provider.context = {}
    if stopped_class():
        return {"harvest": name, "status": "stopped", "stopped": stopped_class()}

    intention = summary["intention"]
    ctx_failed = sum(n for k, n in ctx["by_status"].items() if k.startswith("failed"))
    int_failed = intention.get("not_tagged", 0) if intention.get("status") == "tagged" else 0
    record = {
        "harvest": name,
        "status": "complete" if not (ctx_failed or int_failed) else "finished with failures",
        "documents": len(documents),
        "quotes_kept": summary["observations_kept"],
        "quotes_rejected": summary["observations_rejected"],
        "context": ctx["by_status"],
        "intention": {k: intention.get(k) for k in
                      ("tagged", "not_tagged", "unclear", "failure_reasons")},
        "files": summary["files"],
        "built_at": now(),
    }
    write_json(out_dir / "build_status.json", record)
    log(f"{name}: {record['quotes_kept']} quotes kept; context failures "
        f"{ctx_failed}; intention not tagged {int_failed} -> output/build/{name}/")
    return record


# --- summary and the run -----------------------------------------------------


def summarise(lists: list[dict], stopped: str | None, attempted: int,
              builds: list[dict]) -> dict:
    per_list = []
    for entry in lists:
        counts: dict[str, int] = {}
        for doc_id in entry["doc_ids"]:
            r = read_result(doc_id)
            key = ("not yet done" if r is None
                   else f"failed: {r['failure_class']}" if r["status"] == "failed"
                   else f"not sent: {r['reason']}" if r["status"] == "not_sent"
                   else "complete")
            counts[key] = counts.get(key, 0) + 1
        per_list.append({"harvest": entry["name"], "documents": len(entry["doc_ids"]),
                         "counts": dict(sorted(counts.items()))})
    summary = {"written_at": now(), "stopped": stopped,
               "attempted_this_session": attempted, "extract": per_list,
               "build": builds}
    write_json(SUMMARY, summary)
    return summary


def print_summary(summary: dict) -> None:
    log(f"documents attempted this session: {summary['attempted_this_session']}")
    for h in summary["extract"]:
        log(f"  {h['harvest']} ({h['documents']} documents)")
        for key, n in h["counts"].items():
            log(f"      {n:>5}  {key}")
    for b in summary["build"]:
        log(f"  build {b['harvest']}: {b['status']}")


def run(args) -> int:
    from eps.extract import Extractor, ResponseCache
    from eps.pipeline import load_officeholders, load_taxonomy

    providers = make_workers(args)
    provider = providers[0]
    settings = check_settings(provider)
    log(f"run started: provider={settings['provider']} model={settings['model']} "
        f"effort={settings['effort']} prompt={settings['prompt_version']} "
        f"({settings['prompt_fingerprint']}) tool={provider.tool_version} "
        f"workers={len(providers)}")

    lists, docs = load_all()
    check_against_reference(docs)
    cache = ResponseCache(OUTPUT / "cache")
    taxonomy = load_taxonomy()
    workers = [(Extractor(taxonomy, provider=p, cache=cache), p) for p in providers]
    officeholders = load_officeholders()

    builds: list[dict] = []
    stopped, detail, attempted = None, "", 0
    try:
        stopped, detail, attempted = extract_all(lists, docs, workers,
                                                 officeholders, args.limit)
        extract_failed = any(read_status(d) not in DONE
                             for e in lists for d in e["doc_ids"])
        if not stopped and not extract_failed:
            for entry in lists:
                if not entry["build"]:
                    continue
                record = build_one(entry, docs, workers, officeholders)
                builds.append(record)
                if record["status"] == "stopped":
                    stopped = record["stopped"]
                    break
    except KeyboardInterrupt:
        stopped = "interrupted"
    finally:
        for p in providers:
            p.close()

    summary = summarise(lists, stopped, attempted, builds)
    print_summary(summary)
    extract_failed = sum(n for h in summary["extract"] for k, n in h["counts"].items()
                         if k.startswith("failed"))
    build_failed = [b["harvest"] for b in builds if b["status"] != "complete"]

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
            "is not available to your account. Fix that and run the same "
            "command again; finished documents are kept.")
        return EXIT_STOPPED
    if stopped:
        log(f"STOPPED: {stopped}: {detail[:300]}\nRun the same command again "
            "to continue; finished documents are kept.")
        return EXIT_STOPPED
    if extract_failed:
        log(f"FINISHED EXTRACTING with {extract_failed} failed document(s), so the "
            "build has not run. Run the same command again to retry them.")
        return EXIT_FAILURES
    if build_failed:
        log(f"FINISHED with some failed model calls in the build for "
            f"{', '.join(build_failed)}. Run the same command again to retry "
            "them; answers already received are reused.")
        return EXIT_FAILURES
    log("FINISHED: every document is extracted and both datasets are built "
        "(output/build/). Zip the output folder and upload it.")
    return EXIT_OK


def check_only() -> int:
    """Everything a run checks before its first call, then stop. Writes no
    settings and starts nothing, so it never blocks the real run."""
    lists, docs = load_all()
    check_against_reference(docs)
    log(f"SETUP OK: {len(docs)} documents in {len(lists)} lists; ready to run.")
    return EXIT_OK


def write_reference(path: Path) -> int:
    """Used when the bundle is built: record what ingest produces here."""
    _lists, docs = load_all()
    write_json(path, {doc_id: unit_digest(d) for doc_id, d in sorted(docs.items())})
    print(f"{len(docs)} documents -> {path}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Run the eps pipeline (extract and build) through the Codex "
                    "CLI. See README.md.")
    p.add_argument("--model", help="the OpenAI model Codex should use")
    p.add_argument("--effort", help="the reasoning effort")
    p.add_argument("--check", action="store_true",
                   help="check the set-up and stop; starts no run")
    p.add_argument("--provider", choices=["codex", "fake"], default="codex",
                   help="'fake' tests the bundle without calling Codex")
    p.add_argument("--limit", type=int, default=0,
                   help="stop after this many documents (testing)")
    p.add_argument("--workers", type=int, default=4,
                   help="Codex calls to run at once (default 4); fewer if your "
                        "plan's limits are reached quickly")
    p.add_argument("--timeout", type=float, default=900, help=argparse.SUPPRESS)
    p.add_argument("--fake-delay", type=float, default=0.5, help=argparse.SUPPRESS)
    p.add_argument("--write-reference", type=Path, help=argparse.SUPPRESS)
    args = p.parse_args(argv)

    if sys.version_info < (3, 11):
        stop("This needs Python 3.11 or newer; this is Python "
             f"{sys.version.split()[0]}. Install a newer one (README step 1), "
             "delete the .venv folder inside this folder, and set up again.")
    sys.path.insert(0, str(ROOT / "eps" / "src"))
    if args.write_reference:
        return write_reference(args.write_reference)

    from_codex = args.provider == "codex"
    if from_codex and not args.check and not (args.model and args.effort):
        stop("Choose a model and a reasoning effort first, then run:\n"
             "  run_pipeline.py --model <model> --effort <level>")

    check_checksums()
    if from_codex:
        check_codex_login(shutil.which("codex") or "codex")

    try:
        import lxml  # noqa: F401  # the one compiled dependency
        import eps.extract  # noqa: F401
    except ImportError as exc:
        stop(f"A required package is missing ({exc.name}). Set up the "
             "environment (README step 4), then run again.")
    if args.check:
        return check_only()
    from eps.providers import CodexCLIProvider
    if from_codex and args.effort not in CodexCLIProvider.EFFORTS:
        stop(f"--effort must be one of: {', '.join(CodexCLIProvider.EFFORTS)}")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
