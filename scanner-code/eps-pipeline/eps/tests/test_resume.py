"""Running out of credit stops the run cleanly, and re-running resumes it.

The failure this guards against is quiet: without it, an exhausted balance makes
every remaining document fail one after another, the run "finishes", and the
dataset built from it looks like a complete one with fewer quotes.
"""

from __future__ import annotations

import json

import anthropic
import httpx
import pytest

import eps.cli as cli
from eps.harvest.local import ingest_row
from eps.pipeline import save_documents
from eps.providers import AnthropicProvider, stop_reason

SPEECH = """Thank you for having me here today.

We will raise the apprenticeship levy transfer cap to {n} per cent from April. Larger employers will fund training across their supply chains.

Thank you for listening."""


def _api_error(cls, status, etype, message):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls(message, response=httpx.Response(status, request=request),
               body={"type": "error", "error": {"type": etype, "message": message}})


def _credit_error():
    return _api_error(anthropic.BadRequestError, 400, "invalid_request_error",
                      "Your credit balance is too low to access the Anthropic API.")


class ScriptedClient:
    """Answers like the model; raises `error` on call number `fail_at`."""

    def __init__(self, fail_at=None, error=None):
        self.calls = 0
        self.fail_at = fail_at
        self.error = error

        client = self

        class messages:
            @staticmethod
            def create(**kw):
                client.calls += 1
                if client.fail_at and client.calls >= client.fail_at:
                    raise client.error
                user = kw["messages"][0]["content"]
                if "DOCUMENT UNITS:" in user:
                    ids = [l.split(":")[0] for l in user.splitlines()
                           if ".P002." in l and "not selectable" not in l]
                    text = json.dumps({"observations": [
                        {"unit_ids": ids[:1], "anchor": None, "reason": "q"}]})
                else:
                    text = json.dumps({"mechanism": "m", "codes": []})

                class B: type = "text"
                b = B()
                b.text = text

                class R: content = [b]; usage = None
                return R()

        self.messages = messages()


@pytest.fixture
def run_dir(tmp_path):
    docs = []
    for n in (30, 40, 50):
        p = tmp_path / f"speech{n}.txt"
        p.write_text(SPEECH.format(n=n), encoding="utf-8")
        docs.append(ingest_row({
            "path": str(p), "institution": "Department for Education",
            "country": "UK", "url": f"https://www.gov.uk/speech-{n}",
            "title": "A speech", "doc_type": "speech", "date": "2026-03-04",
            "delivery_status": "unknown", "speaker_hint": "A Minister",
            "notes": "speaker_is_document",
        }))
    d = tmp_path / "run"
    save_documents(docs, d / "documents.pkl")
    return d


def _use(monkeypatch, client):
    monkeypatch.setattr(cli, "get_provider",
                        lambda name, model=None: AnthropicProvider(model="claude-sonnet-4-6",
                                                                   client=client))


def _status(run_dir):
    return json.loads((run_dir / cli.EXTRACT_STATUS).read_text(encoding="utf-8"))


def test_out_of_credit_stops_saves_and_resumes_without_repaying(run_dir, monkeypatch):
    # Each document costs two calls: select, then classify its one quote.
    # Credit runs out on call 4 -- the second document's classification.
    broke = ScriptedClient(fail_at=4, error=_credit_error())
    _use(monkeypatch, broke)
    rc = cli.main(["extract", "--run-dir", str(run_dir), "--run-id", "r"])

    assert rc == 3
    assert broke.calls == 4                      # stopped at once, no hammering
    status = _status(run_dir)
    assert status["complete"] is False
    assert status["stopped_reason"] == "out of credit"
    assert len(status["remaining_doc_ids"]) == 2 # the interrupted doc is redone

    # The partial extract must not quietly become a dataset.
    assert cli.main(["build", "--run-dir", str(run_dir), "--run-id", "r"]) == 2
    assert not (run_dir / "out" / "dataset.csv").exists()

    # Credit topped up: the same command finishes the job, paying only for the
    # three calls it never got answers to.
    paid = ScriptedClient()
    _use(monkeypatch, paid)
    rc = cli.main(["extract", "--run-dir", str(run_dir), "--run-id", "r"])

    assert rc == 0
    assert paid.calls == 3
    status = _status(run_dir)
    assert status["complete"] is True and status["remaining_doc_ids"] == []
    assert cli.main(["build", "--run-dir", str(run_dir), "--run-id", "r"]) == 0


def test_a_killed_run_is_never_reported_complete(run_dir, monkeypatch):
    class Killed(BaseException):
        pass

    _use(monkeypatch, ScriptedClient(fail_at=2, error=Killed()))
    with pytest.raises(Killed):
        cli.main(["extract", "--run-dir", str(run_dir), "--run-id", "r"])
    assert _status(run_dir)["complete"] is False


def test_partial_build_is_possible_when_asked_for(run_dir, monkeypatch):
    _use(monkeypatch, ScriptedClient(fail_at=4, error=_credit_error()))
    cli.main(["extract", "--run-dir", str(run_dir), "--run-id", "r"])
    rc = cli.main(["build", "--run-dir", str(run_dir), "--run-id", "r",
                   "--allow-incomplete"])
    assert rc == 0


@pytest.mark.parametrize("error, expected", [
    (_credit_error(), "out of credit"),
    (_api_error(anthropic.BadRequestError, 400, "invalid_request_error",
                "You have reached your specified API usage limits."), "out of credit"),
    (_api_error(anthropic.PermissionDeniedError, 403, "billing_error",
                "There is an issue with your billing."), "out of credit"),
    (_api_error(anthropic.AuthenticationError, 401, "authentication_error",
                "invalid x-api-key"), "API key rejected"),
    (_api_error(anthropic.RateLimitError, 429, "rate_limit_error",
                "Number of requests has exceeded your rate limit."), None),
    (_api_error(anthropic.InternalServerError, 500, "api_error", "Internal error"), None),
    (_api_error(anthropic.BadRequestError, 400, "invalid_request_error",
                "prompt is too long"), None),
])
def test_only_account_level_errors_stop_the_run(error, expected):
    assert stop_reason(error) == expected
