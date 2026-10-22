"""Output schemas for the command-line provider.

The pipeline makes five kinds of model call, each expecting a different JSON
shape back, so there are five schemas. Each mirrors exactly what its caller
parses:

  select    Extractor.select_units()   {"observations": [{unit_ids, anchor, reason}]}
  classify  Extractor.classify()       {"items": [{item_id, status, codes, comments}]}
  triage    Contextualiser.triage()    [{quote_id, needs_context, expressions}]
  resolve   Contextualiser.resolve()   [{quote_id, status, insertions, note}]
  intention IntentionTagger.tag_one()  {broad, sub, ..., rationale}

All satisfy OpenAI's strict structured-output rules: every property is listed
in `required`, and every object sets `additionalProperties: false`. A field a
caller treats as optional is therefore required but nullable.

Strict output must be an object at the top level, but the two context prompts
ask for a list. Their schemas wrap the list as {"items": [...]}, and the
provider hands the caller the list itself (`LIST_KINDS`), so context.py parses
exactly what it parses from any other provider.

Labels are plain strings, not enums: the callers' own validators judge them,
as they do for every provider, so an invalid label is recorded the same way.

The provider is handed only (system, user), so it tells the calls apart by
their system prompt, which is fixed text in each module.
"""

from __future__ import annotations

import hashlib
import json

SELECT_SCHEMA = {
    "type": "object",
    "properties": {
        "observations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "unit_ids": {"type": "array", "items": {"type": "string"}},
                    "anchor": {"type": ["string", "null"]},
                    "reason": {"type": "string"},
                },
                "required": ["unit_ids", "anchor", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["observations"],
    "additionalProperties": False,
}

CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "string"},
                    "status": {"type": "string"},
                    "codes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "code": {"type": "string"},
                                "strength": {"type": "integer", "enum": [1, 2, 3]},
                                "rationale": {"type": "string"},
                            },
                            "required": ["code", "strength", "rationale"],
                            "additionalProperties": False,
                        },
                    },
                    "comments": {"type": "string"},
                },
                "required": ["item_id", "status", "codes", "comments"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["items"],
    "additionalProperties": False,
}

_NULLABLE_STR = {"type": ["string", "null"]}

TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "quote_id": {"type": "string"},
                    "needs_context": {"type": "boolean"},
                    "expressions": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["quote_id", "needs_context", "expressions"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["items"],
    "additionalProperties": False,
}

RESOLVE_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "quote_id": {"type": "string"},
                    "status": {"type": "string"},
                    "insertions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "position": {"type": "string"},
                                "anchor": {"type": "string"},
                                "insertion": {"type": "string"},
                                "evidence": {"type": "string"},
                            },
                            "required": ["position", "anchor", "insertion", "evidence"],
                            "additionalProperties": False,
                        },
                    },
                    "note": _NULLABLE_STR,
                },
                "required": ["quote_id", "status", "insertions", "note"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["items"],
    "additionalProperties": False,
}

INTENTION_SCHEMA = {
    "type": "object",
    "properties": {
        "broad": {"type": "string"},
        "sub": _NULLABLE_STR,
        "evidence_type": _NULLABLE_STR,
        "secondary_broad": _NULLABLE_STR,
        "secondary_sub": _NULLABLE_STR,
        "cue": {"type": "string"},
        "has_quantified_target": {"type": "boolean"},
        "target_cue": _NULLABLE_STR,
        "claims_causal_effect": {"type": "boolean"},
        "causal_cue": _NULLABLE_STR,
        "rationale": {"type": "string"},
    },
    "required": ["broad", "sub", "evidence_type", "secondary_broad",
                 "secondary_sub", "cue", "has_quantified_target", "target_cue",
                 "claims_causal_effect", "causal_cue", "rationale"],
    "additionalProperties": False,
}

SCHEMAS = {"select": SELECT_SCHEMA, "classify": CLASSIFY_SCHEMA,
           "triage": TRIAGE_SCHEMA, "resolve": RESOLVE_SCHEMA,
           "intention": INTENTION_SCHEMA}

#: Kinds whose caller expects a bare list; the provider unwraps "items".
LIST_KINDS = {"triage", "resolve"}


def schema_json(kind: str) -> str:
    """The schema as written to disk: canonical, so its hash is stable."""
    return json.dumps(SCHEMAS[kind], sort_keys=True, separators=(",", ":"))


def schema_hash(kind: str) -> str:
    return hashlib.sha256(schema_json(kind).encode("utf-8")).hexdigest()[:12]


def call_kind(system: str) -> str | None:
    """Which pipeline call a system prompt belongs to, or None.

    The classify prompt is JEL_SYSTEM followed by the JEL taxonomy, so it
    is matched by prefix; every other prompt is matched exactly.
    """
    from .context import RESOLVE_SYSTEM, TRIAGE_SYSTEM
    from .extract import EXTRACT_SYSTEM, JEL_SYSTEM
    from .intention import INTENTION_PROMPT

    if system == EXTRACT_SYSTEM:
        return "select"
    if system.startswith(JEL_SYSTEM):
        return "classify"
    if system == TRIAGE_SYSTEM:
        return "triage"
    if system == RESOLVE_SYSTEM:
        return "resolve"
    if system == INTENTION_PROMPT:
        return "intention"
    return None


def validate(value, schema: dict, path: str = "$") -> list[str]:
    """Problems with `value` against `schema`; empty when it conforms.

    Covers only what the schemas above use: type (single or list), enum,
    properties, required, additionalProperties false, and array items.
    """
    problems: list[str] = []
    types = schema.get("type")
    types = types if isinstance(types, list) else [types]
    if not any(_is_type(value, t) for t in types):
        return [f"{path}: expected {'/'.join(types)}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        problems.append(f"{path}: {value!r} not in {schema['enum']}")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                problems.append(f"{path}: missing {key!r}")
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in props:
                    problems.append(f"{path}: unexpected {key!r}")
        for key, sub in props.items():
            if key in value:
                problems.extend(validate(value[key], sub, f"{path}.{key}"))
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            problems.extend(validate(item, schema["items"], f"{path}[{i}]"))
    return problems


def _is_type(value, t: str) -> bool:
    if t == "object":
        return isinstance(value, dict)
    if t == "array":
        return isinstance(value, list)
    if t == "string":
        return isinstance(value, str)
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "boolean":
        return isinstance(value, bool)
    if t == "null":
        return value is None
    raise ValueError(f"unsupported schema type {t!r}")
