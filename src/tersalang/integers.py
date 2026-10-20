# SPDX-License-Identifier: Apache-2.0
"""Integer arithmetic. The size cap is checked before an expensive operation."""

from __future__ import annotations

INT64_MIN = -9223372036854775808
INT64_MAX = 9223372036854775807


class IntCapExceeded(Exception):
    """The exact result needs more bits than the run allows (trap `T6204`)."""


class Int64Overflow(Exception):
    """Fixed-width overflow (trap `T6001`). `Int64` never wraps."""


class DivisionByZero(Exception):
    """A `div` or `mod` with a zero divisor (trap `T6002`)."""


def check_int(value: int, limit: int) -> int:
    """`value` unchanged, or `IntCapExceeded` if its magnitude needs more than `limit` bits."""
    if value.bit_length() > limit:
        raise IntCapExceeded
    return value


def add_int(left: int, right: int, limit: int) -> int:
    """`left + right`, capped at `limit` bits."""
    return check_int(left + right, limit)


def sub_int(left: int, right: int, limit: int) -> int:
    """`left - right`, capped at `limit` bits."""
    return check_int(left - right, limit)


def neg_int(value: int, limit: int) -> int:
    """`-value`, capped at `limit` bits."""
    return check_int(-value, limit)


def mul_int(left: int, right: int, limit: int) -> int:
    """Trap before multiplying when the result is certain to exceed the cap."""
    if left == 0 or right == 0:
        return 0
    left_bits = left.bit_length()
    right_bits = right.bit_length()
    if left_bits + right_bits - 1 > limit:
        raise IntCapExceeded
    if left_bits + right_bits <= limit:
        return left * right
    return check_int(left * right, limit)


def pow_int(base: int, exponent: int, limit: int) -> int:
    """`base` to the power `exponent`, capped at `limit` bits; `pow(0, 0)` is 1.

    A negative exponent raises `ValueError`. A result certain to exceed the cap raises
    `IntCapExceeded` before any multiplication; a borderline one is built by squaring, so
    each intermediate product is checked as it grows.
    """
    if exponent < 0:
        raise ValueError("pow exponent must be non-negative")
    magnitude = abs(base)
    if magnitude <= 1:
        if base == 0:
            return 0 if exponent > 0 else 1
        if base == 1 or exponent % 2 == 0:
            return 1
        return -1
    bits = magnitude.bit_length()
    if (bits - 1) * exponent + 1 > limit:
        raise IntCapExceeded
    if bits * exponent <= limit:
        return check_int(pow(base, exponent), limit)
    result = 1
    factor = base
    remaining = exponent
    while remaining:
        if remaining & 1:
            result = mul_int(result, factor, limit)
        remaining >>= 1
        if remaining:
            factor = mul_int(factor, factor, limit)
    return result


def div_int(left: int, right: int, limit: int) -> int:
    """Floored quotient of `left` by `right`, capped at `limit` bits; 0 raises `DivisionByZero`."""
    if right == 0:
        raise DivisionByZero
    return check_int(left // right, limit)


def mod_int(left: int, right: int, limit: int) -> int:
    """Floored remainder of `left` by `right`, signed like `right`; 0 raises `DivisionByZero`."""
    if right == 0:
        raise DivisionByZero
    return check_int(left % right, limit)


def _fit64(value: int) -> int:
    if value < INT64_MIN or value > INT64_MAX:
        raise Int64Overflow
    return value


def add64(left: int, right: int) -> int:
    """`Int64` addition; raises `Int64Overflow` outside the 64-bit range."""
    return _fit64(left + right)


def sub64(left: int, right: int) -> int:
    """`Int64` subtraction; raises `Int64Overflow` outside the 64-bit range."""
    return _fit64(left - right)


def mul64(left: int, right: int) -> int:
    """`Int64` multiplication; raises `Int64Overflow` outside the 64-bit range."""
    return _fit64(left * right)


def neg64(value: int) -> int:
    """`Int64` negation; `-Int64.min` raises `Int64Overflow`."""
    return _fit64(-value)


def div64(left: int, right: int) -> int:
    """`Int64` floored quotient. Zero raises `DivisionByZero`; `Int64.min div -1` overflows."""
    if right == 0:
        raise DivisionByZero
    return _fit64(left // right)


def mod64(left: int, right: int) -> int:
    """`Int64` floored remainder, signed like `right`; 0 raises `DivisionByZero`."""
    if right == 0:
        raise DivisionByZero
    # The floored remainder always fits. `Int64.min mod -1` is 0 even though
    # `Int64.min div -1` traps (§5.2a).
    return left % right
