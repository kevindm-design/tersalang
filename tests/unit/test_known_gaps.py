# SPDX-License-Identifier: Apache-2.0
"""Checker and runtime edge cases, each pinned by a regression test."""

from __future__ import annotations

from tersalang.driver import check_text, run_tests


def _codes_and_places(name: str, source: str) -> list[tuple[str, int, int]]:
    outcome = check_text(name, source)
    return [(item.code, item.span.start_line, item.span.start_col) for item in outcome.diagnostics]


NONE_IN_REQUIRES = """module none_in_requires

function first(xs: List[Int]) returns Int
  requires xs.get(0) != None
do
  return xs.get(0).unwrap_or(0)
end
"""


def test_none_takes_its_type_from_the_other_operand() -> None:
    assert _codes_and_places("none_in_requires.tersa", NONE_IN_REQUIRES) == []


def test_none_with_no_context_is_reported_where_it_is_written() -> None:
    source = "module bare\n\nfunction main() returns Unit\ndo\n  let x = None\n  return\nend\n"
    assert _codes_and_places("bare.tersa", source) == [("E3010", 5, 11)]


def test_a_generic_case_with_no_context_is_reported_where_it_is_written() -> None:
    source = """module bare_case

choice Slot[T]
  case Empty
  case Held(value: T)
end

function main() returns Unit
do
  let x = Empty
  return
end
"""
    assert _codes_and_places("bare_case.tersa", source) == [("E3010", 10, 11)]


def test_both_sides_without_context_still_need_one() -> None:
    source = (
        "module both\n\nfunction main() returns Unit\ndo\n  let x = None == None\n  return\nend\n"
    )
    assert _codes_and_places("both.tersa", source) == [("E3010", 5, 11), ("E3010", 5, 19)]


DEFAULT_IN_GENERIC_CODE = """module default_dispatch

interface Default[T]
  function default() returns T
end

implements Default[Int]
  function default() returns Int
  do
    return 0
  end
end

function make[T: Default]() returns T
do
  return default()
end

function zero() returns Int
do
  return default()
end
"""


def test_return_only_dispatch_in_generic_code_is_a_clear_e3010() -> None:
    outcome = check_text("default_dispatch.tersa", DEFAULT_IN_GENERIC_CODE)
    (item,) = outcome.diagnostics
    assert (item.code, item.span.start_line, item.span.start_col) == ("E3010", 16, 10)
    assert item.message == (
        "cannot pick an implementation of `default` for type parameter T: none of its "
        "parameters has type T, and types are not available at run time"
    )
    assert item.fix is not None
    assert item.fix.description == (
        "call `default` where T is a concrete type, or give it a parameter of type T"
    )


def test_return_only_dispatch_with_a_concrete_expected_type_runs() -> None:
    generic = "function make[T: Default]() returns T\ndo\n  return default()\nend\n\n"
    source = DEFAULT_IN_GENERIC_CODE.replace(generic, "")
    source += '\ntest "zero is the Int default"\ndo\n  expect zero() == 0\nend\n'
    outcome = run_tests("default_dispatch.tersa", source)
    assert outcome.exit_code == 0, outcome.stderr
    assert outcome.stdout.endswith("1 test passed, 0 doc examples passed\n")


CONSTRAINED_TYPES = """module constrained_types

record Keyed[K: Hashable, V]
  key: K
  value: V
end

choice Ranked[T: Comparable]
  case Unranked
  case Best(item: T)
end

record Shady[T: Nope]
  item: T
end

function written() returns Keyed[Float, Int]
do
  return Keyed(key = 1.5, value = 1)
end

function unconstrained[K](k: K) returns Keyed[K, Int]
do
  return Keyed(key = k, value = 1)
end

function constrained[K: Hashable](k: K) returns Keyed[K, Int]
do
  return Keyed(key = k, value = 1)
end

function ranked() returns Ranked[Int]
do
  return Best(1)
end

function unranked() returns Ranked[Bytes]
do
  return Unranked
end
"""


def test_record_and_choice_type_parameters_check_their_constraints() -> None:
    outcome = check_text("constrained_types.tersa", CONSTRAINED_TYPES)
    shown = sorted((item.code, item.span.start_line, item.message) for item in outcome.diagnostics)
    assert shown == [
        ("E3008", 13, "unknown interface `Nope`"),
        ("E3042", 17, "`Float` is not Hashable"),
        ("E3042", 19, "`Float` is not Hashable"),
        ("E3042", 24, "`K` is not Hashable"),
        ("E3046", 37, "`Bytes` does not implement `Comparable`"),
    ]
    (builtin,) = [item for item in outcome.diagnostics if item.code == "E3046"]
    assert builtin.fix is None


def test_implements_needs_the_interface_arity() -> None:
    source = """module arity

interface Solution
  function solve(n: Int) returns Int
end

interface Describable[T]
  function describe(value: T) returns Text
end

implements Solution[Int]
  function solve(n: Int) returns Int
  do
    return n
  end
end

implements Describable[Int, Text]
  function describe(value: Int) returns Text
  do
    return show(value)
  end
end

function solve(n: Int) returns Int
do
  return n + 1
end
"""
    outcome = check_text("arity.tersa", source)
    shown = [(item.code, item.span.start_line, item.message) for item in outcome.diagnostics]
    assert shown == [
        ("E3007", 11, "`Solution` takes no type parameter, so no implements block can supply it"),
        ("E3007", 18, "`Describable` expects 1 type argument"),
    ]
    assert outcome.diagnostics[0].fix is not None
    assert outcome.diagnostics[0].fix.description == "define top-level functions `solve` instead"


def test_implements_without_type_arguments_stays_a_syntax_error() -> None:
    source = "module bare\n\ninterface Solution\n  function solve(n: Int) returns Int\nend\n\nimplements Solution\nend\n"
    assert _codes_and_places("bare.tersa", source) == [("E1000", 7, 12)]
