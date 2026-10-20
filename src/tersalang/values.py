# SPDX-License-Identifier: Apache-2.0
"""Runtime values. Maps and sets keep insertion order."""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from typing import Any, cast

# The one NaN bit pattern, so bit-level results such as `Float.same` never vary between machines.
CANON_NAN = cast(float, struct.unpack(">d", bytes.fromhex("7ff8000000000000"))[0])


def canon_float(value: float) -> float:
    """`value`, with any NaN replaced by `CANON_NAN`."""
    if math.isnan(value):
        return CANON_NAN
    return value


# The classes below plus the function values defined in `tersalang.eval`.
Value = Any


@dataclass(frozen=True)
class VInt:
    """An `Int`. Python ints are unbounded; the evaluator enforces the run's size cap."""

    value: int


@dataclass(frozen=True)
class VInt64:
    """An `Int64`. `value` always fits in a signed 64-bit integer."""

    value: int


@dataclass(frozen=True)
class VFloat:
    """A `Float`. Every NaN is stored as `CANON_NAN`."""

    value: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", canon_float(self.value))


@dataclass(frozen=True)
class VBool:
    """A `Bool`."""

    value: bool


@dataclass(frozen=True)
class VText:
    """A `Text`."""

    value: str


@dataclass(frozen=True)
class VBytes:
    """A `Bytes`."""

    value: bytes


@dataclass(frozen=True)
class VUnit:
    """The `Unit` value."""


@dataclass(frozen=True)
class VList:
    """A `List`."""

    items: tuple[Value, ...]


@dataclass(frozen=True)
class VMap:
    """A `Map` as `(key, value)` pairs in insertion order, with no repeated key."""

    items: tuple[tuple[Value, Value], ...]


@dataclass(frozen=True)
class VSet:
    """A `Set` as its elements in insertion order, with no repeated element."""

    items: tuple[Value, ...]


@dataclass
class VMutableList:
    """A `MutableList`, changed in place."""

    items: list[Value] = field(default_factory=list)


@dataclass
class VMutableMap:
    """A `MutableMap` as `(key, value)` pairs, changed in place.

    `insert` on an existing key moves the pair to the end.
    """

    items: list[tuple[Value, Value]] = field(default_factory=list)


@dataclass(frozen=True)
class VRecord:
    """A record value. `names` and `fields` are parallel tuples."""

    type_name: str
    names: tuple[str, ...]
    fields: tuple[Value, ...]

    def get(self, name: str) -> Value:
        """The field called `name`; raises `ValueError` if the record has none."""
        return self.fields[self.names.index(name)]


@dataclass(frozen=True)
class VChoice:
    """A choice value, including `Option`, `Result`, and `Ordering`; `fields` is the payload."""

    type_name: str
    case: str
    fields: tuple[Value, ...]


@dataclass
class VFunc:
    """A function value: parameter names, body, and the bindings it captured."""

    name: str
    params: tuple[str, ...]
    body: object
    captured: dict[str, Value]
    contracts: tuple[object, ...] = ()
    invariants: tuple[object, ...] = ()


@dataclass
class VResource:
    """An open resource such as a `File`; `closed` is set when its `using` block exits.

    A file's lines are read when it opens; `index` is the next line `read_line` returns.
    """

    kind: str
    path: str
    closed: bool = False
    lines: list[str] = field(default_factory=list)
    index: int = 0


def equal(left: Value, right: Value) -> bool:
    """Tersalang `==`: structural, and false for values of different classes.

    Floats follow IEEE, so NaN is not equal to itself. Map and set equality ignore order. Mutable
    collections, functions, and resources are never equal, not even to themselves.
    """
    if type(left) is not type(right):
        return False
    if isinstance(left, VFloat) and isinstance(right, VFloat):
        return bool(left.value == right.value)
    if isinstance(left, VList) and isinstance(right, VList):
        return len(left.items) == len(right.items) and all(
            equal(a, b) for a, b in zip(left.items, right.items, strict=True)
        )
    if isinstance(left, VMap) and isinstance(right, VMap):
        if len(left.items) != len(right.items):
            return False
        for key, value in left.items:
            found = False
            for other_key, other_value in right.items:
                if equal(key, other_key):
                    found = equal(value, other_value)
                    break
            if not found:
                return False
        return True
    if isinstance(left, VSet) and isinstance(right, VSet):
        if len(left.items) != len(right.items):
            return False
        return all(any(equal(item, other) for other in right.items) for item in left.items)
    if isinstance(left, VRecord) and isinstance(right, VRecord):
        return (
            left.type_name == right.type_name
            and len(left.fields) == len(right.fields)
            and all(equal(a, b) for a, b in zip(left.fields, right.fields, strict=True))
        )
    if isinstance(left, VChoice) and isinstance(right, VChoice):
        return (
            left.type_name == right.type_name
            and left.case == right.case
            and len(left.fields) == len(right.fields)
            and all(equal(a, b) for a, b in zip(left.fields, right.fields, strict=True))
        )
    if isinstance(left, VBytes) and isinstance(right, VBytes):
        return left.value == right.value
    if isinstance(left, (VInt, VInt64, VBool, VText, VUnit)):
        return bool(left.value == right.value) if not isinstance(left, VUnit) else True
    return False


def map_get(mapping: VMap | VMutableMap, key: Value) -> Value | None:
    """The value stored under `key`, or None when the map has no such key."""
    for item_key, item_value in mapping.items:
        if equal(item_key, key):
            return item_value
    return None


def map_put(
    items: tuple[tuple[Value, Value], ...] | list[tuple[Value, Value]],
    key: Value,
    value: Value,
    *,
    move_existing: bool,
) -> list[tuple[Value, Value]]:
    """A new pair list with `key` bound to `value`.

    An existing key keeps its position, or moves to the end when `move_existing` is set.
    """
    kept: list[tuple[Value, Value]] = []
    found = False
    for item_key, item_value in items:
        if equal(item_key, key):
            found = True
            if not move_existing:
                kept.append((key, value))
            continue
        kept.append((item_key, item_value))
    if not found or move_existing:
        kept.append((key, value))
    return kept


def set_has(items: tuple[Value, ...] | list[Value], value: Value) -> bool:
    """Whether any of `items` is `equal` to `value`."""
    return any(equal(item, value) for item in items)
