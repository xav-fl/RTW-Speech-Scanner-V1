"""The Codex command-line provider, with the subprocess mocked.

No Codex call is made anywhere in this file. A fake `run` stands in for the
subprocess: it sees exactly the arguments, stdin and working folder Codex
would, and writes the `-o` answer file the way Codex does.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from eps import cli_schemas
from eps.extract import EXTRACT_SYSTEM, JEL_SYSTEM, Extractor
from eps.harvest.local import ingest_row
from eps.pipeline import load_taxonomy
from eps.providers import (
    CLI_FAILURES, CLICallFailed, CLIProviderStopped, CodexCLIProvider,
    ProviderStopped, get_provider, run_command,
)

SELECT_OK = {"observations": [
    {"unit_ids": ["D1.P001.S001"], "anchor": None, "reason": "Does X work?"}]}
CLASSIFY_OK = {"mechanism": "levy transfer cap", "codes": [{"code": "J24", "strength": 3}]}
CLASSIFY_SYSTEM = JEL_SYSTEM + "\nACTIVE JEL CODES — choose only from these:\nJ24 ...\n"


class FakeRun:
    """Stands in for run_command. `answer` is written to the -o file."""

    def __init__(self, answer=None, code=0, stderr="", raises=None):
        self.answer, self.code, self.stderr, self.raises = answer, code, stderr, raises
        self.calls: list[dict] = []

    def __call__(self, args, stdin_text, cwd, timeout):
        if args[1:] == ["--version"]:
            return 0, "codex-cli 9.9.9\n", ""
        self.calls.append({"args": args, "stdin": stdin_text, "cwd": Path(cwd),
                           "cwd_entries": list(Path(cwd).iterdir()),
                           "timeout": timeout})
        if self.raises is not None:
            raise self.raises
        if self.answer is not None:
            out = Path(args[args.index("-o") + 1])
            out.write_text(self.answer if isinstance(self.answer, str)
                           else json.dumps(self.answer), encoding="utf-8")
        return self.code, "", self.stderr


def provider(tmp_path, run, **kw):
    return CodexCLIProvider(model="gpt-test", effort="medium", run=run,
                            workdir=tmp_path / "codex", executable="codex", **kw)


def _failure(tmp_path, run, system=EXTRACT_SYSTEM):
    p = provider(tmp_path, run)
    with pytest.raises((CLICallFailed, CLIProviderStopped)) as info:
        p.call(system, "DOCUMENT UNITS: ...", 3000)
    assert p.call_log[-1]["failure_class"] == info.value.failure_class
    return info.value


# --- success ---------------------------------------------------------------

def test_select_call_returns_the_answer_and_uses_the_documented_flags(tmp_path):
    run = FakeRun(SELECT_OK)
    p = provider(tmp_path, run)
    text = p.call(EXTRACT_SYSTEM, "DOCUMENT UNITS:\nD1.P001.S001: We will act.", 3000)
    assert json.loads(text) == SELECT_OK

    call = run.calls[0]
    args = call["args"]
    assert args[:3] == ["codex", "exec", "-"]
    for flag in ("--ephemeral", "--skip-git-repo-check", "--ignore-user-config"):
        assert flag in args
    pairs = {args[i]: args[i + 1] for i in range(len(args) - 1)
             if args[i] in ("--sandbox", "-C", "-m", "--output-schema", "-o")}
    assert pairs["--sandbox"] == "read-only"
    assert pairs["-m"] == "gpt-test"
    assert Path(pairs["-C"]) == call["cwd"]
    configs = [args[i + 1] for i, a in enumerate(args) if a == "-c"]
    assert "model_reasoning_effort='medium'" in configs
    assert "project_doc_max_bytes=0" in configs
    assert "web_search='disabled'" in configs
    for feature in ("shell_tool", "multi_agent", "apps"):
        assert f"features.{feature}=false" in configs
    for forbidden in ("--dangerously-bypass-approvals-and-sandbox", "--yolo",
                      "--full-auto", "workspace-write", "danger-full-access"):
        assert forbidden not in args

    # The document goes on stdin; the instructions go in a file, verbatim.
    assert call["stdin"].startswith("DOCUMENT UNITS:")
    instructions = next(c for c in configs if c.startswith("model_instructions_file="))
    path = Path(instructions.split("=", 1)[1].strip("'"))
    assert path.read_text(encoding="utf-8") == EXTRACT_SYSTEM
    schema = json.loads(Path(pairs["--output-schema"]).read_text(encoding="utf-8"))
    assert schema == cli_schemas.SELECT_SCHEMA
    # Run from an empty folder, so no AGENTS.md or CLAUDE.md is picked up.
    assert call["cwd_entries"] == []


def test_classify_call_uses_the_classify_schema(tmp_path):
    run = FakeRun(CLASSIFY_OK)
    p = provider(tmp_path, run)
    assert json.loads(p.call(CLASSIFY_SYSTEM, "QUOTATION: x", 600)) == CLASSIFY_OK
    args = run.calls[0]["args"]
    schema = Path(args[args.index("--output-schema") + 1])
    assert json.loads(schema.read_text(encoding="utf-8")) == cli_schemas.CLASSIFY_SCHEMA


def test_every_call_is_logged_with_the_required_fields(tmp_path):
    log = tmp_path / "calls.jsonl"
    p = provider(tmp_path, FakeRun(SELECT_OK), log_path=log)
    p.call(EXTRACT_SYSTEM, "DOCUMENT UNITS: x", 3000)
    rec = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert rec == p.call_log[0]
    assert rec["tool"] == "codex" and rec["tool_version"] == "codex-cli 9.9.9"
    assert rec["model"] == "gpt-test" and rec["effort"] == "medium"
    assert rec["call_kind"] == "select"
    assert rec["prompt_fingerprint"] and rec["schema_hash"] == cli_schemas.schema_hash("select")
    assert rec["exit_code"] == 0 and rec["duration_s"] is not None
    assert rec["failure_class"] is None


# --- failures, each by name ------------------------------------------------

def test_non_zero_exit_is_cli_error_with_stderr(tmp_path):
    exc = _failure(tmp_path, FakeRun(code=1, stderr="stream disconnected before completion"))
    assert exc.failure_class == "cli_error"
    assert "stream disconnected" in exc.detail
    assert not isinstance(exc, ProviderStopped)


def test_usage_limit_stops_the_run(tmp_path):
    exc = _failure(tmp_path, FakeRun(code=1, stderr="ERROR: You've hit your usage limit. Try again later."))
    assert exc.failure_class == "usage_limit"
    assert isinstance(exc, ProviderStopped), "eps extract must stop, not record a failure"


def test_signed_out_stops_the_run(tmp_path):
    exc = _failure(tmp_path, FakeRun(code=1, stderr="Not logged in. Run codex login."))
    assert exc.failure_class == "auth_failure"
    assert isinstance(exc, ProviderStopped)


def test_timeout(tmp_path):
    exc = _failure(tmp_path, FakeRun(raises=subprocess.TimeoutExpired("codex", 900)))
    assert exc.failure_class == "timeout"


def test_codex_not_installed_stops_the_run(tmp_path):
    exc = _failure(tmp_path, FakeRun(raises=FileNotFoundError("codex")))
    assert exc.failure_class == "cli_error"
    assert isinstance(exc, ProviderStopped)


def test_malformed_json_is_unparseable_output(tmp_path):
    exc = _failure(tmp_path, FakeRun('{"observations": [ '))
    assert exc.failure_class == "unparseable_output"


@pytest.mark.parametrize("answer", [
    {"observations": [{"unit_ids": ["x"], "reason": "r"}]},             # no anchor
    {"observations": [{"unit_ids": ["x"], "anchor": None, "reason": "r", "extra": 1}]},
    {"mechanism": "m", "codes": []},                                     # wrong kind
])
def test_schema_mismatch(tmp_path, answer):
    exc = _failure(tmp_path, FakeRun(answer))
    assert exc.failure_class == "schema_mismatch"


def test_classify_strength_outside_1_to_3_is_schema_mismatch(tmp_path):
    exc = _failure(tmp_path, FakeRun({"mechanism": "m", "codes": [{"code": "J24", "strength": 5}]}),
                   system=CLASSIFY_SYSTEM)
    assert exc.failure_class == "schema_mismatch"


@pytest.mark.parametrize("answer", [None, "", "   \n"])
def test_empty_output(tmp_path, answer):
    exc = _failure(tmp_path, FakeRun(answer))
    assert exc.failure_class == "empty_output"


def test_failure_classes_are_the_documented_set():
    assert set(CLI_FAILURES) == {"auth_failure", "usage_limit", "timeout", "cli_error",
                                 "unparseable_output", "schema_mismatch", "empty_output"}


# --- construction ----------------------------------------------------------

def test_model_and_effort_must_be_chosen(tmp_path):
    with pytest.raises(ValueError, match="model"):
        CodexCLIProvider(effort="medium", workdir=tmp_path)
    with pytest.raises(ValueError, match="effort"):
        CodexCLIProvider(model="gpt-test", workdir=tmp_path)
    with pytest.raises(ValueError, match="effort"):
        CodexCLIProvider(model="gpt-test", effort="hgih", workdir=tmp_path)
    # eps extract --provider codex has no effort to pass, so it fails at once.
    with pytest.raises(ValueError, match="effort"):
        get_provider("codex", "gpt-test")


def test_a_prompt_other_than_extraction_is_refused(tmp_path):
    p = provider(tmp_path, FakeRun(SELECT_OK))
    with pytest.raises(ValueError, match="schema"):
        p.call("You tag intentions.", "x", 100)


# --- the real subprocess helper --------------------------------------------

def test_run_command_passes_stdin_and_cwd(tmp_path):
    code, out, err = run_command(
        [sys.executable, "-c", "import os,sys; print(os.getcwd()); print(sys.stdin.read())"],
        "hello from stdin", tmp_path, 60)
    assert code == 0
    assert Path(out.splitlines()[0]).resolve() == tmp_path.resolve()
    assert "hello from stdin" in out


def test_run_command_times_out_and_kills_the_child(tmp_path):
    with pytest.raises(subprocess.TimeoutExpired):
        run_command([sys.executable, "-c", "import time; time.sleep(60)"], "", tmp_path, 1)


# --- end to end through Extractor ------------------------------------------

SPEECH = """Thank you for having me here today.

We will raise the apprenticeship levy transfer cap to 50 per cent from April.

Thank you for listening."""


def test_extractor_runs_unchanged_on_the_codex_provider(tmp_path):
    path = tmp_path / "speech.txt"
    path.write_text(SPEECH, encoding="utf-8")
    doc = ingest_row({
        "path": str(path), "institution": "Department for Education",
        "country": "UK", "url": "https://www.gov.uk/x", "title": "A speech",
        "doc_type": "speech", "date": "2026-03-04", "delivery_status": "unknown",
        "speaker_hint": "A Minister", "notes": "speaker_is_document",
    })
    target = next(u.unit_id for u in doc.units if "levy" in u.text)

    def answer_for(args, stdin_text):
        configs = [args[i + 1] for i, a in enumerate(args) if a == "-c"]
        system = Path(next(c for c in configs if c.startswith("model_instructions_file="))
                      .split("=", 1)[1].strip("'")).read_text(encoding="utf-8")
        if cli_schemas.call_kind(system) == "select":
            return {"observations": [{"unit_ids": [target], "anchor": None,
                                      "reason": "Do levy transfers raise training?"}]}
        return CLASSIFY_OK

    class Responder(FakeRun):
        def __call__(self, args, stdin_text, cwd, timeout):
            if args[1:] != ["--version"]:
                self.answer = answer_for(args, stdin_text)
            return super().__call__(args, stdin_text, cwd, timeout)

    p = provider(tmp_path, Responder())
    obs = Extractor(load_taxonomy(), provider=p).extract(doc, "A Minister")
    assert [o.unit_ids for o in obs] == [[target]]
    assert obs[0].provider == "codex" and obs[0].model_id == "gpt-test"
    assert obs[0].primary.detailed_code == "J24"
    assert [r["call_kind"] for r in p.call_log] == ["select", "classify"]


# --- the build-stage prompts -----------------------------------------------

from eps.context import RESOLVE_SYSTEM, TRIAGE_SYSTEM, _parse_json_list
from eps.intention import INTENTION_PROMPT, parse_response

TRIAGE_OK = {"items": [{"quote_id": "q1", "needs_context": True,
                        "expressions": ["this policy"]}]}
RESOLVE_OK = {"items": [{"quote_id": "q1", "status": "resolved", "note": None,
                         "insertions": [{"position": "after", "anchor": "this policy",
                                         "insertion": "the levy cap", "evidence": "levy cap"}]}]}
INTENTION_OK = {"broad": "commits_to_action", "sub": "announces_decision",
                "evidence_type": None, "secondary_broad": None, "secondary_sub": None,
                "cue": "We will raise", "has_quantified_target": True,
                "target_cue": "50 per cent", "claims_causal_effect": False,
                "causal_cue": None, "rationale": "A decision announced."}


@pytest.mark.parametrize("system, answer, kind", [
    (TRIAGE_SYSTEM, TRIAGE_OK, "triage"),
    (RESOLVE_SYSTEM, RESOLVE_OK, "resolve"),
])
def test_context_calls_get_the_bare_list_their_prompt_asks_for(tmp_path, system, answer, kind):
    run = FakeRun(answer)
    p = provider(tmp_path, run)
    text = p.call(system, "quote_id: q1\nquotation: x", 4000)
    assert json.loads(text) == answer["items"]
    assert _parse_json_list(text) == answer["items"]   # context.py's own parser
    args = run.calls[0]["args"]
    schema = json.loads(Path(args[args.index("--output-schema") + 1]).read_text(encoding="utf-8"))
    assert schema == cli_schemas.SCHEMAS[kind]
    assert p.call_log[0]["call_kind"] == kind


def test_intention_call_returns_an_object_the_tagger_parses(tmp_path):
    p = provider(tmp_path, FakeRun(INTENTION_OK))
    text = p.call(INTENTION_PROMPT, "QUOTE\nWe will raise the cap.", 1200)
    assert parse_response(text) == INTENTION_OK
    assert p.call_log[0]["call_kind"] == "intention"


def test_triage_answer_missing_a_field_is_schema_mismatch(tmp_path):
    exc = _failure(tmp_path, FakeRun({"items": [{"quote_id": "q1", "expressions": []}]}),
                   system=TRIAGE_SYSTEM)
    assert exc.failure_class == "schema_mismatch"


def test_every_schema_is_strict():
    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for v in node.values():
                walk(v)
    for schema in cli_schemas.SCHEMAS.values():
        assert schema["type"] == "object"
        walk(schema)


def test_kill_running_stops_codex_processes_started_by_other_threads(tmp_path):
    import threading
    import time
    from eps.providers import _RUNNING, kill_running

    outcome = {}

    def worker():
        t0 = time.monotonic()
        code, _out, _err = run_command(
            [sys.executable, "-c", "import time; time.sleep(60)"], "", tmp_path, 120)
        outcome["code"], outcome["took"] = code, time.monotonic() - t0

    t = threading.Thread(target=worker)
    t.start()
    for _ in range(100):
        if _RUNNING:
            break
        time.sleep(0.05)
    kill_running()
    t.join(30)
    assert not t.is_alive()
    assert outcome["code"] != 0 and outcome["took"] < 30
    assert not _RUNNING
