# SPDX-License-Identifier: Apache-2.0
"""An attempt's functions must match interface.tersa (E3047, I9025; design §22.1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tersalang.cli import main
from tersalang.harness import (
    WITHHELD_MESSAGE,
    TaskLoadError,
    _parse,
    agent_view,
    load_task,
    run_episode,
)
from tersalang.result_schema import schema_errors
from tersalang.task_interface import signature_diagnostics

INTERFACE = """module task_spec

interface Solution
  function add_one(n: Int) returns Int
    ensures result == n + 1
end
"""

HIDDEN = """module tests

test "h_secret_one"
do
  expect add_one(4173) == 4174
end
"""

RIGHT = "module attempt\n\nfunction add_one(n: Int) returns Int\ndo\n  return n + 1\nend\n"


def _task(
    root: Path, *, interface: str = INTERFACE, reference: str = RIGHT, credit: float = 0.25
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "task.toml").write_text(
        'id = "sig"\nlanguage = "0.1"\neffects = ["Console"]\n\n[limits]\nfuel = 100000\nmemory_units = 100000\n\n'
        f'[reward]\ncheck_credit = {credit}\nefficiency_weight = 0.0\n\n[seeds]\nproperty_seed_policy = "fixed"\nfixed_seed = 0\n',
        encoding="utf-8",
    )
    (root / "prompt.md").write_text("Add one.\n", encoding="utf-8")
    (root / "interface.tersa").write_text(interface, encoding="utf-8")
    (root / "hidden").mkdir()
    (root / "hidden" / "tests.tersa").write_text(HIDDEN, encoding="utf-8")
    (root / "reference").mkdir()
    (root / "reference" / "solution.tersa").write_text(reference, encoding="utf-8")
    return root


def _messages(attempt: str, interface: str) -> list[str]:
    module, diagnostics = _parse("attempt.tersa", attempt)
    required, parsed = _parse("interface.tersa", interface)
    assert module is not None and required is not None and not diagnostics and not parsed
    found = signature_diagnostics(module, required)
    assert {item.code for item in found} <= {"E3047"}
    return [item.message for item in found]


@pytest.mark.parametrize(
    ("attempt", "message"),
    [
        (
            "module attempt\n\nfunction add_one(n: Text) returns Int\ndo\n  return 1\nend\n",
            "`add_one` does not match interface.tersa: parameter 1 (`n`) is `Text`, the interface says `Int`",
        ),
        (
            "module attempt\n\nfunction add_one(n: Int) returns Text\ndo\n  return show(n)\nend\n",
            "`add_one` does not match interface.tersa: it returns `Text`, the interface says `Int`",
        ),
        (
            "module attempt\n\nfunction add_one(n: Int, m: Int) returns Int\ndo\n  return n + m\nend\n",
            "`add_one` does not match interface.tersa: it takes 2 parameters, the interface takes 1",
        ),
        (
            "module attempt\n\nfunction add_one[T](n: Int) returns Int\ndo\n  return n\nend\n",
            "`add_one` does not match interface.tersa: it has 1 type parameter, the interface has 0",
        ),
        (
            "module attempt\n\nfunction plus_one(n: Int) returns Int\ndo\n  return n + 1\nend\n",
            "no function `add_one`; interface.tersa requires `function add_one(n: Int) returns Int`",
        ),
    ],
)
def test_each_kind_of_mismatch_names_the_difference(attempt: str, message: str) -> None:
    assert _messages(attempt, INTERFACE) == [message]


def test_names_public_contracts_and_effects_are_not_compared() -> None:
    attempt = """module attempt

import std.console exposing print

public function add_one(value: Int) returns Int
  uses Console
  ensures true
do
  print("hi")
  return value + 1
end
"""
    assert _messages(attempt, INTERFACE) == []


def test_type_parameters_match_by_position_with_their_constraints() -> None:
    interface = """module task_spec

function smallest[T: Comparable](xs: List[T], fallback: T) returns T
do
  return fallback
end
"""
    renamed = """module attempt

function smallest[U: Comparable](xs: List[U], fallback: U) returns U
do
  return fallback
end
"""
    assert _messages(renamed, interface) == []
    unconstrained = renamed.replace("[U: Comparable]", "[U]")
    assert _messages(unconstrained, interface) == [
        "`smallest` does not match interface.tersa: type parameter `U` should be `T: Comparable`"
    ]
    concrete = renamed.replace("xs: List[U]", "xs: List[Int]")
    assert _messages(concrete, interface) == [
        "`smallest` does not match interface.tersa: parameter 1 (`xs`) is `List[Int]`, "
        "the interface says `List[T]`"
    ]


def test_a_generic_interface_lends_its_type_parameters_to_its_functions() -> None:
    interface = "module task_spec\n\ninterface Picker[T]\n  function pick(xs: List[T]) returns Option[T]\nend\n"
    attempt = "module attempt\n\nfunction pick[A](xs: List[A]) returns Option[A]\ndo\n  return xs.get(0)\nend\n"
    assert _messages(attempt, interface) == []


def test_a_mismatch_scores_zero_and_keeps_its_detail_for_the_agent(tmp_path: Path) -> None:
    task = load_task(_task(tmp_path))
    source = "module attempt\n\nfunction add_one(n: Text) returns Int\ndo\n  return 1\nend\n"
    episode = run_episode(task, source, attempt_id="t", seed=0)
    assert episode.stage_reached == "check"
    assert episode.correctness == 0.0
    assert episode.reward == 0.0
    assert [item.code for item in episode.diagnostics] == ["E3047"]
    assert episode.attempt_diagnostics == 1
    assert (episode.total, episode.passed, episode.failed) == (1, 0, 1)
    view = agent_view(episode)
    diagnostics = view["diagnostics"]
    assert isinstance(diagnostics, list) and isinstance(diagnostics[0], dict)
    assert diagnostics[0]["message"] != WITHHELD_MESSAGE
    assert "the interface says `Int`" in diagnostics[0]["message"]
    assert diagnostics[0]["related"][0]["file"] == "interface.tersa"
    assert "4173" not in json.dumps(view)
    assert schema_errors(view) == []


def test_a_check_error_beside_a_mismatch_still_scores_zero(tmp_path: Path) -> None:
    task = load_task(_task(tmp_path))
    source = "module attempt\n\nfunction add_one(n: Int) returns Text\ndo\n  return n\nend\n"
    episode = run_episode(task, source, attempt_id="t", seed=0)
    assert {item.code for item in episode.diagnostics} == {"E3033", "E3047"}
    assert episode.reward == 0.0


def test_a_matching_attempt_still_scores_one(tmp_path: Path) -> None:
    episode = run_episode(load_task(_task(tmp_path)), RIGHT, attempt_id="t", seed=0)
    assert episode.reward == 1.0


def test_a_reference_that_does_not_match_fails_to_load(tmp_path: Path) -> None:
    wrong = RIGHT.replace("returns Int", "returns Float").replace("n + 1", "1.0")
    root = _task(tmp_path, reference=wrong)
    with pytest.raises(TaskLoadError) as raised:
        load_task(root)
    assert raised.value.code == "I9025"
    assert raised.value.message == (
        "reference/solution.tersa: `add_one` does not match interface.tersa: "
        "it returns `Float`, the interface says `Int`"
    )


def test_the_cli_refuses_a_task_whose_reference_does_not_match(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _task(tmp_path / "task", reference=RIGHT.replace("add_one", "plus_one"))
    attempt = tmp_path / "attempt.tersa"
    attempt.write_text(RIGHT, encoding="utf-8")
    assert (
        main(["harness", "run", str(root), "--attempt", str(attempt), "--isolation", "none"]) == 4
    )
    assert "I9025" in capsys.readouterr().err
