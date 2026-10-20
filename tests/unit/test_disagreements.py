# SPDX-License-Identifier: Apache-2.0
"""Points where the code once disagreed with the spec, settled in favor of the spec."""

from __future__ import annotations

import json

from tersalang.driver import run_tests, run_text

BANK = """module bank

public function withdraw(balance: Int, amount: Int) returns Int
  requires amount > 0
  requires amount <= balance
  ensures result == old(balance) - amount
  ensures result >= 0
do
  return balance - amount
end

function main() returns Unit
do
  let left = withdraw(10, 50)
  return
end
"""


def test_failed_requires_matches_reference_17_2() -> None:
    outcome = run_text("bank.tersa", BANK, as_json=True)
    assert outcome.exit_code == 2
    (trap,) = json.loads(outcome.stdout)
    assert trap["code"] == "T6101"
    assert trap["category"] == "contract"
    assert trap["message"] == "precondition failed: amount <= balance"
    assert trap["span"] == {"start": {"line": 5, "column": 12}, "end": {"line": 5, "column": 29}}
    assert [item["message"] for item in trap["related"]] == ["called from here"]
    assert trap["related"][0]["span"]["start"] == {"line": 14, "column": 14}
    assert trap["blame"] == "caller"
    assert trap["values"] == {"amount": "50", "balance": "10"}


def test_failed_requires_human_layout_follows_design_18_1() -> None:
    outcome = run_text("bank.tersa", BANK)
    assert outcome.stderr.splitlines() == [
        "trap[T6101]: precondition failed: amount <= balance",
        "  --> bank.tersa:5:12",
        "  = called from here (bank.tersa:14:14)",
        "  = blame: caller",
        "  = amount = 50",
        "  = balance = 10",
    ]


def test_failed_ensures_and_invariant_quote_the_condition_and_values() -> None:
    src = """module post

record Rect
  width: Int
  invariant width >= 0
end

function shrink(r: Rect, by: Int) returns Int
  ensures result == old(r.width) - by
do
  return r.width - by + 1
end

function main() returns Unit
do
  let n = shrink(Rect(width = 5), 3)
  return
end
"""
    outcome = run_text("post.tersa", src, as_json=True)
    (trap,) = json.loads(outcome.stdout)
    assert trap["code"] == "T6102"
    assert trap["message"] == "postcondition failed: result == old(r.width) - by"
    assert trap["blame"] == "function"
    assert trap["values"] == {"result": "3", "old(r.width)": "5", "by": "3"}
    broken = src.replace("let n = shrink(Rect(width = 5), 3)", "let r = Rect(width = -1)")
    outcome = run_text("post.tersa", broken, as_json=True)
    (trap,) = json.loads(outcome.stdout)
    assert trap["code"] == "T6103"
    assert trap["message"] == "invariant failed: width >= 0"
    assert trap["blame"] == "constructor"
    assert trap["values"] == {"width": "-1"}
    assert [item["message"] for item in trap["related"]] == ["`Rect` built or updated here"]


def test_condition_values_skip_functions_cases_and_namespaces() -> None:
    src = """module skip

function ok(xs: List[Int], limit: Int) returns Bool
do
  return xs.length() < limit
end

function take(xs: List[Int], limit: Int) returns Option[Int]
  requires ok(xs, limit) and Int.compare(limit, 0) == Greater and limit < Int64.to_int(Int64.max)
do
  return xs.get(0)
end

function main() returns Unit
do
  let first = take([1, 2, 3], 2)
  return
end
"""
    outcome = run_text("skip.tersa", src, as_json=True)
    (trap,) = json.loads(outcome.stdout)
    assert trap["code"] == "T6101"
    assert trap["values"] == {"xs": "[1, 2, 3]", "limit": "2"}


INVENTORY_TESTS = """module inventory

## Example: double(2) == 4
function double(n: Int) returns Int
do
  return n * 2
end

test "one"
do
  expect double(1) == 2
end

test "two"
do
  expect double(2) == 4
end

test "three"
do
  expect double(3) == 6
end

test "four"
do
  expect double(0) == 0
end
"""


def test_tersa_test_prints_the_summary_line_of_reference_19() -> None:
    outcome = run_tests("inventory.tersa", INVENTORY_TESTS)
    assert outcome.exit_code == 0
    assert outcome.stdout == "4 tests passed, 1 doc example passed\n"


def test_tersa_test_summary_counts_failures_and_singulars() -> None:
    src = INVENTORY_TESTS.replace("double(3) == 6", "double(3) == 7").replace(
        "double(2) == 4\nfunction", "double(2) == 5\nfunction"
    )
    outcome = run_tests("inventory.tersa", src)
    assert outcome.exit_code == 1
    assert (
        outcome.stdout
        == "3 tests passed, 1 test failed, 0 doc examples passed, 1 doc example failed\n"
    )
    assert [item.code for item in outcome.diagnostics] == ["T6031", "T6031"]


def test_tersa_test_summary_matches_the_failure_line_in_reference_19() -> None:
    one_failed = run_tests(
        "inventory.tersa", INVENTORY_TESTS.replace("double(3) == 6", "double(3) == 7")
    )
    assert one_failed.exit_code == 1
    assert one_failed.stdout == "3 tests passed, 1 test failed, 1 doc example passed\n"
    trapped = run_tests(
        "inventory.tersa", INVENTORY_TESTS.replace("double(3) == 6", "1 div 0 == 6")
    )
    assert trapped.exit_code == 1
    assert trapped.stdout == "3 tests passed, 1 test failed, 1 doc example passed\n"
    assert [item.code for item in trapped.diagnostics] == ["T6002"]


def test_tersa_test_summary_follows_program_output_and_is_not_in_json() -> None:
    src = INVENTORY_TESTS.replace('test "one"\ndo\n', 'test "one"\ndo\n  print("hi")\n').replace(
        "module inventory\n", "module inventory\n\nimport std.console exposing print\n"
    )
    outcome = run_tests("inventory.tersa", src, grants={"Console": []})
    assert outcome.stdout == "hi\n4 tests passed, 1 doc example passed\n"
    as_json = run_tests("inventory.tersa", INVENTORY_TESTS, as_json=True)
    assert as_json.stdout == "[]\n"


IGNORED = """module warn

#fmt:skip
function seven() returns Option[Int]
do
  return Some(7)
end

function main() returns Unit
do
  seven()
  let n = 1 div zero
  return
end

let zero: Int = 0
"""


def test_run_reports_warnings_alongside_a_trap() -> None:
    outcome = run_text("warn.tersa", IGNORED, as_json=True)
    assert outcome.exit_code == 2
    assert [item["code"] for item in json.loads(outcome.stdout)] == ["T6002", "W3001", "W1104"]
    human = run_text("warn.tersa", IGNORED)
    assert "warning[W3001]" in human.stderr
    assert "warning[W1104]" in human.stderr


def test_run_reports_warnings_alongside_a_check_error() -> None:
    src = IGNORED.replace("let n = 1 div zero", 'let n: Int = "x"')
    outcome = run_text("warn.tersa", src, as_json=True)
    assert outcome.exit_code == 3
    codes = [item["code"] for item in json.loads(outcome.stdout)]
    assert "W3001" in codes and "W1104" in codes and "E3000" in codes


def test_successful_run_does_not_print_warnings() -> None:
    src = IGNORED.replace("let n = 1 div zero", "let n = 1 div 1")
    outcome = run_text("warn.tersa", src)
    assert outcome.exit_code == 0
    assert outcome.stderr == ""
    assert run_text("warn.tersa", src, as_json=True).stdout == "[]\n"
