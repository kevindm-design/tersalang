# SPDX-License-Identifier: Apache-2.0
"""Hidden task code lives in its own namespace during the harness merge (design §22.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tersalang.harness import load_task, run_episode, validate_task

INTERFACE = """module task_spec

interface Solution
  function add_one(n: Int) returns Int
    ensures result == n + 1
end
"""

HIDDEN = """module tests

import std.math exposing abs

let expected: Int = 42

record Pair
  a: Int
  b: Int
end

choice Verdict
  case Good
  case Bad(reason: Text)
end

function agrees(got: Int, want: Int) returns Bool
do
  return got == want
end

function judge(got: Int) returns Verdict
do
  if agrees(got, expected) then
    return Good
  end
  return Bad("off")
end

test "h_const"
do
  expect agrees(add_one(41), expected)
end

test "h_record"
do
  let pair = Pair(a = 41, b = add_one(41))
  expect pair.b == expected
end

test "h_choice"
do
  match judge(add_one(abs(-41)))
    case Good then
      expect true
    case Bad(reason) then
      expect reason == "never"
  end
end
"""

RIGHT = """module solution

function add_one(n: Int) returns Int
do
  return n + 1
end
"""

WRONG = """module solution

function add_one(n: Int) returns Int
do
  return 0
end
"""

OVERRIDES = """
let expected: Int = 0

record Pair
  a: Int
end

choice Verdict
  case Good
end

function agrees(got: Int, want: Int) returns Bool
do
  return true
end

function judge(got: Int) returns Verdict
do
  return Good
end

function abs(x: Int) returns Int
do
  return 41
end
"""


def _task(
    root: Path,
    hidden: str = HIDDEN,
    *,
    interface: str = INTERFACE,
    credit: float = 0.0,
    reference: str = RIGHT,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "task.toml").write_text(
        "\n".join(
            [
                'id = "merge"',
                'language = "0.1"',
                "effects = []",
                "",
                "[limits]",
                "fuel = 100000",
                "memory_units = 100000",
                "",
                "[reward]",
                f"check_credit = {credit}",
                "efficiency_weight = 0.0",
                "",
                "[seeds]",
                'property_seed_policy = "fixed"',
                "fixed_seed = 0",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (root / "prompt.md").write_text("Add one.\n", encoding="utf-8")
    if interface:
        (root / "interface.tersa").write_text(interface, encoding="utf-8")
    (root / "hidden").mkdir()
    (root / "hidden" / "tests.tersa").write_text(hidden, encoding="utf-8")
    (root / "reference").mkdir()
    (root / "reference" / "solution.tersa").write_text(reference, encoding="utf-8")
    return root


def _score(root: Path, source: str) -> tuple[float | None, list[tuple[object, object]]]:
    episode = run_episode(
        load_task(root), source, attempt_id="t", seed=0, filename="solution.tersa"
    )
    return episode.reward, [(case["id"], case["status"]) for case in episode.cases]


def test_hidden_constants_records_choices_and_helpers_all_carry_over(tmp_path: Path) -> None:
    reward, cases = _score(_task(tmp_path), RIGHT)
    assert reward == 1.0
    assert cases == [("h_const", "passed"), ("h_record", "passed"), ("h_choice", "passed")]


def test_redefining_every_hidden_name_cannot_lift_a_wrong_answer(tmp_path: Path) -> None:
    reward, cases = _score(_task(tmp_path), WRONG + OVERRIDES)
    assert reward == 0.0
    assert "passed" not in {status for _name, status in cases}


def test_a_correct_answer_that_reuses_hidden_names_still_scores_one(tmp_path: Path) -> None:
    honest = RIGHT + OVERRIDES
    reward, cases = _score(_task(tmp_path), honest)
    assert reward == 1.0
    assert {status for _name, status in cases} == {"passed"}


def test_candidate_names_that_match_hidden_locals_do_not_break_the_check(tmp_path: Path) -> None:
    # `got`, `want`, `pair`, and `reason` are hidden locals. They used to clash (E2020)
    # and earn check_credit for a wrong answer.
    sabotage = (
        WRONG + "\nlet got: Int = 0\nlet want: Int = 0\nlet pair: Int = 0\nlet reason: Int = 0\n"
    )
    root = _task(tmp_path, credit=0.5)
    episode = run_episode(
        load_task(root), sabotage, attempt_id="t", seed=0, filename="solution.tersa"
    )
    assert episode.stage_reached == "run"
    assert episode.reward == 0.5


def test_hidden_import_keeps_its_exposed_names_when_the_candidate_imports_the_module(
    tmp_path: Path,
) -> None:
    candidate = RIGHT.replace("module solution\n", "module solution\n\nimport std.math\n")
    reward, _cases = _score(_task(tmp_path), candidate)
    assert reward == 1.0


def test_hidden_functions_win_without_an_interface(tmp_path: Path) -> None:
    root = _task(tmp_path, interface="")
    reward, _cases = _score(root, WRONG + OVERRIDES)
    assert reward == 0.0
    reward, _cases = _score(root, RIGHT + OVERRIDES)
    assert reward == 1.0


def test_hidden_values_show_with_the_names_the_task_wrote(tmp_path: Path) -> None:
    hidden = """module tests

choice Verdict
  case Good
end

record Pair
  a: Int
end

test "h_show"
do
  expect show(Good) == "Good"
  expect show(Pair(a = add_one(0))) == "Pair(a = 1)"
end
"""
    reward, _cases = _score(_task(tmp_path, hidden), RIGHT)
    assert reward == 1.0


def test_hidden_record_fields_may_match_candidate_top_level_names(tmp_path: Path) -> None:
    hidden = """module tests

record Box
  value: Int
  invariant value >= 0
end

test "h_box"
do
  expect Box(value = add_one(1)).value == 2
end
"""
    candidate = RIGHT + "\nlet value: Int = 7\n"
    reward, _cases = _score(_task(tmp_path, hidden), candidate)
    assert reward == 1.0


def test_validate_reports_the_override_attack_as_held(tmp_path: Path) -> None:
    report = validate_task(load_task(_task(tmp_path)))
    attack = report["override_attack"]
    assert isinstance(attack, dict)
    assert report["ok"] is True
    assert attack["held"] is True
    assert attack["reward"] == 1.0
    assert attack["mutants_survived"] == []
    declared = attack["declarations"]
    assert isinstance(declared, list)
    for name in ("expected", "Pair", "Verdict", "agrees", "judge", "pair", "reason"):
        assert name in declared


def test_validate_fails_a_hidden_check_that_trusts_a_candidate_owned_helper(
    tmp_path: Path,
) -> None:
    # The interface hands `agrees` to the candidate, so the hidden check trusts it.
    interface = INTERFACE.replace(
        "end\n",
        "end\n\nfunction agrees(got: Int, want: Int) returns Bool\ndo\n  return got == want\nend\n",
    )
    hidden = """module tests

test "h"
do
  expect agrees(add_one(41), 42)
end
"""
    root = _task(tmp_path, hidden, interface=interface)
    (root / "reference" / "solution.tersa").write_text(
        RIGHT
        + "\nfunction agrees(got: Int, want: Int) returns Bool\ndo\n  return got == want\nend\n",
        encoding="utf-8",
    )
    report = validate_task(load_task(root))
    assert report["ok"] is False


def test_validate_flags_a_merge_that_lets_the_attempt_reach_hidden_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tersalang.harness as harness

    real = harness.namespace_hidden

    def unnamespaced(modules, shared, candidate, suffix):  # type: ignore[no-untyped-def]
        return real(modules, shared, candidate, "")

    monkeypatch.setattr(harness, "namespace_hidden", unnamespaced)
    report = validate_task(load_task(_task(tmp_path)))
    attack = report["override_attack"]
    assert isinstance(attack, dict)
    assert attack["held"] is False
    assert report["ok"] is False


SIZED_HIDDEN = """module tests

interface Sized[T]
  function size(value: T) returns Int
    ensures result >= 0
end

record Box
  width: Int
  height: Int
end

implements Sized[Box]
  function size(value: Box) returns Int
  do
    return value.width * value.height
  end
end

implements Sized[Int]
  function size(value: Int) returns Int
  do
    if value < 0 then
      return -value
    end
    return value
  end
end

implements Comparable[Box]
  function compare(a: Box, b: Box) returns Ordering
  do
    return Int.compare(a.size(), b.size())
  end
end

function top[T: Comparable](a: T, b: T) returns T
do
  if compare(a, b) == Greater then
    return a
  end
  return b
end

function largest[T: Sized](xs: List[T]) returns Int
do
  var best = 0
  for x in xs
  do
    if size(x) > best then
      set best = size(x)
    end
  end
  return best
end

test "h_sized"
do
  let small = Box(width = 1, height = add_one(1))
  let big = Box(width = 3, height = 3)
  expect small.size() == 2
  expect largest([small, big]) == 9
  expect largest([-4, add_one(1)]) == 4
  expect compare(big, small) == Greater
  expect top(small, big) == big
  expect big.compare(small) == Greater
end
"""


def test_hidden_interfaces_and_their_implements_blocks_carry_over(tmp_path: Path) -> None:
    reward, cases = _score(_task(tmp_path, SIZED_HIDDEN), RIGHT)
    assert reward == 1.0
    assert cases == [("h_sized", "passed")]


def test_a_candidate_can_declare_the_hidden_interface_names_without_a_clash(
    tmp_path: Path,
) -> None:
    own = """
interface Sized[T]
  function size(value: T) returns Int
end

record Box
  side: Int
end

implements Sized[Box]
  function size(value: Box) returns Int
  do
    return 100
  end
end

implements Sized[Int]
  function size(value: Int) returns Int
  do
    return 100
  end
end

implements Comparable[Box]
  function compare(a: Box, b: Box) returns Ordering
  do
    return Equal
  end
end

function largest(xs: List[Int]) returns Int
do
  return 100
end
"""
    root = _task(tmp_path, SIZED_HIDDEN)
    reward, _cases = _score(root, RIGHT + own)
    assert reward == 1.0
    reward, _cases = _score(root, WRONG + own)
    assert reward == 0.0
    report = validate_task(load_task(root))
    attack = report["override_attack"]
    assert isinstance(attack, dict)
    assert attack["held"] is True
    assert "Sized" in attack["declarations"]


def test_the_candidate_keeps_its_own_interfaces_and_implements_blocks(tmp_path: Path) -> None:
    interface = """module task_spec

record Rect
  width: Int
  height: Int
end

interface Solution
  function biggest(xs: List[Rect]) returns Int
end
"""
    hidden = """module tests

test "h_big"
do
  expect biggest([Rect(width = 1, height = 2), Rect(width = 3, height = 3)]) == 9
end
"""
    candidate = """module solution

record Rect
  width: Int
  height: Int
end

interface Area[T]
  function area(value: T) returns Int
end

implements Area[Rect]
  function area(value: Rect) returns Int
  do
    return value.width * value.height
  end
end

function biggest(xs: List[Rect]) returns Int
do
  var best = 0
  for x in xs
  do
    if x.area() > best then
      set best = area(x)
    end
  end
  return best
end
"""
    root = _task(tmp_path, hidden, interface=interface, reference=candidate)
    reward, cases = _score(root, candidate)
    assert reward == 1.0
    assert cases == [("h_big", "passed")]


def test_a_hidden_implements_of_a_public_interface_for_a_public_type_is_dropped(
    tmp_path: Path,
) -> None:
    from tersalang.harness import _parse
    from tersalang.namespacing import namespace_hidden

    interface = """module task_spec

record Rect
  width: Int
  height: Int
end

interface Solution
  function first(xs: List[Rect]) returns Rect
end
"""
    hidden = """module tests

implements Comparable[Rect]
  function compare(a: Rect, b: Rect) returns Ordering
  do
    return Int.compare(b.width, a.width)
  end
end

test "h_first"
do
  let a = Rect(width = 1, height = 1)
  let b = Rect(width = 2, height = 1)
  expect first([a, b]) == a
end
"""
    candidate = """module solution

record Rect
  width: Int
  height: Int
end

implements Comparable[Rect]
  function compare(a: Rect, b: Rect) returns Ordering
  do
    return Int.compare(a.width, b.width)
  end
end

function first(xs: List[Rect]) returns Rect
  requires not List.is_empty(xs)
do
  var best = xs.at(0)
  for x in xs
  do
    if compare(x, best) == Less then
      set best = x
    end
  end
  return best
end
"""
    # Kept, the hidden block would collide with the candidate's (E3043) or reverse its sort.
    root = _task(tmp_path, hidden, interface=interface, reference=candidate)
    reward, cases = _score(root, candidate)
    assert reward == 1.0
    assert cases == [("h_first", "passed")]
    module, _diagnostics = _parse("tests.tersa", hidden)
    owner, _owned = _parse("solution.tersa", candidate)
    assert module is not None and owner is not None
    merged = namespace_hidden([module], {"Rect", "Solution", "first"}, owner, "@hidden")
    assert merged.dropped == ["ImplementsDecl Comparable[Rect]"]


NO_ENSURES = """module task_spec

interface Solution
  function add_one(n: Int) returns Int
end
"""


def test_a_hidden_helper_called_as_a_method_is_the_hidden_one(tmp_path: Path) -> None:
    hidden = """module tests

record Pair
  a: Int
end

function doubled(n: Int) returns Int
do
  return n * 2
end

function length(p: Pair) returns Int
do
  return 99
end

test "h_method"
do
  expect add_one(1).doubled() == 4
  expect [1, 2].length() == 2
  expect Pair(a = 1).length() == 99
  expect Text.concat("a", "b") == "ab"
end
"""
    hijack = WRONG + "\nfunction doubled(n: Int) returns Int\ndo\n  return 4\nend\n"
    root = _task(tmp_path, hidden, interface=NO_ENSURES)
    reward, cases = _score(root, RIGHT)
    assert reward == 1.0, cases
    reward, _cases = _score(root, hijack)
    assert reward == 0.0
