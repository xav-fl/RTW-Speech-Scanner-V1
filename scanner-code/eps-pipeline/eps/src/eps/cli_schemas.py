"""Output schemas for the command-line provider.

Extraction makes two kinds of call, and each expects a different JSON shape
back, so there are two schemas. Each mirrors exactly what extract.py parses:

  select    Extractor.select_units()  {"observations": [{unit_ids, anchor, reason}]}
  classify  Extractor.classify()      {"mechanism", "codes": [{code, strength}]}

Both satisfy OpenAI's strict structured-output rules: every property is listed
in `required`, and every object sets `additionalProperties: false`. A field
extract.py treats as optional is therefore required but nullable (`anchor`).

The provider is handed only (system, user), so it tells the two calls apart
by their system prompt, which is fixed text in extract.py.
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
        "mechanism": {"type": "string"},
        "codes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "strength": {"type": "integer", "enum": [1, 2, 3]},
                },
                "required": ["code", "strength"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["mechanism", "codes"],
    "additionalProperties": False,
}

SCHEMAS = {"select": SELECT_SCHEMA, "classify": CLASSIFY_SCHEMA}


def schema_json(kind: str) -> str:
    """The schema as written to disk: canonical, so its hash is stable."""
    return json.dumps(SCHEMAS[kind], sort_keys=True, separators=(",", ":"))


def schema_hash(kind: str) -> str:
    return hashlib.sha256(schema_json(kind).encode("utf-8")).hexdigest()[:12]


def call_kind(system: str) -> str | None:
    """Which extraction call a system prompt belongs to, or None.

    The classify prompt is JEL_SYSTEM followed by the active code list, so it
    is matched by prefix; the select prompt is EXTRACT_SYSTEM exactly.
    """
    from .extract import EXTRACT_SYSTEM, JEL_SYSTEM

    if system == EXTRACT_SYSTEM:
        return "select"
    if system.startswith(JEL_SYSTEM):
        return "classify"
    return None


def validate(value, schema: dict, path: str = "$") -> list[str]:
    """Problems with `value` against `schema`; empty when it conforms.

    Covers only what the two schemas above use: type (single or list), enum,
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
    if t == "null":
        return value is None
    raise ValueError(f"unsupported schema type {t!r}")
