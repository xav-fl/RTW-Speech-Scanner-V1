"""Model providers.

Everything in `extract.py` — the prompts, the caching, the JSON parsing, the
two-stage JEL selection — has nothing to do with which company answers the
call. This module is the one seam where that choice is made, so switching
providers means passing a different object in here, not touching extraction
logic, validation, or assembly.

A provider is anything with a `.call(system, user, max_tokens, cache_system)`
method returning text, and a `.name` used in the cache key. `cache_system` asks
for the system prompt to be cached server-side; a provider that cannot do that
ignores it, and the answer is the same either way. `FakeProvider` in the test suite satisfies
this with no network and no cost, which is how the pipeline gets tested at all.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

#: USD per million tokens, (input, output), for turning recorded usage into a
#: cost line. Cache writes bill at 1.25x input and cache reads at 0.1x.
PRICES_PER_MTOK = {
    "claude-sonnet-4-6": (3.00, 15.00),
}
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10

#: Transient failures (429 rate limits, 5xx, overloaded, dropped connections) are
#: retried by the SDK with exponential backoff. The default of 2 retries is tuned
#: for interactive use; a run of several hours will meet the odd bad minute, and
#: a document that exhausts its retries is recorded as failed.
MAX_RETRIES = 8


class ProviderStopped(RuntimeError):
    """The API will refuse every further request on this key.

    Out of credit, a spend limit reached, a key rejected or lacking permission:
    none of these is about the document being processed, so trying the next
    document fails in exactly the same way. The run stops instead of recording
    thousands of failures, and resumes from its saved responses once fixed.
    """

    def __init__(self, reason: str, detail: str):
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


#: Phrases the API uses when an account cannot pay for a request. Out of credit
#: has been reported as a 400 invalid_request_error ("Your credit balance is too
#: low to access the Anthropic API"), and a workspace spend limit the same way
#: ("You have reached your specified API usage limits"), so the type and status
#: code alone do not catch them.
_OUT_OF_CREDIT_PHRASES = ("credit balance", "usage limit", "spend limit")


def stop_reason(exc: BaseException) -> str | None:
    """Why no further request can succeed, or None for a per-request failure."""
    status = getattr(exc, "status_code", None)
    etype = getattr(exc, "type", None)
    body = getattr(exc, "body", None)
    if not etype and isinstance(body, dict):
        etype = (body.get("error") or {}).get("type")
    message = str(exc).lower()
    if (etype == "billing_error" or status == 402
            or any(p in message for p in _OUT_OF_CREDIT_PHRASES)):
        return "out of credit"
    if etype == "authentication_error" or status == 401:
        return "API key rejected"
    if etype == "permission_error" or status == 403:
        return "API key lacks permission"
    return None


class ModelProvider(Protocol):
    name: str

    def call(self, system: str, user: str, max_tokens: int,
             cache_system: bool = False) -> str: ...


class AnthropicProvider:
    """Wraps the Anthropic Messages API. Needs ANTHROPIC_API_KEY."""

    name = "anthropic"

    def __init__(self, model: str = "claude-sonnet-4-6", client=None):
        self.model = model
        if client is None:
            from anthropic import Anthropic
            client = Anthropic(max_retries=MAX_RETRIES)
        self.client = client
        self.usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                      "cache_creation_input_tokens": 0,
                      "cache_read_input_tokens": 0}

    def call(self, system: str, user: str, max_tokens: int,
             cache_system: bool = False) -> str:
        # A cached system prompt is sent as a content block carrying the
        # breakpoint. The prompt must be byte-identical on every call for the
        # cache to be read, which is why only fixed text goes there.
        system_arg = (
            [{"type": "text", "text": system,
              "cache_control": {"type": "ephemeral"}}]
            if cache_system else system
        )
        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=0,
                system=system_arg,
                messages=[{"role": "user", "content": user}],
            )
        except Exception as exc:
            reason = stop_reason(exc)
            if reason:
                raise ProviderStopped(reason, str(exc)) from exc
            raise
        self._record(getattr(resp, "usage", None))
        return "".join(
            b.text for b in resp.content if getattr(b, "type", "") == "text"
        )

    def _record(self, usage) -> None:
        """Keep the API's own token counts. They are the only proof that
        caching is working: a broken cache raises no error, it just costs more."""
        self.usage["calls"] += 1
        if usage is None:
            return
        for field in ("input_tokens", "output_tokens",
                      "cache_creation_input_tokens", "cache_read_input_tokens"):
            self.usage[field] += int(getattr(usage, field, 0) or 0)

    def cost_usd(self) -> float | None:
        """Cost of the calls made so far, or None for an unpriced model."""
        prices = PRICES_PER_MTOK.get(self.model)
        if prices is None:
            return None
        inp, out = prices
        u = self.usage
        return (u["input_tokens"] * inp
                + u["cache_creation_input_tokens"] * inp * CACHE_WRITE_MULTIPLIER
                + u["cache_read_input_tokens"] * inp * CACHE_READ_MULTIPLIER
                + u["output_tokens"] * out) / 1_000_000


class MistralProvider:
    """Wraps the Mistral API. Needs MISTRAL_API_KEY.

    Requires the `mistralai` package: pip install mistralai

    The default model name below is a placeholder — Mistral's catalogue moves
    quickly, so confirm the current model identifier against Mistral's own
    documentation before relying on it, rather than trusting this string.
    """

    name = "mistral"

    def __init__(self, model: str = "mistral-large-latest", client=None):
        self.model = model
        if client is None:
            from mistralai.client import Mistral
            import os
            key = os.environ.get("MISTRAL_API_KEY")
            if not key:
                raise RuntimeError(
                    "MISTRAL_API_KEY is not set. Get a key from "
                    "console.mistral.ai and set it before running extract."
                )
            client = Mistral(api_key=key)
        self.client = client

    def call(self, system: str, user: str, max_tokens: int,
             cache_system: bool = False) -> str:
        resp = self.client.chat.complete(
            model=self.model,
            max_tokens=max_tokens,
            temperature=0,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content


#: Every way a command-line call can fail, each recorded by name, so a failed
#: document is never mistaken for one in which nothing qualified.
CLI_FAILURES = (
    "auth_failure", "usage_limit", "timeout", "cli_error",
    "unparseable_output", "schema_mismatch", "empty_output",
)

#: Failures no later call can recover from: stop the run, resume later.
CLI_STOPPING = {"auth_failure", "usage_limit"}


class CLICallFailed(RuntimeError):
    """One call failed for a reason specific to it; the run can go on."""

    def __init__(self, failure_class: str, detail: str):
        super().__init__(f"{failure_class}: {detail}")
        self.failure_class = failure_class
        self.detail = detail


class CLIProviderStopped(ProviderStopped):
    """Signed out or at a usage limit: every further call would fail too."""

    def __init__(self, failure_class: str, detail: str):
        super().__init__(failure_class, detail)
        self.failure_class = failure_class


def run_command(args: list[str], stdin_text: str, cwd: Path,
                timeout: float) -> tuple[int, str, str]:
    """Run `args` with `stdin_text` on stdin; return (exit code, stdout, stderr).

    No shell. On timeout or Ctrl+C the whole process tree is killed, not just the
    immediate child: on Windows `codex` is usually a .cmd shim that starts
    node, and killing only the shim would leave the real work running.
    Raises subprocess.TimeoutExpired after the kill.
    """
    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        args, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
        **kwargs,
    )
    try:
        out, err = proc.communicate(stdin_text, timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        try:
            proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            pass
        raise
    except KeyboardInterrupt:
        # The child runs in its own process group, so Ctrl+C does not reach
        # it; without this it would carry on after the run has stopped.
        _kill_tree(proc)
        raise
    return proc.returncode, out or "", err or ""


def _kill_tree(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                       capture_output=True)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:  # pragma: no cover - already gone
            pass


#: Phrases that mark a non-zero exit as one no retry can fix. Codex's exit
#: codes are not documented, so this reads its message. Anything unmatched is
#: recorded as `cli_error` with the message, rather than guessed at.
_USAGE_LIMIT_PHRASES = ("usage limit",)
_AUTH_PHRASES = ("not logged in", "codex login", "401 unauthorized",
                 "unauthorized", "authentication")


def classify_cli_error(message: str) -> str:
    text = (message or "").lower()
    if any(p in text for p in _USAGE_LIMIT_PHRASES):
        return "usage_limit"
    if any(p in text for p in _AUTH_PHRASES):
        return "auth_failure"
    return "cli_error"


class CodexCLIProvider:
    """Calls an installed Codex CLI (`codex exec`) instead of an HTTP API.

    For running extraction on someone else's computer under their own ChatGPT
    sign-in, with no API key. Each call:

    - runs `codex exec` as a subprocess, with an argument list and a timeout;
    - from an empty working folder this provider creates, so no AGENTS.md or
      other project file is picked up;
    - with the extraction instructions as Codex's replacement system
      instructions (a file), and the document on stdin;
    - with shell, web search, multi-agent and app connectors switched off, a
      read-only sandbox, and no saved session;
    - against a strict JSON Schema for the call's kind (cli_schemas.py), read
      back from the `-o` file and checked again here.

    A failure raises CLICallFailed (or CLIProviderStopped for a sign-in or
    usage-limit failure) carrying one of CLI_FAILURES. Every call, failed or
    not, is appended to `call_log`, and to `log_path` as JSON lines if given.

    `model` and `effort` have no defaults: the person running it chooses them.
    """

    name = "codex"

    #: Reasoning levels Codex documents; which a model accepts varies by model.
    EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")

    def __init__(self, model: str | None = None, effort: str | None = None,
                 timeout: float = 900, log_path: str | Path | None = None,
                 executable: str | None = None, run=run_command,
                 workdir: str | Path | None = None):
        if not model:
            raise ValueError("the codex provider needs a model name (--model)")
        if effort not in self.EFFORTS:
            raise ValueError(f"the codex provider needs a reasoning effort "
                             f"(--effort), one of {list(self.EFFORTS)}")
        self.model = model
        self.effort = effort
        self.timeout = timeout
        self.log_path = Path(log_path) if log_path else None
        self.executable = executable or shutil.which("codex") or "codex"
        self._run = run
        root = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="eps-codex-"))
        self.workdir = root / "work"      # -C target; stays empty
        self.files = root / "files"       # instructions, schemas, answers
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.files.mkdir(parents=True, exist_ok=True)
        self.call_log: list[dict] = []
        #: Merged into every call-log record, e.g. the document being worked on.
        self.context: dict = {}
        self._tool_version: str | None = None
        self._n = 0

    @property
    def tool_version(self) -> str:
        if self._tool_version is None:
            try:
                code, out, err = self._run([self.executable, "--version"], "",
                                           self.workdir, 30)
                self._tool_version = (out or err).strip() if code == 0 else "unknown"
            except Exception:
                self._tool_version = "unknown"
        return self._tool_version

    def command(self, instructions: Path, schema: Path, answer: Path) -> list[str]:
        # Values after -c are TOML; single quotes make them literal strings,
        # so a Windows path's backslashes are not read as escapes.
        return [
            self.executable, "exec", "-",
            "--sandbox", "read-only",
            "--ephemeral",
            "--skip-git-repo-check",
            "--ignore-user-config",
            "-C", str(self.workdir),
            "-m", self.model,
            "-c", f"model_reasoning_effort='{self.effort}'",
            "-c", f"model_instructions_file='{instructions}'",
            "-c", "project_doc_max_bytes=0",
            "-c", "web_search='disabled'",
            "-c", "features.shell_tool=false",
            "-c", "features.multi_agent=false",
            "-c", "features.apps=false",
            "--output-schema", str(schema),
            "-o", str(answer),
        ]

    def call(self, system: str, user: str, max_tokens: int,
             cache_system: bool = False) -> str:
        from . import cli_schemas

        kind = cli_schemas.call_kind(system)
        if kind is None:
            raise ValueError("the codex provider has no output schema for this "
                             "prompt; it serves extraction calls only")
        instructions = self.files / (
            f"instructions-{hashlib.sha256(system.encode('utf-8')).hexdigest()[:12]}.md")
        if not instructions.exists():
            instructions.write_text(system, encoding="utf-8")
        schema = self.files / f"{kind}.schema.json"
        if not schema.exists():
            schema.write_text(cli_schemas.schema_json(kind), encoding="utf-8")
        self._n += 1
        answer = self.files / f"answer-{self._n}.json"
        answer.unlink(missing_ok=True)

        record = self._record_start(kind)
        started = time.monotonic()
        try:
            try:
                code, out, err = self._run(
                    self.command(instructions, schema, answer), user,
                    self.workdir, self.timeout)
            except subprocess.TimeoutExpired:
                raise CLICallFailed("timeout", f"no answer after {self.timeout:g}s")
            except OSError as exc:
                # Not installed, or not on PATH: no call can succeed.
                raise CLIProviderStopped("cli_error", f"cannot run codex: {exc}")
            record["exit_code"] = code
            if code != 0:
                message = (err or out or "").strip()
                failure = classify_cli_error(message)
                detail = f"exit {code}: {message[-1000:]}"
                if failure in CLI_STOPPING:
                    raise CLIProviderStopped(failure, detail)
                raise CLICallFailed(failure, detail)
            text = answer.read_text(encoding="utf-8") if answer.exists() else ""
            if not text.strip():
                raise CLICallFailed("empty_output", "codex wrote no final message")
            try:
                data = json.loads(text)
            except ValueError as exc:
                raise CLICallFailed("unparseable_output", f"{exc}: {text[:200]!r}")
            problems = cli_schemas.validate(data, cli_schemas.SCHEMAS[kind])
            if problems:
                raise CLICallFailed("schema_mismatch", "; ".join(problems[:5]))
        except (CLICallFailed, CLIProviderStopped) as exc:
            record["failure_class"] = exc.failure_class
            record["detail"] = exc.detail[:1000]
            raise
        finally:
            record["duration_s"] = round(time.monotonic() - started, 2)
            self._record_end(record)
            answer.unlink(missing_ok=True)
        return text

    def _record_start(self, kind: str) -> dict:
        from . import cli_schemas
        from .extract import PROMPT_VERSION, prompt_fingerprint

        return {
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "tool": self.name, "tool_version": self.tool_version,
            "model": self.model, "effort": self.effort, "call_kind": kind,
            "prompt_version": PROMPT_VERSION,
            "prompt_fingerprint": prompt_fingerprint(),
            "schema_hash": cli_schemas.schema_hash(kind),
            "exit_code": None, "duration_s": None,
            "failure_class": None, "detail": "",
            **self.context,
        }

    def _record_end(self, record: dict) -> None:
        self.call_log.append(record)
        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def close(self) -> None:
        """Remove the working folder this provider created."""
        shutil.rmtree(self.workdir.parent, ignore_errors=True)


class FakeProvider:
    """A provider with no network and no cost, for tests and dry runs.

    `responder` is a function (system, user) -> str. Tests supply canned JSON;
    the pipeline cannot tell this apart from a real provider, which is the
    point — it proves the extraction logic does not depend on which one
    answered.
    """

    name = "fake"

    def __init__(self, responder):
        self.responder = responder
        self.calls = 0

    def call(self, system: str, user: str, max_tokens: int,
             cache_system: bool = False) -> str:
        self.calls += 1
        return self.responder(system, user)


PROVIDERS = {"anthropic": AnthropicProvider, "mistral": MistralProvider,
             "codex": CodexCLIProvider}


def get_provider(name: str, model: str | None = None):
    """Construct a provider by name, e.g. from a CLI flag."""
    if name not in PROVIDERS:
        raise ValueError(f"unknown provider {name!r}; choose from {list(PROVIDERS)}")
    cls = PROVIDERS[name]
    return cls(model=model) if model else cls()
