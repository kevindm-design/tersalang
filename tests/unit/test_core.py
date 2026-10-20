# SPDX-License-Identifier: Apache-2.0
"""Unit checks for integers, show, fuel, and the grammars."""

from __future__ import annotations

from pathlib import Path

import yaml
from lark import Lark

from tersalang.diagnostics import EXTRA_CODES
from tersalang.integers import IntCapExceeded, div_int, mul_int, pow_int
from tersalang.lexer import lex_text
from tersalang.limits import LimitConfig, Meter
from tersalang.parser import parse_module
from tersalang.show import show
from tersalang.values import (
    VBytes,
    VChoice,
    VFloat,
    VFunc,
    VInt,
    VList,
    VMutableList,
    VMutableMap,
    VRecord,
    VResource,
    VText,
)

ROOT = Path(__file__).resolve().parents[2]


def test_mul_precheck_does_not_build_the_value() -> None:
    try:
        mul_int(1 << 40000, 1 << 40000, 65536)
    except IntCapExceeded:
        return
    raise AssertionError("expected the cap")


def test_pow_precheck() -> None:
    assert pow_int(2, 10, 65536) == 1024
    try:
        pow_int(2, 10_000_000, 65536)
    except IntCapExceeded:
        return
    raise AssertionError("expected the cap")


def test_floor_div() -> None:
    assert div_int(-7, 3, 65536) == -3
    assert div_int(7, 3, 65536) == 2


def test_show_float_and_text() -> None:
    assert show(VFloat(float("nan"))) == "Float.nan"
    assert show(VFloat(float("-0.0"))) == "-0.0"
    assert show(VText("a\tb")) == '"a\\tb"'
    assert show(VBytes(b"\x0a\xff")) == 'Bytes.of_hex("0aff")'
    assert len(show(VInt(1 << 20000))) > 4000
    function = VFunc("f", (), None, {})
    assert show(function) == "<function>"
    assert show(VResource("File", "a.txt")) == "<resource>"
    assert show(VMutableList()) == "<mutable>"
    assert show(VMutableMap()) == "<mutable>"
    assert show(VList((function,))) == "<value>"
    assert show(VRecord("Box", ("f",), (function,))) == "<value>"
    assert show(VChoice("Wrap", "Some", (function,))) == "<value>"
    assert show(VList((VList((VInt(1), VInt(2))), VList((VInt(3),))))) == "[[1, 2], [3]]"


def test_fuel_stops() -> None:
    meter = Meter(LimitConfig(fuel=2))
    meter.charge_fuel(1)
    try:
        meter.charge_fuel(2)
    except Exception as exc:
        assert exc.__class__.__name__ == "FuelExhausted"
        return
    raise AssertionError("expected fuel exhaustion")


def test_lark_is_conflict_free() -> None:
    Lark((ROOT / "spec" / "tersa.lark").read_text(encoding="utf-8"), parser="lalr", start="file")


def test_diagnostics_cover_extra_codes() -> None:
    catalog = yaml.safe_load((ROOT / "spec" / "diagnostics.yaml").read_text(encoding="utf-8"))
    missing = [code for code in EXTRA_CODES if code not in catalog["codes"]]
    assert missing == []


def test_lexer_recovers() -> None:
    _source, _tokens, diagnostics = lex_text("sample.tersa", "module sample\nlet x = %\n")
    assert any(item.code == "E0030" for item in diagnostics)


def test_unicode_digit_does_not_crash_the_lexer() -> None:
    # Python str.isdigit() is true for ². Grammar digits are ASCII 0-9.
    _source, tokens, _diagnostics = lex_text("sample.tersa", "1²")
    assert tokens[0].kind == "int"
    assert tokens[0].text == "1"


def test_parse_hello() -> None:
    text = (ROOT / "examples" / "hello.tersa").read_text(encoding="utf-8")
    source, tokens, diagnostics = lex_text("hello.tersa", text)
    module = parse_module(source, tokens, diagnostics)
    assert module is not None
    assert not any(item.severity == "error" for item in diagnostics)
