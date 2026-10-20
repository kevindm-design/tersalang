# SPDX-License-Identifier: Apache-2.0
"""The harness parent checks the child's episode against result.schema.json (RH-10)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tersalang.cli import main
from tersalang.harness import (
    _crash_episode,
    _scored_trap_episode,
    agent_view,
    child_result_problem,
    load_task,
    run_episode,
    run_episode_isolated,
)
from tersalang.result_schema import episode_problems, schema_errors

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "tasks" / "add_one"
REFERENCE = EXAMPLE / "reference" / "solution.tersa"


def _reference_body() -> dict[str, object]:
    task = load_task(EXAMPLE)
    episode = run_episode(task, task.reference_text, seed=0, filename="solution.tersa")
    return episode.to_dict()


def test_the_packaged_schema_is_the_spec_schema() -> None:
    packaged = ROOT / "src" / "tersalang" / "schemas" / "result.schema.json"
    spec = ROOT / "spec" / "schemas" / "result.schema.json"
    assert packaged.read_bytes() == spec.read_bytes()
    assert json.loads(spec.read_text(encoding="utf-8"))["$id"] == "tersa.result/0.9"


@pytest.mark.parametrize(
    "source",
    [
        "",
        "module solution\nfunction",
        "module solution\n\nfunction add_one(n: Int) returns Int\ndo\n  return true\nend\n",
        "module solution\n\nfunction add_one(n: Int) returns Int\ndo\n  return 0\nend\n",
    ],
    ids=["empty", "parse", "check", "wrong"],
)
def test_every_in_process_episode_passes_the_schema(source: str) -> None:
    task = load_task(EXAMPLE)
    episode = run_episode(task, source, seed=0, filename="solution.tersa")
    assert episode_problems(episode.to_dict()) == []
    assert schema_errors(agent_view(episode)) == []


def test_parent_built_episodes_pass_the_schema(tmp_path: Path) -> None:
    trap = _scored_trap_episode(EXAMPLE, REFERENCE, 0, "a", "T6206", "OS memory limit exceeded")
    crash = _crash_episode(EXAMPLE, REFERENCE, 0, "a", 3, "output is not JSON")
    missing = _crash_episode(tmp_path, REFERENCE, 0, "a", 3)
    for episode in (trap, crash, missing):
        assert episode_problems(episode.to_dict()) == []


def test_reference_result_is_accepted() -> None:
    text = json.dumps(_reference_body())
    assert child_result_problem(text, EXAMPLE, REFERENCE, "none") is None


@pytest.mark.parametrize(
    ("edit", "problem"),
    [
        (lambda body: body.update(reward=1.5), "$.reward is above 1"),
        (lambda body: body["breakdown"].update(C=0.5), "$.reward does not match"),
        (lambda body: body.update(reward=None), "$.reward must be null exactly"),
        (lambda body: body.pop("tests"), "$.tests is required"),
        (lambda body: body.update(extra=1), "$.extra is not allowed"),
        (lambda body: body["tests"].update(passed=5), "passed + failed + trapped"),
        (
            lambda body: body.update(schema="tersa.result/0.7"),
            '$.schema must be "tersa.result/0.9"',
        ),
        (
            lambda body: body["replay"].update(source_hash="sha256:" + "0" * 64),
            "source_hash does not match",
        ),
        (
            lambda body: body["replay"].update(task_hash="sha256:" + "0" * 64),
            "task_hash does not match",
        ),
        (lambda body: body.update(isolation="bwrap"), "$.isolation must be none"),
        (lambda body: body.update(attempt_diagnostics=1), "$.attempt_diagnostics cannot exceed"),
        (lambda body: body.pop("attempt_diagnostics"), "$.attempt_diagnostics is required"),
    ],
)
def test_forged_or_broken_child_results_are_rejected(edit, problem: str) -> None:  # type: ignore[no-untyped-def]
    body = _reference_body()
    edit(body)
    found = child_result_problem(json.dumps(body), EXAMPLE, REFERENCE, "none")
    assert found is not None
    assert problem in found


def test_text_that_is_not_json_is_rejected() -> None:
    found = child_result_problem('{"reward": 1.0', EXAMPLE, REFERENCE, "none")
    assert found is not None and found.startswith("output is not JSON")


def test_a_forged_child_result_scores_zero_as_a_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TERSALANG_HARNESS_FORGE", "1")
    body = json.loads(run_episode_isolated(EXAMPLE, REFERENCE, seed=0, isolation="none"))
    assert body["reward"] == 0.0
    assert body["infrastructure_error"] is None
    assert body["crash"]["type"] == "invalid_result"
    assert "$.task_id is required" in body["crash"]["message"]
    assert [case["status"] for case in body["tests"]["cases"]] == ["failed", "failed"]
    assert episode_problems(body) == []
    code = main(
        ["harness", "run", str(EXAMPLE), "--attempt", str(REFERENCE), "--isolation", "none"]
    )
    assert code == 0
    assert json.loads(capsys.readouterr().out)["crash"]["type"] == "invalid_result"
