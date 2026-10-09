"""The bundle's run_extract.py, on a three-document bundle built in tmp_path.

No Codex is called: `--provider fake` answers through the real Codex provider
code with a stand-in for the `codex` program. Failure cases replace that
stand-in with one that fails.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

EPS = Path(__file__).resolve().parent.parent

SPEECH = """Thank you for having me here today.

We will raise the apprenticeship levy transfer cap to 50 per cent from April.

Thank you for listening."""

RELEASE = """The department today published new figures.

The figures cover the period to March."""


def _write_checksums(root: Path) -> None:
    lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(root).as_posix()}"
             for p in sorted(root.rglob("*"))
             if p.is_file() and p.name != "CHECKSUMS.sha256" and "output" not in p.parts]
    (root / "CHECKSUMS.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def bundle(tmp_path):
    root = tmp_path / "eps-bundle"
    shutil.copytree(EPS / "src" / "eps", root / "eps" / "src" / "eps",
                    ignore=shutil.ignore_patterns("__pycache__", "*.bak*", "*.xlsx"))
    shutil.copytree(EPS / "data" / "reference", root / "eps" / "data" / "reference")
    shutil.copyfile(EPS / "bundle" / "run_extract.py", root / "run_extract.py")
    docs = root / "harvests" / "uk" / "documents"
    docs.mkdir(parents=True)
    rows = []
    for name, text, doc_type, notes in [
        ("a.txt", SPEECH, "speech", "speaker_is_document"),
        ("b.txt", SPEECH.replace("Thank you for having me", "Good morning, and thank you for having me"), "speech",
         "speaker_is_document"),
        ("c.txt", RELEASE, "press_release", "no_match"),
    ]:
        (docs / name).write_text(text, encoding="utf-8")
        rows.append({"path": f"documents/{name}", "institution": "Test Department",
                     "country": "UK", "url": f"https://www.gov.uk/{name}",
                     "title": name, "doc_type": doc_type, "date": "2026-07-04",
                     "delivery_status": "unknown", "speaker_hint": "A Minister",
                     "notes": notes})
    with open(root / "harvests" / "uk" / "manifest.csv", "w", newline="",
              encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    (root / "harvests" / "harvests.json").write_text(
        json.dumps([{"name": "test-uk", "manifest": "uk/manifest.csv"}]), encoding="utf-8")
    _write_checksums(root)
    return root


def run(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(root / "run_extract.py"), "--provider", "fake",
         "--fake-delay", "0", *args],
        cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=300)


def results(root: Path) -> dict:
    return {p.stem: json.loads(p.read_text(encoding="utf-8"))
            for p in (root / "output" / "results").glob("*.json")}


def calls(root: Path) -> list[dict]:
    path = root / "output" / "logs" / "calls.jsonl"
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]


def load_runner(root: Path):
    spec = importlib.util.spec_from_file_location("run_extract_under_test",
                                                  root / "run_extract.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def failing_codex(stderr: str):
    def factory(delay):
        def run(args, stdin_text, cwd, timeout):
            if args[1:] == ["--version"]:
                return 0, "fake-codex\n", ""
            return 1, "", stderr
        return run
    return factory


# --- a complete run ----------------------------------------------------------

def test_full_run_writes_a_result_per_document_and_a_summary(bundle):
    r = run(bundle)
    assert r.returncode == 0, r.stdout + r.stderr
    res = results(bundle)
    assert len(res) == 3
    statuses = sorted(v["status"] for v in res.values())
    assert statuses == ["complete", "complete", "not_sent"]
    assert next(v for v in res.values() if v["status"] == "not_sent")["reason"] \
        == "nothing selectable"
    for v in res.values():
        if v["status"] == "complete":
            assert len(v["observations"]) == 1
            assert v["observations"][0]["provider"] == "fake-codex"

    summary = json.loads((bundle / "output" / "run_summary.json").read_text(encoding="utf-8"))
    assert summary["harvests"][0]["counts"] == {"complete": 2, "not sent: nothing selectable": 1}

    log = calls(bundle)
    assert [c["call_kind"] for c in log] == ["select", "classify"] * 2
    for c in log:
        for field in ("tool", "tool_version", "model", "effort", "prompt_fingerprint",
                      "schema_hash", "exit_code", "duration_s", "failure_class",
                      "doc_id", "harvest"):
            assert field in c
        assert c["tool"] == "fake-codex" and c["failure_class"] is None


def test_rerun_after_a_finished_run_does_nothing(bundle):
    assert run(bundle).returncode == 0
    n = len(calls(bundle))
    r = run(bundle)
    assert r.returncode == 0
    assert len(calls(bundle)) == n
    assert "0 to do" in r.stdout


# --- resuming ----------------------------------------------------------------

def test_limit_stops_and_the_same_command_resumes_without_redoing(bundle):
    r = run(bundle, "--limit", "1")
    assert r.returncode == 3
    done = {k for k, v in results(bundle).items() if v["status"] == "complete"}
    assert len(done) == 1
    first_calls = calls(bundle)

    r = run(bundle)
    assert r.returncode == 0, r.stdout + r.stderr
    later = calls(bundle)[len(first_calls):]
    assert later and not ({c["doc_id"] for c in later} & done), \
        "a finished document was sent again"
    assert sum(v["status"] == "complete" for v in results(bundle).values()) == 2


def test_failed_documents_are_named_and_retried(bundle, monkeypatch):
    mod = load_runner(bundle)
    monkeypatch.setattr(mod, "fake_codex", failing_codex("stream disconnected"))
    assert mod.main(["--provider", "fake"]) == mod.EXIT_FAILURES
    res = results(bundle)
    failed = [v for v in res.values() if v["status"] == "failed"]
    assert len(failed) == 2
    assert all(v["failure_class"] == "cli_error" for v in failed)
    assert all(not v.get("observations") for v in failed)
    summary = json.loads((bundle / "output" / "run_summary.json").read_text(encoding="utf-8"))
    assert summary["harvests"][0]["counts"]["failed: cli_error"] == 2

    r = run(bundle)  # the real fake answers now: only the failed two are retried
    assert r.returncode == 0, r.stdout + r.stderr
    assert {c["doc_id"] for c in calls(bundle) if c["failure_class"] is None} \
        == {v["doc_id"] for v in failed}


def test_usage_limit_stops_cleanly_and_leaves_the_document_to_do(bundle, monkeypatch):
    mod = load_runner(bundle)
    monkeypatch.setattr(mod, "fake_codex",
                        failing_codex("You've hit your usage limit. Try again later."))
    assert mod.main(["--provider", "fake"]) == mod.EXIT_STOPPED
    assert not [v for v in results(bundle).values() if v["status"] != "not_sent"]
    assert "usage limit" in (bundle / "output" / "logs" / "run.log").read_text(encoding="utf-8")

    assert run(bundle).returncode == 0
    assert sum(v["status"] == "complete" for v in results(bundle).values()) == 2


def test_repeated_failures_stop_the_run(bundle, monkeypatch):
    mod = load_runner(bundle)
    monkeypatch.setattr(mod, "fake_codex", failing_codex("model not found"))
    monkeypatch.setattr(mod, "MAX_CONSECUTIVE_FAILURES", 2)
    assert mod.main(["--provider", "fake"]) == mod.EXIT_STOPPED
    assert "--model or --effort" in (bundle / "output" / "logs" / "run.log").read_text(encoding="utf-8")


# --- the guards ----------------------------------------------------------------

def test_a_changed_file_stops_the_run_before_anything_happens(bundle):
    doc = bundle / "harvests" / "uk" / "documents" / "a.txt"
    doc.write_text(doc.read_text(encoding="utf-8") + " edited", encoding="utf-8")
    r = run(bundle)
    assert r.returncode == 1
    assert "changed: harvests/uk/documents/a.txt" in r.stderr
    assert not (bundle / "output" / "results").exists()


def test_different_settings_are_refused(bundle):
    assert run(bundle, "--limit", "1").returncode == 3
    settings = bundle / "output" / "run_settings.json"
    data = json.loads(settings.read_text(encoding="utf-8"))
    data["effort"] = "high"
    settings.write_text(json.dumps(data), encoding="utf-8")
    r = run(bundle)
    assert r.returncode == 1
    assert "different settings" in r.stderr


def test_codex_run_needs_a_model_and_an_effort(bundle):
    r = subprocess.run([sys.executable, str(bundle / "run_extract.py")],
                       cwd=bundle, capture_output=True, text=True, timeout=60)
    assert r.returncode == 1
    assert "model and a reasoning effort" in r.stderr and "README step 6" in r.stderr


def test_reference_check_passes_on_an_unchanged_bundle(bundle):
    subprocess.run([sys.executable, str(bundle / "run_extract.py"),
                    "--write-reference", str(bundle / "reference_units.json")],
                   cwd=bundle, check=True, capture_output=True)
    _write_checksums(bundle)
    r = run(bundle)
    assert r.returncode == 0
    assert "all 3 documents match the reference" in r.stdout
