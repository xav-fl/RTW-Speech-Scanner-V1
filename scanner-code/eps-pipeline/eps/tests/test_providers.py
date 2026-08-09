"""Tests for the provider abstraction.

The point of this module is that extraction, caching and validation do not
know or care which company answered a call. These tests exercise that claim
directly, using FakeProvider so nothing here touches the network.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from eps.assemble import observation_row
from eps.extract import Extractor, ResponseCache, render_units
from eps.harvest.local import ingest_row
from eps.pipeline import load_taxonomy
from eps.providers import (
    AnthropicProvider, FakeProvider, MistralProvider, PROVIDERS, get_provider,
)
from eps.validate import OfficeholderTable, validate_observations

SPEECH = """Thank you for having me here today.

We will raise the apprenticeship levy transfer cap to 50 per cent from April. Larger employers will fund training across their supply chains.

Thank you for listening."""


def _row(path, **over):
    row = {
        "path": str(path), "institution": "Department for Education",
        "country": "UK", "url": "https://www.gov.uk/x", "title": "A speech",
        "doc_type": "speech", "date": "2026-03-04", "delivery_status": "unknown",
        "speaker_hint": "A Minister", "notes": "",
    }
    row.update(over)
    return row


@pytest.fixture
def doc(tmp_path):
    p = tmp_path / "speech.txt"
    p.write_text(SPEECH, encoding="utf-8")
    return ingest_row(_row(p))


def _canned_responder(system, user):
    """A stand-in model: always picks the funding-commitment sentence."""
    if "DOCUMENT UNITS:" in user:
        ids = [
            l.split(":")[0] for l in user.splitlines()
            if ".P" in l and "not selectable" not in l and ":" in l
        ]
        pick = [i for i in ids if ".P002." in i][:1]
        return json.dumps({
            "observations": [{"unit_ids": pick, "anchor": None, "reason": "commitment"}]
            if pick else []
        })
    if "MAJOR CATEGORIES:" in user:
        return json.dumps({"primary": "J", "secondary": []})
    return json.dumps({"sub": "J2", "detailed": ""})


# --- the provider interface -------------------------------------------------

def test_fake_provider_satisfies_the_interface():
    p = FakeProvider(_canned_responder)
    assert p.name == "fake"
    assert isinstance(p.call("sys", "DOCUMENT UNITS:\nfoo", 100), str)


def test_get_provider_rejects_unknown_name():
    with pytest.raises(ValueError):
        get_provider("openai")


def test_get_provider_returns_registered_classes():
    assert isinstance(get_provider("anthropic", "claude-x"), AnthropicProvider)
    # MistralProvider construction needs a key or client; check the class is
    # registered without actually constructing one.
    assert PROVIDERS["mistral"] is MistralProvider


# --- Extractor is provider-agnostic -----------------------------------------

def test_extraction_result_identical_regardless_of_provider(doc, tmp_path):
    """The actual claim this refactor is for: swap the provider, get the same
    selected unit and the same JEL code, because none of the extraction logic
    references the provider at all."""
    tax = load_taxonomy()
    results = {}
    for name in ("anthropic-ish", "mistral-ish"):
        provider = FakeProvider(_canned_responder)
        provider.name = name  # distinct cache namespaces, same behaviour
        ex = Extractor(tax, provider=provider, cache=ResponseCache(tmp_path / name))
        obs = ex.extract(doc, "A Minister", run_id="t")
        results[name] = [o.unit_ids for o in obs]

    assert results["anthropic-ish"] == results["mistral-ish"]
    assert results["anthropic-ish"] != [[]]  # actually selected something


def test_provider_name_recorded_on_the_observation(doc, tmp_path):
    tax = load_taxonomy()
    provider = FakeProvider(_canned_responder)
    ex = Extractor(tax, provider=provider, cache=ResponseCache(tmp_path / "c"))
    obs = ex.extract(doc, "A Minister", run_id="t")
    assert obs and obs[0].provider == "fake"


def test_provider_name_flows_to_the_dataset_row(doc, tmp_path):
    tax = load_taxonomy()
    provider = FakeProvider(_canned_responder)
    ex = Extractor(tax, provider=provider, cache=ResponseCache(tmp_path / "c"))
    obs_list = ex.extract(doc, "A Minister", run_id="t")

    holders = OfficeholderTable([])  # speaker comes from the manifest hint
    validated, speaker, source, _ = validate_observations(doc, obs_list, tax, holders)
    row = observation_row(doc, validated[0], speaker, source)
    assert row["provider"] == "fake"


def test_legacy_client_kwarg_still_works(doc, tmp_path):
    """Existing scripts and tests that pass client=... directly must keep
    working — the refactor should not be a breaking change."""
    class LegacyFakeClient:
        class messages:
            @staticmethod
            def create(**kw):
                class B: type = "text"
                b = B()
                b.text = _canned_responder("", kw["messages"][0]["content"])
                class R: content = [b]
                return R()
        messages = messages()

    tax = load_taxonomy()
    ex = Extractor(tax, client=LegacyFakeClient(), cache=ResponseCache(tmp_path / "legacy"))
    obs = ex.extract(doc, "A Minister", run_id="t")
    assert obs and obs[0].provider == "anthropic"


# --- cache does not collide across providers --------------------------------

def test_same_prompt_different_provider_does_not_share_cache_entry():
    key_a = ResponseCache.key(provider="anthropic", model="m", system="s",
                              user="u", prompt_version="P", identity_mode="blind")
    key_b = ResponseCache.key(provider="mistral", model="m", system="s",
                              user="u", prompt_version="P", identity_mode="blind")
    assert key_a != key_b


# --- Mistral provider construction ------------------------------------------

def test_mistral_provider_requires_a_key(monkeypatch):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    pytest.importorskip("mistralai")
    with pytest.raises(RuntimeError, match="MISTRAL_API_KEY"):
        MistralProvider()


def test_mistral_provider_accepts_an_injected_client():
    """You do not need mistralai installed, or a key, to unit test against a
    fake Mistral client — same pattern as the Anthropic tests."""
    class FakeMistralClient:
        class chat:
            @staticmethod
            def complete(**kw):
                class Msg: content = _canned_responder("", kw["messages"][-1]["content"])
                class Choice: message = Msg()
                class R: choices = [Choice()]
                return R()
        chat = chat()

    provider = MistralProvider(client=FakeMistralClient())
    out = provider.call("sys", "DOCUMENT UNITS:\nD1.P001.S001: hello", 100)
    assert json.loads(out) == {"observations": []}
