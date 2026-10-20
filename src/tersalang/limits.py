# SPDX-License-Identifier: Apache-2.0
"""Fuel, memory units, call depth, and the integer-size cap."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

from tersalang.version import DEFAULT_MAX_DEPTH, DEFAULT_MAX_INT_BITS


def words(value: int) -> int:
    """The number of 64-bit words needed for the magnitude of `value`; 0 needs none."""
    return math.ceil(value.bit_length() / 64)


@dataclass
class LimitConfig:
    """Limits the host sets for one run. `None` means that limit is not enforced.

    `wall_ms` is the in-process wall-clock backstop in milliseconds; `output_bytes` caps
    console output in UTF-8 bytes.
    """

    fuel: int | None = None
    memory_units: int | None = None
    max_int_bits: int = DEFAULT_MAX_INT_BITS
    max_depth: int = DEFAULT_MAX_DEPTH
    output_bytes: int | None = None
    wall_ms: int | None = None


class FuelExhausted(Exception):
    """The run used more fuel than `LimitConfig.fuel` allows (trap `T6201`)."""


class MemoryExhausted(Exception):
    """The run allocated more memory units than `LimitConfig.memory_units` (trap `T6202`)."""


@dataclass
class Meter:
    """Running totals of fuel, memory units, call depth, and output for one run.

    Memory units count cumulative allocation and are never refunded.
    """

    config: LimitConfig
    fuel_used: int = 0
    memory_used: int = 0
    depth: int = 0
    output_used: int = 0
    output_truncated: bool = False
    wall_deadline: float | None = None

    def charge_fuel(self, amount: int) -> None:
        """Spend `amount` fuel, raising `FuelExhausted` past the limit.

        The wall-clock deadline is checked first, on every call, so even a zero charge can
        raise `WallClockExceeded`. On exhaustion `fuel_used` is pinned to the limit.
        """
        if self.wall_deadline is not None and time.monotonic() >= self.wall_deadline:
            raise WallClockExceeded
        if amount <= 0:
            return
        if self.config.fuel is not None and self.fuel_used + amount > self.config.fuel:
            self.fuel_used = self.config.fuel
            raise FuelExhausted
        self.fuel_used += amount

    def charge_memory(self, amount: int) -> None:
        """Spend `amount` memory units, raising `MemoryExhausted` past the limit.

        On exhaustion `memory_used` is pinned to the limit.
        """
        if amount <= 0:
            return
        if (
            self.config.memory_units is not None
            and self.memory_used + amount > self.config.memory_units
        ):
            self.memory_used = self.config.memory_units
            raise MemoryExhausted
        self.memory_used += amount

    def charge_int_op(self, op: str, left: int, right: int) -> None:
        """Extra fuel for an `Int` operation on an operand wider than 64 bits.

        Linear operations (`+`, `-`, `neg`, `cmp`) cost the larger word count; every other
        `op` costs the product of the word counts. Operands within 64 bits cost nothing here.
        """
        if left.bit_length() <= 64 and right.bit_length() <= 64:
            return
        if op in {"+", "-", "neg", "cmp"}:
            extra = max(words(left), words(right))
        else:
            extra = words(left) * words(right)
        self.charge_fuel(extra)

    def charge_int_value(self, value: int) -> None:
        """Memory units for an `Int` result wider than 64 bits: one per 64-bit word."""
        if value.bit_length() > 64:
            self.charge_memory(words(value))

    def charge_text(self, value: str) -> None:
        """Memory units for a `Text` value: one plus one per started 8 bytes of UTF-8."""
        size = len(value.encode("utf-8"))
        self.charge_memory(1 + math.ceil(size / 8))

    def charge_bytes(self, value: bytes) -> None:
        """Memory units for a `Bytes` value: one plus one per started 8 bytes."""
        self.charge_memory(1 + math.ceil(len(value) / 8))

    def enter(self) -> None:
        """Count one more call frame, raising `RecursionLimit` past `max_depth`."""
        self.depth += 1
        if self.depth > self.config.max_depth:
            raise RecursionLimit

    def leave(self) -> None:
        """Pop the call frame counted by `enter`."""
        self.depth -= 1

    def write_output(self, text: str) -> str:
        """The part of `text` that fits in the remaining output budget.

        Anything cut sets `output_truncated`. The cut falls on a byte boundary and a
        partial UTF-8 sequence at the end is dropped.
        """
        data = text.encode("utf-8")
        if self.config.output_bytes is None:
            self.output_used += len(data)
            return text
        room = self.config.output_bytes - self.output_used
        if room <= 0:
            self.output_truncated = True
            return ""
        if len(data) <= room:
            self.output_used += len(data)
            return text
        self.output_truncated = True
        self.output_used = self.config.output_bytes
        return data[:room].decode("utf-8", errors="ignore")


class RecursionLimit(Exception):
    """The call depth went past `LimitConfig.max_depth` (trap `T6203`)."""


class WallClockExceeded(Exception):
    """The wall-clock backstop fired.

    A candidate episode scores this as T6208. Measuring the reference keeps
    I9013 on that reference episode, so a stopped reference is not a yardstick.
    `tersa harness validate` then fails its gate and exits 1. `tersa harness run`
    falls back to the declared or limit basis with `E_basis_reason`
    `reference_did_not_execute`.
    """


def in_process_wall_message(wall_ms: int | None) -> str:
    """Diagnostic text for a `WallClockExceeded` raised inside this process."""
    amount = 0 if wall_ms is None else wall_ms
    return f"in-process wall-clock backstop reached ({amount:g} ms)"


def child_wall_message(timeout_s: float) -> str:
    """Diagnostic text for a child process stopped at the harness timeout (`T6208`)."""
    return f"child process wall-clock backstop reached ({timeout_s:g} s)"
