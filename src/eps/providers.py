"""Model providers.

Everything in `extract.py` — the prompts, the caching, the JSON parsing, the
two-stage JEL selection — has nothing to do with which company answers the
call. This module is the one seam where that choice is made, so switching
providers means passing a different object in here, not touching extraction
logic, validation, or assembly.

A provider is anything with a `.call(system, user, max_tokens) -> str` method
and a `.name` used in the cache key. `FakeProvider` in the test suite satisfies
this with no network and no cost, which is how the pipeline gets tested at all.
"""

from __future__ import annotations

from typing import Protocol


class ModelProvider(Protocol):
    name: str

    def call(self, system: str, user: str, max_tokens: int) -> str: ...


class AnthropicProvider:
    """Wraps the Anthropic Messages API. Needs ANTHROPIC_API_KEY."""

    name = "anthropic"

    def __init__(self, model: str = "claude-sonnet-4-6", client=None):
        self.model = model
        if client is None:
            from anthropic import Anthropic
            client = Anthropic()
        self.client = client

    def call(self, system: str, user: str, max_tokens: int) -> str:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=0,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(
            b.text for b in resp.content if getattr(b, "type", "") == "text"
        )


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

    def call(self, system: str, user: str, max_tokens: int) -> str:
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

    def call(self, system: str, user: str, max_tokens: int) -> str:
        self.calls += 1
        return self.responder(system, user)


PROVIDERS = {"anthropic": AnthropicProvider, "mistral": MistralProvider}


def get_provider(name: str, model: str | None = None):
    """Construct a provider by name, e.g. from a CLI flag."""
    if name not in PROVIDERS:
        raise ValueError(f"unknown provider {name!r}; choose from {list(PROVIDERS)}")
    cls = PROVIDERS[name]
    return cls(model=model) if model else cls()
