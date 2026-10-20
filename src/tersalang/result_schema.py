# SPDX-License-Identifier: Apache-2.0
"""Check an episode against `result.schema.json` without a third-party validator.

The checker covers the JSON Schema keywords that file uses: `$ref` to
`#/$defs`, `type`, `const`, `enum`, `pattern`, `minimum`,
`maximum`, `required`, `properties`, `additionalProperties`, and
`items`. `episode_problems` adds the rules a schema cannot state.
"""

from __future__ import annotations

import json
import math
import re
from functools import cache
from importlib import resources
from typing import Any

_TYPES = {
    "object": lambda value: isinstance(value, dict),
    "array": lambda value: isinstance(value, list),
    "string": lambda value: isinstance(value, str),
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
    "boolean": lambda value: isinstance(value, bool),
    "null": lambda value: value is None,
}


@cache
def result_schema() -> dict[str, Any]:
    """The packaged `result.schema.json`, loaded once."""
    text = resources.files("tersalang").joinpath("schemas/result.schema.json").read_text("utf-8")
    loaded: dict[str, Any] = json.loads(text)
    return loaded


def schema_errors(value: object, schema: dict[str, Any] | None = None) -> list[str]:
    """Every way `value` breaks `schema` (by default the result schema), as JSON-path messages."""
    root = schema if schema is not None else result_schema()
    errors: list[str] = []
    _check(value, root, root, "$", errors)
    return errors


def episode_problems(value: object) -> list[str]:
    """Schema errors, then the cross-field rules of the reward formula."""
    errors = schema_errors(value)
    if errors or not isinstance(value, dict):
        return errors
    reward = value["reward"]
    infrastructure = value["infrastructure_error"]
    if (reward is None) != (infrastructure is not None):
        errors.append("$.reward must be null exactly when infrastructure_error is set")
    if value["attempt_diagnostics"] > len(value["diagnostics"]):
        errors.append("$.attempt_diagnostics cannot exceed the number of diagnostics")
    tests = value["tests"]
    if tests["passed"] + tests["failed"] + tests["trapped"] != tests["total"]:
        errors.append("$.tests: passed + failed + trapped must equal total")
    cases = tests.get("cases")
    if isinstance(cases, list) and len(cases) != tests["total"]:
        errors.append("$.tests.cases must list every test")
    breakdown = value["breakdown"]
    if reward is not None:
        parts = [breakdown["C"], breakdown["E"], breakdown["w"]]
        if any(part is None for part in parts):
            errors.append("$.breakdown: C, E, and w are required for a scored reward")
        else:
            from tersalang.harness import score_reward

            expected = score_reward(float(parts[0]), float(parts[1]), float(parts[2]))
            if not math.isclose(float(reward), expected, rel_tol=0.0, abs_tol=1e-12):
                errors.append("$.reward does not match (1 - w) * C + w * C * E")
    return errors


def _check(
    value: object, schema: dict[str, Any], root: dict[str, Any], path: str, errors: list[str]
) -> None:
    ref = schema.get("$ref")
    if isinstance(ref, str):
        target: Any = root
        for part in ref.removeprefix("#/").split("/"):
            target = target[part]
        _check(value, target, root, path, errors)
        return
    kinds = schema.get("type")
    if kinds is not None:
        allowed = [kinds] if isinstance(kinds, str) else list(kinds)
        if not any(_TYPES[kind](value) for kind in allowed):
            errors.append(f"{path} must be {' or '.join(allowed)}")
            return
    if "const" in schema and not _same(value, schema["const"]):
        errors.append(f"{path} must be {json.dumps(schema['const'])}")
    if "enum" in schema and not any(_same(value, item) for item in schema["enum"]):
        errors.append(f"{path} must be one of {json.dumps(schema['enum'])}")
    if (
        isinstance(value, str)
        and "pattern" in schema
        and re.search(schema["pattern"], value) is None
    ):
        errors.append(f"{path} does not match {schema['pattern']}")
    if _TYPES["number"](value):
        number = float(value)  # type: ignore[arg-type]
        if "minimum" in schema and not number >= schema["minimum"]:
            errors.append(f"{path} is below {schema['minimum']}")
        if "maximum" in schema and not number <= schema["maximum"]:
            errors.append(f"{path} is above {schema['maximum']}")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}.{key} is required")
        properties: dict[str, Any] = schema.get("properties", {})
        extra = schema.get("additionalProperties", True)
        for key, item in value.items():
            if key in properties:
                _check(item, properties[key], root, f"{path}.{key}", errors)
            elif extra is False:
                errors.append(f"{path}.{key} is not allowed")
            elif isinstance(extra, dict):
                _check(item, extra, root, f"{path}.{key}", errors)
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            _check(item, schema["items"], root, f"{path}[{index}]", errors)


def _same(left: object, right: object) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    return left == right
