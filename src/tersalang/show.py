# SPDX-License-Identifier: Apache-2.0
"""Canonical text form. The form is the expression that would build the value."""

from __future__ import annotations

import math

from tersalang.namespacing import public_name
from tersalang.values import (
    Value,
    VBool,
    VBytes,
    VChoice,
    VFloat,
    VInt,
    VInt64,
    VList,
    VMap,
    VMutableList,
    VMutableMap,
    VRecord,
    VResource,
    VSet,
    VText,
    VUnit,
)

# Most function values live in the evaluator, which imports this module, so they are matched
# by class name.
_FUNCTION_NAMES = frozenset(
    {
        "VFunc",
        "VBuiltin",
        "VCtor",
        "VRecordCtor",
        "VUserFunc",
        "VIfaceFn",
        "VForeign",
        "VLambda",
        "VBound",
    }
)


def show(value: Value) -> str:
    """The canonical text form of `value`, or a placeholder such as `<function>`.

    A value with any non-Showable part shows as a placeholder as a whole.
    """
    placeholder = _placeholder(value)
    if placeholder is not None:
        return placeholder
    if isinstance(value, (VInt, VInt64)):
        return str(value.value)
    if isinstance(value, VFloat):
        return _show_float(value.value)
    if isinstance(value, VBool):
        return "true" if value.value else "false"
    if isinstance(value, VText):
        return _show_text(value.value)
    if isinstance(value, VBytes):
        return f'Bytes.of_hex("{value.value.hex()}")'
    if isinstance(value, VUnit):
        return "Unit"
    if isinstance(value, VList):
        return "[" + ", ".join(show(item) for item in value.items) + "]"
    if isinstance(value, VMap):
        inner = ", ".join(f"{show(key)}: {show(item)}" for key, item in value.items)
        return "{" + inner + "}"
    if isinstance(value, VSet):
        inner = ", ".join(show(item) for item in value.items)
        return f"Set.from_list([{inner}])"
    if isinstance(value, VRecord):
        pairs = ", ".join(
            f"{name} = {show(item)}" for name, item in zip(value.names, value.fields, strict=True)
        )
        return f"{public_name(value.type_name)}({pairs})"
    if isinstance(value, VChoice):
        if not value.fields:
            return public_name(value.case)
        inner = ", ".join(show(item) for item in value.fields)
        return f"{public_name(value.case)}({inner})"
    return "<value>"


def _placeholder(value: Value) -> str | None:
    """The placeholder for a non-Showable value; None means the value has a canonical form."""
    if type(value).__name__ in _FUNCTION_NAMES:
        return "<function>"
    if isinstance(value, VResource):
        return "<resource>"
    if isinstance(value, (VMutableList, VMutableMap)):
        return "<mutable>"
    if isinstance(value, (VInt, VInt64, VFloat, VBool, VText, VBytes, VUnit)):
        return None
    children = _children(value)
    if children is None or any(_placeholder(child) is not None for child in children):
        return "<value>"
    return None


def _children(value: Value) -> tuple[Value, ...] | None:
    if isinstance(value, (VList, VSet)):
        return tuple(value.items)
    if isinstance(value, VMap):
        return tuple(item for pair in value.items for item in pair)
    if isinstance(value, (VRecord, VChoice)):
        return tuple(value.fields)
    return None


def _show_float(value: float) -> str:
    if math.isnan(value):
        return "Float.nan"
    if math.isinf(value):
        return "-Float.infinity" if value < 0 else "Float.infinity"
    if value == 0.0:
        return "-0.0" if math.copysign(1.0, value) < 0 else "0.0"
    # The shortest form that reads back as the same float; 17 digits always does.
    for precision in range(1, 18):
        text = format(value, f".{precision}g").replace("E", "e")
        if float(text) == value:
            return _normalize_float_text(text)
    return _normalize_float_text(format(value, ".17g").replace("E", "e"))


def _normalize_float_text(text: str) -> str:
    if "e" in text:
        mantissa, exponent = text.split("e", 1)
        sign = ""
        if exponent.startswith(("+", "-")):
            sign = "-" if exponent[0] == "-" else ""
            exponent = exponent[1:]
        exponent = str(int(exponent))
        text = f"{mantissa}e{sign}{exponent}"
    if "." not in text and "e" not in text:
        text += ".0"
    return text


def _show_text(value: str) -> str:
    parts = ['"']
    for char in value:
        code = ord(char)
        if char == "\\":
            parts.append("\\\\")
        elif char == '"':
            parts.append('\\"')
        elif char == "\n":
            parts.append("\\n")
        elif char == "\t":
            parts.append("\\t")
        elif char == "\r":
            parts.append("\\r")
        elif code < 0x20 or code == 0x7F:
            parts.append(f"\\u{{{code:x}}}")
        else:
            parts.append(char)
    parts.append('"')
    return "".join(parts)
