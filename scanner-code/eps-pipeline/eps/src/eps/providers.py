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


PROVIDERS = {"anthropic": AnthropicProvider, "mistral": MistralProvider}


def get_provider(name: str, model: str | None = None):
    """Construct a provider by name, e.g. from a CLI flag."""
    if name not in PROVIDERS:
        raise ValueError(f"unknown provider {name!r}; choose from {list(PROVIDERS)}")
    cls = PROVIDERS[name]
    return cls(model=model) if model else cls()
