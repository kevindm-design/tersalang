# SPDX-License-Identifier: Apache-2.0
"""RL task loader, hidden-test runner, and reward formula (design §22)."""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import sys
import tomllib
from dataclasses import dataclass, replace
from dataclasses import field as dataclass_field
from pathlib import Path
from typing import TypeGuard

from tersalang.ast import (
    BinaryExpr,
    Block,
    CallExpr,
    ChoiceDecl,
    ConstDecl,
    Contract,
    Decl,
    ExpectStmt,
    Expr,
    ExprStmt,
    FailStmt,
    FieldExpr,
    ForStmt,
    FunctionDecl,
    GroupExpr,
    IfStmt,
    ImplementsDecl,
    InterfaceDecl,
    LambdaExpr,
    LetStmt,
    ListExpr,
    LiteralExpr,
    MapExpr,
    MatchStmt,
    Module,
    OldExpr,
    RecordDecl,
    ReturnStmt,
    SetStmt,
    TestDecl,
    TypeExpr,
    UnaryExpr,
    UsingStmt,
    WhileStmt,
    WithExpr,
)
from tersalang.checker import check_module
from tersalang.diagnostics import Diagnostic
from tersalang.eval import Host, Interpreter
from tersalang.isolation import OsLimits
from tersalang.lexer import lex_text
from tersalang.limits import (
    FuelExhausted,
    LimitConfig,
    MemoryExhausted,
    RecursionLimit,
    WallClockExceeded,
    child_wall_message,
    in_process_wall_message,
)
from tersalang.namespacing import collect_locals, interface_names, namespace_hidden
from tersalang.parser import parse_module
from tersalang.sandbox import RL_DENIED_EFFECTS
from tersalang.source import Span, decode_source_bytes
from tersalang.task_interface import signature_diagnostics
from tersalang.typesys import EFFECTS
from tersalang.version import (
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_INT_BITS,
    DEFAULT_PROPERTY_CASES,
    DEFAULT_TEST_OUTPUT_BYTES,
    LANGUAGE_VERSION,
    RESULT_SCHEMA,
    TOOL_VERSION,
)

_LIMIT_NAMES = {"T6201": "fuel", "T6202": "memory", "T6203": "depth", "T6204": "int"}
_HARNESS_WALL_MS = 5_000


@dataclass
class ReferenceYardstick:
    """Cached reference run for one seed.

    `fuel` is set only when the reference executed and passed every hidden
    test. `reason` is why that yardstick is missing.
    """

    fuel: int | None
    reason: str | None


class TaskLoadError(Exception):
    """A task that cannot be loaded or run; `code` is its `I90xx` diagnostic code."""

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass
class Task:
    """A loaded task directory: its `task.toml` settings and the text of its files.

    `hidden` holds `(filename, text)` for each hidden test file. `ref_measured`
    caches the reference run per seed.
    """

    root: Path
    task_id: str
    language: str
    effects: list[str]
    limits: LimitConfig
    check_credit: float
    efficiency_weight: float
    seed_policy: str
    fixed_seed: int
    cases: int
    env: dict[str, str]
    prompt: str
    interface_text: str
    visible_text: str
    hidden: list[tuple[str, str]]
    reference_text: str
    task_hash: str
    declared_reference_fuel: int | None = None
    ref_measured: dict[int, ReferenceYardstick] = dataclass_field(default_factory=dict)


@dataclass
class Episode:
    """The scored result of one attempt on one task."""

    task_id: str
    attempt_id: str
    stage_reached: str
    diagnostics: list[Diagnostic]
    total: int
    passed: int
    failed: int
    trapped: int
    cases: list[dict[str, object]]
    task_spec_violations: int
    fuel_used: int
    fuel_limit: int
    memory_used: int
    memory_limit: int
    limit_hit: str | None
    reward: float | None
    infrastructure_error: dict[str, str] | None
    seed: int
    source_hash: str
    task_hash: str
    stdout: str
    visible_passed: int
    visible_total: int
    crash: dict[str, str] | None = None
    isolation: str = "none"
    isolation_warning: str | None = None
    correctness: float | None = None
    efficiency: float | None = None
    efficiency_weight: float | None = None
    e_basis: str | None = None
    e_basis_reason: str | None = None
    ref_fuel: int | None = None
    # diagnostics[:attempt_diagnostics] come from the attempt's own parse and
    # check. Later ones were raised with hidden code in scope, so agent_view
    # withholds their detail. The default 0 withholds everything.
    attempt_diagnostics: int = 0

    def to_dict(self) -> dict[str, object]:
        """The episode as an object that `result.schema.json` describes."""
        return {
            "schema": RESULT_SCHEMA,
            "task_id": self.task_id,
            "attempt_id": self.attempt_id,
            "toolchain": toolchain(),
            "stage_reached": self.stage_reached,
            "diagnostics": [item.to_json() for item in self.diagnostics],
            "attempt_diagnostics": self.attempt_diagnostics,
            "tests": {
                "total": self.total,
                "passed": self.passed,
                "failed": self.failed,
                "trapped": self.trapped,
                "cases": self.cases,
            },
            "visible_tests": {"total": self.visible_total, "passed": self.visible_passed},
            "contracts": {"task_spec_violations": self.task_spec_violations},
            "resources": {
                "fuel_used": self.fuel_used,
                "fuel_limit": self.fuel_limit,
                "memory_units_used": self.memory_used,
                "memory_units_limit": self.memory_limit,
                "limit_hit": self.limit_hit,
            },
            "breakdown": {
                "C": self.correctness,
                "E": self.efficiency,
                "E_basis": self.e_basis,
                "E_basis_reason": self.e_basis_reason,
                "ref_fuel": self.ref_fuel,
                "w": self.efficiency_weight,
            },
            "reward": self.reward,
            "infrastructure_error": self.infrastructure_error,
            "isolation": self.isolation,
            "isolation_warning": self.isolation_warning,
            "stdout": self.stdout,
            "replay": {
                "seed": self.seed,
                "source_hash": self.source_hash,
                "task_hash": self.task_hash,
            },
            "crash": self.crash,
        }

    def to_json(self) -> str:
        """`to_dict` as JSON text with sorted keys, ending in a newline."""
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"


def toolchain() -> dict[str, str]:
    """The tool, language, and Python versions and the host platform."""
    return {
        "tersalang": TOOL_VERSION,
        "language": LANGUAGE_VERSION,
        "python": platform.python_version(),
        "platform": f"{sys.platform}-{platform.machine()}",
    }


def canonical_bytes(episode: Episode | dict[str, object]) -> bytes:
    """Reward payload with host identity removed, so CI can compare it across OSes."""
    body = episode.to_dict() if isinstance(episode, Episode) else episode
    cloned = json.loads(json.dumps(body))
    tool = cloned.get("toolchain")
    if isinstance(tool, dict):
        tool["python"] = "python"
        tool["platform"] = "platform"
    text = json.dumps(cloned, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return (text + "\n").encode("utf-8")


WITHHELD_MESSAGE = "raised while checking or running the hidden tests; details are withheld"
WITHHELD_INFRASTRUCTURE = "infrastructure error; details are withheld"
WITHHELD_FILE = "<hidden>"


def agent_view(episode: Episode | dict[str, object]) -> dict[str, object]:
    """What the agent may see (design §22.5).

    Hidden cases and stdout are removed. The attempt's own parse and check
    diagnostics keep full detail. Every later diagnostic was raised while the
    attempt was checked against the hidden tests or ran them, so it keeps only
    its code, a position in public code, and a generic message: no values,
    related notes, blame, fix, or original text. An infrastructure message is
    withheld too; its code stays. Fuel and memory used, and a measured
    ref_fuel, are rounded down to a power of two, and E and the reward are
    recomputed from the rounded numbers (`coarse_count`).
    """
    source = episode.to_dict() if isinstance(episode, Episode) else episode
    body: dict[str, object] = json.loads(json.dumps(source))
    tests = body.get("tests")
    if isinstance(tests, dict):
        tests.pop("cases", None)
    body.pop("stdout", None)
    count = body.get("attempt_diagnostics")
    own = count if isinstance(count, int) and not isinstance(count, bool) else 0
    items = body.get("diagnostics")
    shown: list[object] = []
    for index, item in enumerate(items if isinstance(items, list) else []):
        if isinstance(item, dict):
            shown.append(item if index < own else _withheld(item))
    body["diagnostics"] = shown
    body["attempt_diagnostics"] = min(own, len(shown))
    infrastructure = body.get("infrastructure_error")
    if isinstance(infrastructure, dict):
        infrastructure["message"] = WITHHELD_INFRASTRUCTURE
    _coarsen_resources(body)
    return body


def coarse_count(value: int) -> int:
    """The largest power of two that is at most `value`; 0 stays 0.

    An attempt can spend fuel or memory in proportion to a hidden input, so the
    exact numbers would be a channel it controls. A power-of-two bucket leaves
    about log2 of the range distinct values (31 up to 2**31), keeps the order,
    and is within a factor of two, which is the scale E is measured on.
    """
    if value <= 0:
        return value
    return 1 << (value.bit_length() - 1)


def _coarsen_resources(body: dict[str, object]) -> None:
    resources = body.get("resources")
    breakdown = body.get("breakdown")
    if not isinstance(resources, dict) or not isinstance(breakdown, dict):
        return
    for key in ("fuel_used", "memory_units_used"):
        value = resources.get(key)
        if _is_count(value):
            resources[key] = coarse_count(value)
    ref_fuel = breakdown.get("ref_fuel")
    if _is_count(ref_fuel):
        breakdown["ref_fuel"] = ref_fuel = coarse_count(ref_fuel)
    used = resources.get("fuel_used")
    limit = resources.get("fuel_limit")
    e = breakdown.get("E")
    # E 0 means the attempt did not run or spent its whole limit; it stays 0.
    if not _is_unit(e) or e == 0 or not _is_count(used):
        return
    basis = breakdown.get("E_basis")
    if basis in {"reference", "declared"} and _is_count(ref_fuel):
        e = round(reference_efficiency(used, ref_fuel), 10)
    elif basis == "limit" and _is_count(limit):
        e = round(efficiency_score(used, limit), 10)
    else:
        return
    breakdown["E"] = e
    c = breakdown.get("C")
    w = breakdown.get("w")
    if _is_unit(body.get("reward")) and _is_unit(c) and _is_unit(w):
        body["reward"] = score_reward(c, e, w)


def _is_count(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_unit(value: object) -> TypeGuard[float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1


def _withheld(item: dict[str, object]) -> dict[str, object]:
    file, span = _public_place(item)
    return {
        **item,
        "message": WITHHELD_MESSAGE,
        "file": file,
        "span": span,
        "related": [],
        "blame": None,
        "values": None,
        "fix": None,
    }


def _public_place(item: dict[str, object]) -> tuple[str, object]:
    """The primary span if it is public, else the first public related span."""
    places: list[object] = [item]
    related = item.get("related")
    if isinstance(related, list):
        places.extend(related)
    for place in places:
        if not isinstance(place, dict):
            continue
        file = place.get("file")
        if isinstance(file, str) and not _is_hidden_file(file) and not _is_harness_file(file):
            return file, place.get("span")
    start = {"line": 1, "column": 1}
    return WITHHELD_FILE, {"start": start, "end": dict(start)}


def _is_harness_file(file: str) -> bool:
    return file.replace("\\", "/").rsplit("/", 1)[-1].startswith("harness_")


def _is_hidden_file(file: str) -> bool:
    normalized = file.replace("\\", "/")
    if normalized.startswith("hidden/") or "/hidden/" in f"/{normalized}":
        return True
    name = normalized.rsplit("/", 1)[-1]
    return name.startswith("harness_hidden")


def load_task(path: Path) -> Task:
    """Load and validate the task directory at `path`.

    A bad task raises `TaskLoadError`: `I9014` when task.toml is missing,
    `I9022` for a malformed field, `I9015` for a language mismatch, `I9010` for
    a limit out of range or a scoped effect, `I9016` and `I9017` for an unknown
    or RL-denied effect, `I9018` for a reward weight outside [0, 1], `I9019`
    for an unknown seed policy, `I9020` when hidden/ is missing or empty,
    `I9021` for a task file that does not parse, and `I9025` when the
    reference does not match `interface.tersa`. `task_hash` covers every file
    outside an `attempt` directory, with CRLF read as LF.
    """
    root = path.resolve()
    toml_path = root / "task.toml"
    if not toml_path.is_file():
        raise TaskLoadError("task.toml is missing", "I9014")
    try:
        data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise TaskLoadError(f"task.toml: {exc}", "I9022") from exc
    if "language" in data and not isinstance(data.get("language"), str):
        raise TaskLoadError("language must be text", "I9022")
    task_id = _string(data, "id") or root.name
    language = _string(data, "language") or LANGUAGE_VERSION
    if language != LANGUAGE_VERSION:
        raise TaskLoadError(
            f"task language `{language}` does not match {LANGUAGE_VERSION}", "I9015"
        )
    effects = _string_list(data.get("effects"))
    _check_task_effects(effects)
    limits_table = data.get("limits")
    if not isinstance(limits_table, dict):
        raise TaskLoadError("fuel and memory_units are required in [limits]", "I9010")
    fuel = _positive(limits_table, "fuel")
    memory = _positive(limits_table, "memory_units")
    if fuel is None or memory is None:
        raise TaskLoadError("fuel and memory_units must be set and greater than 0", "I9010")
    bits = _optional_int(limits_table, "max_int_bits", DEFAULT_MAX_INT_BITS)
    depth = _optional_int(limits_table, "call_depth", DEFAULT_MAX_DEPTH)
    output = _optional_int(limits_table, "output_bytes", DEFAULT_TEST_OUTPUT_BYTES)
    wall_ms = _optional_int(limits_table, "wall_ms", _HARNESS_WALL_MS)
    cases = _optional_int(limits_table, "cases", DEFAULT_PROPERTY_CASES)
    if bits > DEFAULT_MAX_INT_BITS or bits < 64:
        raise TaskLoadError("max_int_bits cannot be raised above 65536 or set below 64", "I9010")
    if depth > DEFAULT_MAX_DEPTH or depth < 1:
        raise TaskLoadError("call_depth cannot be raised above 1000", "I9010")
    if output > DEFAULT_TEST_OUTPUT_BYTES or output < 0:
        raise TaskLoadError("output_bytes cannot be raised above 1048576", "I9010")
    if wall_ms < 1 or cases < 1:
        raise TaskLoadError("wall_ms and cases must be at least 1", "I9010")
    reward_raw = data.get("reward")
    if "reward" in data and not isinstance(reward_raw, dict):
        raise TaskLoadError("reward must be a table", "I9022")
    reward: dict[str, object] = reward_raw if isinstance(reward_raw, dict) else {}
    check_credit = _float(reward, "check_credit", 0.0)
    efficiency = _float(reward, "efficiency_weight", 0.1)
    if not 0.0 <= check_credit <= 1.0 or not 0.0 <= efficiency <= 1.0:
        raise TaskLoadError("check_credit and efficiency_weight must be between 0 and 1", "I9018")
    declared_fuel = _reference_fuel_field(reward)
    seeds_raw = data.get("seeds")
    if "seeds" in data and not isinstance(seeds_raw, dict):
        raise TaskLoadError("seeds must be a table", "I9022")
    seeds: dict[str, object] = seeds_raw if isinstance(seeds_raw, dict) else {}
    if "property_seed_policy" in seeds and not isinstance(seeds.get("property_seed_policy"), str):
        raise TaskLoadError("property_seed_policy must be text", "I9022")
    policy = _string(seeds, "property_seed_policy") or "per_episode"
    if policy not in {"per_episode", "fixed"}:
        raise TaskLoadError("property_seed_policy must be per_episode or fixed", "I9019")
    fixed_seed = _optional_int(seeds, "fixed_seed", 0)
    env_raw = data.get("env")
    env: dict[str, str] = {}
    if isinstance(env_raw, dict):
        env = {str(key): str(value) for key, value in env_raw.items()}
    hidden_dir = root / "hidden"
    if not hidden_dir.is_dir():
        raise TaskLoadError("hidden/ is missing", "I9020")
    hidden = _sources(hidden_dir)
    if not hidden:
        raise TaskLoadError("hidden/ has no .tersa files", "I9020")
    for name, text in hidden:
        _require_parsed(name, text)
    prompt = _read(root / "prompt.md")
    interface_text = _read(root / "interface.tersa")
    if interface_text.strip():
        _require_parsed("interface.tersa", interface_text)
    visible_text = _read(root / "visible_tests.tersa")
    reference_text = _read(root / "reference" / "solution.tersa")
    _require_reference_signatures(reference_text, interface_text)
    digest = hashlib.sha256()
    for file in sorted(root.rglob("*")):
        if file.is_file() and "attempt" not in file.parts:
            digest.update(file.relative_to(root).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(file.read_bytes().replace(b"\r\n", b"\n"))
    return Task(
        root=root,
        task_id=task_id,
        language=language,
        effects=effects,
        limits=LimitConfig(
            fuel=fuel,
            memory_units=memory,
            max_int_bits=bits,
            max_depth=depth,
            output_bytes=output,
            wall_ms=wall_ms,
        ),
        check_credit=check_credit,
        efficiency_weight=efficiency,
        seed_policy=policy,
        fixed_seed=fixed_seed,
        cases=cases,
        env=env,
        prompt=prompt,
        interface_text=interface_text,
        visible_text=visible_text,
        hidden=hidden,
        reference_text=reference_text,
        task_hash="sha256:" + digest.hexdigest(),
        declared_reference_fuel=declared_fuel,
    )


def _require_reference_signatures(reference_text: str, interface_text: str) -> None:
    interface = _interface_module(interface_text)
    if interface is None or not reference_text.strip():
        return
    reference, diagnostics = _parse("reference/solution.tersa", reference_text)
    if reference is None or _errors(diagnostics):
        return
    mismatched = signature_diagnostics(reference, interface)
    if mismatched:
        raise TaskLoadError(f"reference/solution.tersa: {mismatched[0].message}", "I9025")


def public_task_files(task: Task) -> dict[str, str]:
    """Files the agent is allowed to see. Hidden tests are not included."""
    files = {"prompt.md": task.prompt}
    if task.interface_text:
        files["interface.tersa"] = task.interface_text
    if task.visible_text:
        files["visible_tests.tersa"] = task.visible_text
    return files


def run_episode(
    task: Task,
    source: str,
    *,
    attempt_id: str = "",
    seed: int = 0,
    filename: str = "attempt.tersa",
    isolation: str = "none",
    isolation_warning: str | None = None,
    as_candidate: bool = True,
) -> Episode:
    """Score the attempt `source` against `task` in this process.

    The first failing stage decides the score: a parse error or a mismatch
    with `interface.tersa` (`E3047`) scores 0, and any other check error scores
    the task's `check_credit`. Otherwise the hidden tests run and C, E, and the
    reward are computed. A `fixed` seed policy overrides `seed`. With
    `as_candidate` false, a wall-clock stop is `I9013` with a null reward
    instead of the scored trap `T6208`, and a host `MemoryError` propagates.
    """
    chosen = task.fixed_seed if task.seed_policy == "fixed" else seed
    attempt = attempt_id or hashlib.sha256(_source_bytes(source)).hexdigest()[:16]
    source_hash = _source_hash(source)
    base = _blank(task, attempt, chosen, source_hash)
    base.isolation = isolation
    base.isolation_warning = isolation_warning
    module, diagnostics = _parse(filename, source)
    if module is None or _errors(diagnostics):
        base.stage_reached = "parse"
        base.diagnostics = diagnostics
        base.attempt_diagnostics = len(diagnostics)
        _assign_score(base, task, 0.0, 0, executed=False)
        _mark_unrun(base, task)
        return base
    diagnostics.extend(check_module(module, mode="rl"))
    mismatched = signature_diagnostics(module, _interface_module(task.interface_text))
    if mismatched:
        base.stage_reached = "check"
        base.diagnostics = [*diagnostics, *mismatched]
        base.attempt_diagnostics = len(base.diagnostics)
        _assign_score(base, task, 0.0, 0, executed=False)
        _mark_unrun(base, task)
        return base
    if _errors(diagnostics):
        base.stage_reached = "check"
        base.diagnostics = diagnostics
        base.attempt_diagnostics = len(diagnostics)
        _assign_score(base, task, task.check_credit, 0, executed=False)
        _mark_unrun(base, task)
        return base
    base.attempt_diagnostics = len(diagnostics)
    try:
        stitched, stitch_diagnostics = _stitch(task, module, source)
    except TaskLoadError as exc:
        return _infra(base, exc)
    own = {_diagnostic_key(item) for item in diagnostics}
    stitch_diagnostics = [item for item in stitch_diagnostics if _diagnostic_key(item) not in own]
    if _errors(stitch_diagnostics):
        base.stage_reached = "check"
        base.diagnostics = [*diagnostics, *stitch_diagnostics]
        _assign_score(base, task, task.check_credit, 0, executed=False)
        _mark_unrun(base, task)
        return base
    hidden_tests = [decl for decl in stitched.decls if isinstance(decl, TestDecl)]
    if not hidden_tests:
        base.stage_reached = "run"
        base.diagnostics = diagnostics
        _assign_score(base, task, 0.0, 0, executed=False)
        return base
    outcome = _run_suite(
        task, stitched, hidden_tests, chosen, count_reward=True, as_candidate=as_candidate
    )
    if outcome.resource_failure is not None:
        base.stage_reached = "run"
        base.diagnostics = [*diagnostics, *outcome.diagnostics]
        seen = {str(case.get("id")) for case in outcome.cases}
        cases = list(outcome.cases)
        failed = 0
        for decl in hidden_tests:
            if decl.name in seen:
                continue
            cases.append({"id": decl.name, "status": "failed", "fuel": 0})
            failed += 1
        base.total = len(hidden_tests)
        base.passed = 0
        base.failed = failed
        base.trapped = outcome.trapped
        base.cases = cases
        base.fuel_used = outcome.fuel_used
        base.memory_used = outcome.memory_used
        base.stdout = outcome.stdout
        _assign_score(base, task, 0.0, 0, executed=False)
        return base
    if outcome.infrastructure is not None:
        base.stage_reached = "run"
        base.diagnostics = [*diagnostics, *outcome.diagnostics]
        base.infrastructure_error = outcome.infrastructure
        base.reward = None
        base.stdout = outcome.stdout
        return base
    visible_passed, visible_total = _visible(task, module, chosen)
    base.stage_reached = "run"
    base.diagnostics = [*diagnostics, *outcome.diagnostics]
    base.total = len(hidden_tests)
    base.passed = outcome.passed
    base.failed = outcome.failed
    base.trapped = outcome.trapped
    base.cases = outcome.cases
    base.task_spec_violations = outcome.task_spec_violations
    base.fuel_used = outcome.fuel_used
    base.memory_used = outcome.memory_used
    base.limit_hit = outcome.limit_hit
    _assign_score(
        base,
        task,
        _correctness(task, outcome.passed, len(hidden_tests)),
        outcome.fuel_used,
        executed=True,
    )
    base.stdout = outcome.stdout
    base.visible_passed = visible_passed
    base.visible_total = visible_total
    return base


def validate_task(task: Task) -> dict[str, object]:
    """Mutation check (RH-17). The reference must pass and each mutant must not.

    A reference that cannot be mutated is reported as a warning. That alone does
    not fail the task.
    """
    warnings: list[str] = []
    if not task.reference_text:
        return {
            "ok": False,
            "message": "reference/solution.tersa is missing",
            "mutants": [],
            "warnings": warnings,
        }
    # as_candidate is false so a wall-clock stop stays I9013 on this episode.
    # The command still fails the gate (exit 1). It does not discard a later run.
    reference = run_episode(
        task,
        task.reference_text,
        attempt_id="reference",
        seed=0,
        filename="reference/solution.tersa",
        as_candidate=False,
    )
    mutants: list[dict[str, object]] = []
    ok = (
        _reference_passed(reference)
        and reference.reward is not None
        and reference.infrastructure_error is None
    )
    if task.declared_reference_fuel is not None:
        measured = reference.fuel_used if _reference_ran(reference) else None
        if measured != task.declared_reference_fuel:
            ok = False
            shown = "no runnable reference" if measured is None else str(measured)
            warnings.append(
                f"reference_fuel {task.declared_reference_fuel} does not match the reference run ({shown})"
            )
    generated = _mutants(task.reference_text)
    if not generated:
        warnings.append("no mutant could be generated")
    for name, source in generated:
        episode = run_episode(
            task, source, attempt_id=name, seed=0, filename="reference/solution.tersa"
        )
        survived = episode.correctness == 1.0 and episode.infrastructure_error is None
        mutants.append({"name": name, "reward": episode.reward, "survived": survived})
        if survived:
            ok = False
    attack = _override_attack(task, reference, generated)
    if not attack["held"]:
        ok = False
    report: dict[str, object] = {
        "ok": ok,
        "reference_reward": reference.reward,
        "mutants": mutants,
        "override_attack": attack,
        "warnings": warnings,
    }
    stopped = reference.infrastructure_error
    if stopped is not None:
        report["message"] = (
            f"reference stopped during validation: {stopped['code']}: {stopped['message']}"
        )
    return report


def _override_attack(
    task: Task, reference: Episode, mutants: list[tuple[str, str]]
) -> dict[str, object]:
    """Redefine every hidden name in the attempt and check nothing moves (§22.1).

    The reference plus the hostile block must score exactly what the reference
    scored, test by test. Each mutant plus the hostile block must still fail a
    hidden test, so an override cannot lift a wrong answer.
    """
    hostile, declared, skipped = _hostile_block(task)
    report: dict[str, object] = {
        "declarations": declared,
        "skipped": skipped,
        "reward": reference.reward,
        "held": True,
        "mutants_survived": [],
    }
    if not declared:
        return report
    attacked = run_episode(
        task,
        _with_block(task.reference_text, hostile),
        attempt_id="override-attack",
        seed=0,
        filename="reference/solution.tersa",
        as_candidate=False,
    )
    report["reward"] = attacked.reward
    same = attacked.reward == reference.reward and _statuses(attacked) == _statuses(reference)
    survived: list[str] = []
    for name, source in mutants:
        episode = run_episode(
            task,
            _with_block(source, hostile),
            attempt_id=f"override-{name}",
            seed=0,
            filename="reference/solution.tersa",
        )
        if episode.correctness == 1.0 and episode.infrastructure_error is None:
            survived.append(name)
    report["mutants_survived"] = survived
    report["held"] = same and not survived
    return report


def _statuses(episode: Episode) -> list[tuple[object, object]]:
    return [(case.get("id"), case.get("status")) for case in episode.cases]


def _with_block(source: str, block: list[str]) -> str:
    return source.rstrip("\n") + "\n\n" + "\n\n".join(block) + "\n"


def _hostile_block(task: Task) -> tuple[list[str], list[str], list[str]]:
    """Attempt-side redefinitions of hidden names that still type-check."""
    reference, diagnostics = _parse("reference/solution.tersa", task.reference_text)
    if reference is None or _errors(diagnostics):
        return [], [], []
    taken = _top_names(reference)
    shared = _shared_names(task.interface_text)
    candidates: list[tuple[str, str]] = []
    locals_seen: set[str] = set()
    for filename, text in task.hidden:
        module, parsed = _parse(filename, text)
        if module is None or _errors(parsed):
            continue
        for decl in module.decls:
            entry = _hostile_decl(decl, text, len(candidates))
            if entry is not None and entry[0] not in shared and entry[0] not in taken:
                candidates.append(entry)
                taken.add(entry[0])
        bound: set[str] = set()
        for decl in module.decls:
            collect_locals(decl, bound)
        for name in sorted(bound - taken - shared - locals_seen):
            if name != "_" and name[:1].islower():
                locals_seen.add(name)
                candidates.append((name, f"let {name}: Int = 0"))
    kept: list[str] = []
    declared: list[str] = []
    skipped: list[str] = []
    for name, text in candidates:
        if _well_typed(_with_block(task.reference_text, [*kept, text])):
            kept.append(text)
            declared.append(name)
        else:
            skipped.append(name)
    return kept, declared, skipped


def _top_names(module: Module) -> set[str]:
    names: set[str] = set()
    for decl in module.decls:
        if isinstance(decl, FunctionDecl):
            names.add(decl.sig.name)
        elif isinstance(decl, (ConstDecl, RecordDecl, InterfaceDecl)):
            names.add(decl.name)
        elif isinstance(decl, ChoiceDecl):
            names.add(decl.name)
            names.update(case.name for case in decl.cases)
    for item in module.imports:
        names.add(item.alias or item.path[-1])
        names.update(name for name, _span in item.exposing or [])
    return names


def _hostile_decl(decl: Decl, text: str, index: int) -> tuple[str, str] | None:
    if isinstance(decl, FunctionDecl) and decl.sig.name != "main":
        header = text[decl.span.start : decl.body.span.start].rstrip()
        if header.endswith("do"):
            header = header[: -len("do")].rstrip()
        ret = decl.sig.ret
        bool_ret = ret.kind == "named" and not ret.path and ret.name == "Bool"
        body = "return true" if bool_ret else 'fail "override"'
        return decl.sig.name, f"{header}\ndo\n  {body}\nend"
    if isinstance(decl, ConstDecl):
        ty = text[decl.ty.span.start : decl.ty.span.end]
        expr = text[decl.expr.span.start : decl.expr.span.end]
        changed = {
            "Int": f"({expr}) + 1",
            "Float": f"({expr}) + 1.0",
            "Bool": f"not ({expr})",
            "Text": f'Text.concat({expr}, "override")',
        }.get(ty)
        if changed is None:
            return None
        return decl.name, f"let {decl.name}: {ty} = {changed}"
    if isinstance(decl, RecordDecl):
        return decl.name, f"record {decl.name}\n  override_field: Int\nend"
    if isinstance(decl, ChoiceDecl):
        cases = "".join(f"  case {case.name}\n" for case in decl.cases)
        return decl.name, f"choice {decl.name}\n{cases}  case OverrideAttack{index}\nend"
    if isinstance(decl, InterfaceDecl):
        return decl.name, text[decl.span.start : decl.span.end]
    return None


def run_episode_isolated(
    task_dir: Path,
    attempt: Path,
    *,
    seed: int = 0,
    attempt_id: str = "",
    timeout_s: float = 30.0,
    isolation: str | None = None,
    os_limits: OsLimits | None = None,
) -> str:
    """Run one attempt in a child process. A dead child scores 0 (RH-10).

    `isolation` None uses the strongest backend that can launch. The return
    value is the episode JSON. A live child result is passed through unchanged.
    An OS kill or the child timeout is a scored trap (reward 0), not a discard.
    """
    from tersalang.isolation import IsolationUnavailable, classify_os_death, resolve, run_argv

    limits = os_limits if os_limits is not None else OsLimits()
    try:
        backend, warning = resolve(isolation)
    except IsolationUnavailable as exc:
        return _backend_episode(
            task_dir, attempt, seed, attempt_id, exc.code, exc.message
        ).to_json()
    task_path = task_dir.resolve()
    attempt_path = attempt.resolve()
    payload = json.dumps(
        {
            "task": str(task_path),
            "attempt": str(attempt_path),
            "seed": seed,
            "attempt_id": attempt_id,
            "isolation": backend,
            "isolation_warning": warning,
        }
    )
    result = run_argv(
        [sys.executable, "-m", "tersalang.harness_worker"],
        stdin=payload,
        backend=backend,
        limits=limits,
        timeout=timeout_s,
        read_only=(task_path, attempt_path),
    )
    if result.timed_out:
        episode = _timeout_episode(task_dir, attempt, seed, attempt_id, timeout_s)
        episode.isolation = backend
        episode.isolation_warning = warning
        return episode.to_json()
    text = result.stdout.strip()
    problem = None
    if text:
        problem = child_result_problem(text, task_dir, attempt, backend)
        if problem is None:
            return text + "\n"
    killed = classify_os_death(result.returncode, result.stderr)
    if killed is not None:
        code, message = killed
        episode = _scored_trap_episode(task_dir, attempt, seed, attempt_id, code, message)
        episode.isolation = backend
        episode.isolation_warning = warning
        return episode.to_json()
    episode = _crash_episode(task_dir, attempt, seed, attempt_id, result.returncode, problem)
    episode.isolation = backend
    episode.isolation_warning = warning
    return episode.to_json()


def failure_episode(
    *,
    task_id: str,
    attempt_id: str,
    task_hash: str,
    source_hash: str,
    seed: int,
    message: str,
    infrastructure: dict[str, str] | None,
    reward: float | None,
) -> Episode:
    """An episode with no per-test results and every count zero.

    With `infrastructure` set it is an infrastructure error; otherwise `crash`
    records `message` as a process crash. `reward` is used as given.
    """
    episode = Episode(
        task_id=task_id,
        attempt_id=attempt_id,
        stage_reached="run",
        diagnostics=[],
        total=0,
        passed=0,
        failed=0,
        trapped=0,
        cases=[],
        task_spec_violations=0,
        fuel_used=0,
        fuel_limit=0,
        memory_used=0,
        memory_limit=0,
        limit_hit=None,
        reward=reward,
        infrastructure_error=infrastructure,
        seed=seed,
        source_hash=source_hash,
        task_hash=task_hash,
        stdout="",
        visible_passed=0,
        visible_total=0,
        crash=None if infrastructure else {"type": "process", "message": message},
    )
    return episode


def _timeout_episode(
    task_dir: Path, attempt: Path, seed: int, attempt_id: str, timeout_s: float
) -> Episode:
    """The child used up the harness timeout. That is the candidate's own run."""
    return _scored_trap_episode(
        task_dir, attempt, seed, attempt_id, "T6208", child_wall_message(timeout_s)
    )


def _scored_trap_episode(
    task_dir: Path,
    attempt: Path,
    seed: int,
    attempt_id: str,
    code: str,
    message: str,
) -> Episode:
    """A candidate resource trap: reward 0, correctness 0, efficiency 0.

    The child never returned a per-test result, so every hidden test is
    listed by its real name and marked failed (it did not run). The kill
    diagnostic is on the episode. A task that cannot be loaded stays an
    infrastructure error.
    """
    source = _read_attempt(attempt)
    source_hash = _source_hash(source)
    try:
        task = load_task(task_dir)
    except TaskLoadError as exc:
        return failure_episode(
            task_id=task_dir.name,
            attempt_id=attempt_id or "attempt",
            task_hash="",
            source_hash=source_hash,
            seed=seed,
            message=exc.message,
            infrastructure={"code": exc.code, "message": exc.message},
            reward=None,
        )
    episode = _blank(task, attempt_id or "attempt", seed, source_hash)
    episode.stage_reached = "run"
    span = Span(attempt.name, 0, 0, 1, 1, 1, 1)
    episode.diagnostics = [Diagnostic(code=code, message=message, file=attempt.name, span=span)]
    _fill_unstarted(episode, task)
    episode.crash = None
    episode.infrastructure_error = None
    _assign_score(episode, task, 0.0, 0, executed=False)
    return episode


def _backend_episode(
    task_dir: Path,
    attempt: Path,
    seed: int,
    attempt_id: str,
    code: str,
    message: str,
) -> Episode:
    source = _read_attempt(attempt)
    return failure_episode(
        task_id=task_dir.name,
        attempt_id=attempt_id or "attempt",
        task_hash="",
        source_hash=_source_hash(source),
        seed=seed,
        message=message,
        infrastructure={"code": code, "message": message},
        reward=None,
    )


def child_result_problem(text: str, task_dir: Path, attempt: Path, backend: str) -> str | None:
    """Why the child's output is not a trustworthy episode, or None.

    The output must be one JSON object that passes `result.schema.json` and
    the reward formula, and it must name this attempt, this task, and the
    backend the parent launched.
    """
    from tersalang.result_schema import episode_problems

    try:
        body = json.loads(text)
    except json.JSONDecodeError as exc:
        return f"output is not JSON ({exc.msg})"
    problems = episode_problems(body)
    if problems:
        return problems[0]
    assert isinstance(body, dict)
    replay = body["replay"]
    if replay["source_hash"] != _source_hash(_read_attempt(attempt)):
        return "$.replay.source_hash does not match the attempt"
    try:
        task_hash = load_task(task_dir).task_hash
    except TaskLoadError:
        task_hash = ""
    if replay["task_hash"] != task_hash:
        return "$.replay.task_hash does not match the task"
    if body["isolation"] != backend:
        return f"$.isolation must be {backend}"
    return None


def _crash_episode(
    task_dir: Path,
    attempt: Path,
    seed: int,
    attempt_id: str,
    code: int,
    problem: str | None = None,
) -> Episode:
    """An unclassified child death: reward 0, correctness 0, and a crash object.

    Hidden tests are listed by name and marked failed. The crash object is
    the diagnostic. A child that exited with output the parent rejects is the
    same crash, typed `invalid_result`. A task that cannot be loaded stays an
    infrastructure error.
    """
    source = _read_attempt(attempt)
    source_hash = _source_hash(source)
    message = f"interpreter process exited {code}"
    if problem is not None:
        message = f"interpreter process exited {code} with an invalid result: {problem}"
    try:
        task = load_task(task_dir)
    except TaskLoadError as exc:
        return failure_episode(
            task_id=task_dir.name,
            attempt_id=attempt_id or "attempt",
            task_hash="",
            source_hash=source_hash,
            seed=seed,
            message=exc.message,
            infrastructure={"code": exc.code, "message": exc.message},
            reward=None,
        )
    episode = _blank(task, attempt_id or "attempt", seed, source_hash)
    episode.stage_reached = "run"
    _fill_unstarted(episode, task)
    episode.crash = {"type": "process" if problem is None else "invalid_result", "message": message}
    episode.infrastructure_error = None
    _assign_score(episode, task, 0.0, 0, executed=False)
    return episode


@dataclass
class _Suite:
    passed: int = 0
    failed: int = 0
    trapped: int = 0
    cases: list[dict[str, object]] = dataclass_field(default_factory=list)
    diagnostics: list[Diagnostic] = dataclass_field(default_factory=list)
    task_spec_violations: int = 0
    fuel_used: int = 0
    memory_used: int = 0
    limit_hit: str | None = None
    stdout: str = ""
    infrastructure: dict[str, str] | None = None
    resource_failure: str | None = None


def _record_resource_trap(
    suite: _Suite, interpreter: Interpreter, decl: TestDecl, code: str, message: str
) -> None:
    diagnostic = interpreter._diagnostic(code, message, decl.span)
    suite.diagnostics.append(diagnostic)
    suite.trapped += 1
    suite.cases.append(
        {
            "id": decl.name,
            "status": "trapped",
            "fuel": interpreter.meter.fuel_used,
            "trap": code,
        }
    )
    suite.fuel_used += interpreter.meter.fuel_used
    suite.memory_used = max(suite.memory_used, interpreter.meter.memory_used)
    suite.resource_failure = code


def _run_suite(
    task: Task,
    module: Module,
    tests: list[TestDecl],
    seed: int,
    *,
    count_reward: bool,
    as_candidate: bool = True,
) -> _Suite:
    suite = _Suite()
    grants: dict[str, list[str]] = {effect: [] for effect in task.effects}
    if task.env:
        grants["Env"] = []
    chunks: list[str] = []
    for decl in tests:
        host = Host(
            grants=grants,
            seed=seed,
            env=dict(task.env),
            mode="rl",
            limits=task.limits,
            filename="harness_attempt.tersa",
        )
        interpreter = Interpreter(module, host)
        failures: list[Diagnostic] = []
        try:
            interpreter._run_one_test(decl, task.cases, failures)
        except FuelExhausted:
            failures.append(interpreter._diagnostic("T6201", "fuel exhausted", decl.span))
        except MemoryExhausted:
            failures.append(interpreter._diagnostic("T6202", "memory limit exceeded", decl.span))
        except RecursionLimit:
            failures.append(interpreter._diagnostic("T6203", "call depth exceeded", decl.span))
        except WallClockExceeded:
            message = in_process_wall_message(task.limits.wall_ms)
            if not as_candidate:
                suite.infrastructure = {"code": "I9013", "message": message}
                suite.diagnostics.append(interpreter._diagnostic("I9013", message, decl.span))
                return suite
            _record_resource_trap(suite, interpreter, decl, "T6208", message)
            return suite
        except MemoryError:
            if not as_candidate:
                raise
            from tersalang.isolation import MEMORY_MESSAGE

            _record_resource_trap(suite, interpreter, decl, "T6206", MEMORY_MESSAGE)
            return suite
        diagnostic = failures[-1] if failures else None
        status, trap = _status(diagnostic)
        if status == "passed":
            suite.passed += 1
        elif status == "trapped":
            suite.trapped += 1
        else:
            suite.failed += 1
        if diagnostic is not None and diagnostic.code.startswith("T61"):
            suite.task_spec_violations += 1
        if diagnostic is not None and count_reward:
            suite.diagnostics.append(diagnostic)
            hit = _LIMIT_NAMES.get(diagnostic.code)
            if hit is not None:
                suite.limit_hit = hit
        case: dict[str, object] = {
            "id": decl.name,
            "status": status,
            "fuel": interpreter.meter.fuel_used,
        }
        if trap is not None and diagnostic is not None:
            case["trap"] = trap
            if diagnostic.blame is not None:
                case["blame"] = diagnostic.blame
        suite.cases.append(case)
        suite.fuel_used += interpreter.meter.fuel_used
        suite.memory_used = max(suite.memory_used, interpreter.meter.memory_used)
        chunks.append("".join(interpreter.stdout))
        if interpreter.meter.output_truncated:
            suite.diagnostics.append(
                interpreter._diagnostic("W6205", "console output was truncated", decl.span)
            )
    suite.stdout = "".join(chunks)
    return suite


def _visible(task: Task, candidate: Module, seed: int) -> tuple[int, int]:
    if not task.visible_text:
        return 0, 0
    visible_module, diagnostics = _parse("visible_tests.tersa", task.visible_text)
    if visible_module is None or _errors(diagnostics):
        return 0, 0
    tests = [decl for decl in visible_module.decls if isinstance(decl, TestDecl)]
    if not tests:
        return 0, 0
    stitched = _combine(candidate, [visible_module], task.interface_text, tag="visible")
    check_diagnostics = check_module(stitched, mode="rl")
    if _errors(check_diagnostics):
        return 0, len(tests)
    outcome = _run_suite(task, stitched, tests, seed, count_reward=False)
    if outcome.infrastructure is not None:
        return 0, len(tests)
    return outcome.passed, len(tests)


def _stitch(task: Task, candidate: Module, source: str) -> tuple[Module, list[Diagnostic]]:
    hidden_modules: list[Module] = []
    diagnostics: list[Diagnostic] = []
    for name, text in task.hidden:
        module, parsed = _parse(name, text)
        diagnostics.extend(parsed)
        if module is None:
            return candidate, diagnostics
        hidden_modules.append(module)
    if _errors(diagnostics):
        return candidate, diagnostics
    stitched = _combine(candidate, hidden_modules, task.interface_text, tag="hidden")
    _ = source
    diagnostics.extend(check_module(stitched, mode="rl"))
    return stitched, diagnostics


def _combine(candidate: Module, others: list[Module], interface_text: str, *, tag: str) -> Module:
    """Candidate declarations plus task code renamed into `name@tag` (design §22.1)."""
    contracts = _contracts(interface_text)
    decls: list[Decl] = []
    for decl in candidate.decls:
        if isinstance(decl, TestDecl):
            continue
        if isinstance(decl, FunctionDecl):
            if decl.sig.name == "main":
                continue
            if decl.sig.name in contracts:
                sig = replace(decl.sig, contracts=list(contracts[decl.sig.name]))
                decl = replace(decl, sig=sig)
        decls.append(decl)
    merged = namespace_hidden(others, _shared_names(interface_text), candidate, f"@{tag}")
    decls.extend(merged.decls)
    span = Span(f"harness_{tag}.tersa", 0, 0, 1, 1, 1, 1)
    return Module(span, [f"harness_{tag}"], [*candidate.imports, *merged.imports], decls)


def _interface_module(text: str) -> Module | None:
    if not text.strip():
        return None
    module, diagnostics = _parse("interface.tersa", text)
    if module is None or _errors(diagnostics):
        return None
    return module


def _shared_names(text: str) -> set[str]:
    return interface_names(_interface_module(text))


def _contracts(text: str) -> dict[str, list[Contract]]:
    found: dict[str, list[Contract]] = {}
    module = _interface_module(text)
    if module is None:
        return found
    for decl in module.decls:
        if isinstance(decl, InterfaceDecl):
            for header in decl.headers:
                found[header.name] = list(header.contracts)
        elif isinstance(decl, FunctionDecl):
            found[decl.sig.name] = list(decl.sig.contracts)
    return found


def _status(diagnostic: Diagnostic | None) -> tuple[str, str | None]:
    if diagnostic is None:
        return "passed", None
    if diagnostic.code in {"T6030", "T6031"}:
        return "failed", diagnostic.code
    return "trapped", diagnostic.code


def efficiency_score(fuel_used: int, fuel_limit: int) -> float:
    """Limit basis, used when the reference solution did not run.

    E = max(0, 1 - fuel_used / fuel). fuel_used is the sum over hidden tests.
    """
    if fuel_limit <= 0:
        return 0.0
    return max(0.0, 1.0 - fuel_used / fuel_limit)


def reference_efficiency(fuel_used: int, ref_fuel: int) -> float:
    """E = min(1, max(ref_fuel, 1) / max(fuel_used, 1)).

    A reference that used no fuel still counts as 1, so a correct reference scores 1.
    Matching or beating the reference is 1. Twice the fuel is 0.5. Ten times is 0.1.
    """
    return min(1.0, max(ref_fuel, 1) / max(fuel_used, 1))


def score_reward(correctness: float, efficiency: float, weight: float) -> float:
    """The reward `(1 - w) * C + w * C * E`.

    C, E, and w are in [0, 1]. The result is in [0, 1]; it is not clipped.
    """
    c = round(correctness, 10)
    e = round(efficiency, 10)
    w = round(weight, 10)
    reward = round((1.0 - w) * c + w * c * e, 10)
    if not 0.0 <= c <= 1.0:
        raise AssertionError(c)
    if not 0.0 <= e <= 1.0:
        raise AssertionError(e)
    if not 0.0 <= w <= 1.0:
        raise AssertionError(w)
    if not 0.0 <= reward <= 1.0:
        raise AssertionError(reward)
    return reward


def _correctness(task: Task, passed: int, total: int) -> float:
    if total <= 0:
        return 0.0
    test_score = passed / total
    return task.check_credit + (1.0 - task.check_credit) * test_score


def _assign_score(
    episode: Episode,
    task: Task,
    correctness: float,
    fuel_used: int,
    *,
    executed: bool,
) -> None:
    ref_fuel, basis, reason = _reference_basis(task, episode.seed)
    if not executed:
        raw = 0.0
    elif basis in {"reference", "declared"} and ref_fuel is not None:
        raw = reference_efficiency(fuel_used, ref_fuel)
    else:
        raw = efficiency_score(fuel_used, task.limits.fuel or 0)
        basis = "limit"
        ref_fuel = None
        if reason is None:
            reason = "no_reference"
    c = round(correctness, 10)
    e = round(raw, 10)
    w = round(task.efficiency_weight, 10)
    episode.correctness = c
    episode.efficiency = e
    episode.efficiency_weight = w
    episode.e_basis = basis
    episode.e_basis_reason = reason
    episode.ref_fuel = ref_fuel
    episode.reward = score_reward(c, e, w)


def _reference_ran(episode: Episode) -> bool:
    return (
        episode.stage_reached == "run"
        and episode.infrastructure_error is None
        and episode.total > 0
    )


def _reference_passed(episode: Episode) -> bool:
    return (
        _reference_ran(episode) and episode.passed == episode.total and episode.correctness == 1.0
    )


def _reference_basis(task: Task, seed: int) -> tuple[int | None, str, str | None]:
    """Fuel, basis, and fallback reason for this seed.

    The reference basis is used when the reference executed and passed every
    hidden test. A declared `reference_fuel` stands in only when that
    measurement is not available, and it is labeled `declared` with the
    reason the measurement is missing. A reference that ran and failed tests
    is never the yardstick.
    """
    stick = _measure_reference_fuel(task, seed)
    if stick.reason is None and stick.fuel is not None:
        return stick.fuel, "reference", None
    if stick.reason == "reference_failed_hidden_tests":
        return None, "limit", stick.reason
    if task.declared_reference_fuel is not None:
        return task.declared_reference_fuel, "declared", stick.reason
    return None, "limit", stick.reason


def _measure_reference_fuel(task: Task, seed: int) -> ReferenceYardstick:
    """Run the reference once per seed and cache whether it can be the yardstick."""
    cached = task.ref_measured.get(seed)
    if cached is not None:
        return cached
    task.ref_measured[seed] = ReferenceYardstick(None, "reference_did_not_execute")
    if not task.reference_text.strip():
        measured = ReferenceYardstick(None, "no_reference")
        task.ref_measured[seed] = measured
        return measured
    # A wall-clock stop here is I9013, so the reference did not execute.
    # The candidate run keeps going on the declared or limit basis.
    episode = run_episode(
        task,
        task.reference_text,
        attempt_id="reference-fuel",
        seed=seed,
        filename="reference/solution.tersa",
        as_candidate=False,
    )
    if _reference_passed(episode):
        measured = ReferenceYardstick(episode.fuel_used, None)
    elif _reference_ran(episode):
        measured = ReferenceYardstick(None, "reference_failed_hidden_tests")
    else:
        measured = ReferenceYardstick(None, "reference_did_not_execute")
    task.ref_measured[seed] = measured
    return measured


def _hidden_test_names(task: Task) -> list[str]:
    """Names of hidden tests, in the order the suite would run them."""
    names: list[str] = []
    for filename, text in task.hidden:
        module, diagnostics = _parse(filename, text)
        if module is None or _errors(diagnostics):
            continue
        names.extend(decl.name for decl in module.decls if isinstance(decl, TestDecl))
    return names


def _fill_unstarted(episode: Episode, task: Task) -> None:
    """Tests the child never started: real names, status failed, trap count 0.

    This matches a test that does not run on the in-process path. The kill
    or crash diagnostic stays on the episode, not on a synthetic case.
    """
    names = _hidden_test_names(task)
    episode.total = len(names)
    episode.passed = 0
    episode.failed = len(names)
    episode.trapped = 0
    episode.cases = [{"id": name, "status": "failed", "fuel": 0} for name in names]


def _mark_unrun(episode: Episode, task: Task) -> None:
    total = 0
    for _name, text in task.hidden:
        module, _diagnostics = _parse("hidden.tersa", text)
        if module is None:
            continue
        total += sum(1 for decl in module.decls if isinstance(decl, TestDecl))
    episode.total = total
    episode.failed = total
    episode.cases = [
        {"id": f"unrun-{index}", "status": "failed", "fuel": 0} for index in range(total)
    ]


def _blank(task: Task, attempt_id: str, seed: int, source_hash: str) -> Episode:
    return Episode(
        task_id=task.task_id,
        attempt_id=attempt_id,
        stage_reached="parse",
        diagnostics=[],
        total=0,
        passed=0,
        failed=0,
        trapped=0,
        cases=[],
        task_spec_violations=0,
        fuel_used=0,
        fuel_limit=task.limits.fuel or 0,
        memory_used=0,
        memory_limit=task.limits.memory_units or 0,
        limit_hit=None,
        reward=0.0,
        infrastructure_error=None,
        seed=seed,
        source_hash=source_hash,
        task_hash=task.task_hash,
        stdout="",
        visible_passed=0,
        visible_total=0,
    )


def _infra(episode: Episode, exc: TaskLoadError) -> Episode:
    episode.stage_reached = "task"
    episode.reward = None
    episode.infrastructure_error = {"code": exc.code, "message": exc.message}
    return episode


def _parse(filename: str, text: str) -> tuple[Module | None, list[Diagnostic]]:
    _source, tokens, diagnostics = lex_text(filename, text)
    module = parse_module(_source, tokens, diagnostics)
    return module, diagnostics


def _require_parsed(filename: str, text: str) -> None:
    module, diagnostics = _parse(filename, text)
    if module is None or _errors(diagnostics):
        detail = diagnostics[0].message if diagnostics else "did not parse"
        raise TaskLoadError(f"{filename}: {detail}", "I9021")


def _check_task_effects(effects: list[str]) -> None:
    """Task grants are bare effect names. Every scoped effect is refused in RL mode."""
    parts = [(entry, entry.partition("=")[0]) for entry in effects]
    for _entry, name in parts:
        if name not in EFFECTS:
            raise TaskLoadError(f"unknown effect `{name}`", "I9016")
    for entry, name in parts:
        if name in RL_DENIED_EFFECTS:
            if "=" in entry:
                raise TaskLoadError(
                    f"RL mode cannot grant {name}, with or without a scope (`{entry}`)", "I9017"
                )
            raise TaskLoadError(f"RL mode cannot grant {name}", "I9017")
    for entry, name in parts:
        if "=" in entry:
            raise TaskLoadError(f"{name} does not take a scope (`{entry}`)", "I9010")


def _diagnostic_key(item: Diagnostic) -> str:
    """The combined-module check repeats the attempt's own warnings; this spots them."""
    return item.to_json_text()


def _errors(diagnostics: list[Diagnostic]) -> bool:
    return any(item.severity == "error" for item in diagnostics)


_MUTANT_CAP = 16
_OP_SWAP = {
    "+": "-",
    "-": "+",
    "*": "/",
    "/": "*",
    "div": "mod",
    "mod": "div",
    "==": "!=",
    "!=": "==",
    "<": ">",
    ">": "<",
    "<=": ">=",
    ">=": "<=",
    "and": "or",
    "or": "and",
}
_OP_LABEL = {
    "+": "plus",
    "-": "minus",
    "*": "star",
    "/": "slash",
    "div": "div",
    "mod": "mod",
    "==": "eq",
    "!=": "ne",
    "<": "lt",
    ">": "gt",
    "<=": "le",
    ">=": "ge",
    "and": "and",
    "or": "or",
}
_Site = tuple[str, int, int, str]


def _mutants(source: str) -> list[tuple[str, str]]:
    """Up to 16 well-typed AST edits, spread across function and test bodies.

    Contracts are left alone. Sites are grouped by edit kind, shuffled inside
    the kind with a step taken from the source hash, then drawn round-robin so
    a late operator is not dropped just because it follows sixteen earlier
    ones. A splice that does not parse or does not type-check is skipped and
    is not counted toward the cap.
    """
    module, diagnostics = _parse("reference.tersa", source)
    if module is None or _errors(diagnostics):
        return []
    sites: list[_Site] = []
    for decl in module.decls:
        if isinstance(decl, FunctionDecl):
            _collect_block(source, decl.body, sites, _ret_name(decl.sig.ret))
        elif isinstance(decl, TestDecl):
            _collect_block(source, decl.body, sites, None)
        elif isinstance(decl, ImplementsDecl):
            for function in decl.functions:
                _collect_block(source, function.body, sites, _ret_name(function.sig.ret))
    grouped: dict[str, list[_Site]] = {}
    for site in sites:
        grouped.setdefault(_site_kind(site[0]), []).append(site)
    seed = int.from_bytes(hashlib.sha256(_source_bytes(source)).digest()[:8], "big")
    orders = {kind: _spread(items, seed) for kind, items in grouped.items()}
    cursors = dict.fromkeys(orders, 0)
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    while len(found) < _MUTANT_CAP:
        progressed = False
        for kind, items in orders.items():
            cursor = cursors[kind]
            if cursor >= len(items):
                continue
            cursors[kind] = cursor + 1
            progressed = True
            text = _apply_site(source, items[cursor])
            if text is None or text in seen:
                continue
            seen.add(text)
            if not _well_typed(text):
                continue
            found.append((f"{items[cursor][0]}-{len(found)}", text))
            if len(found) >= _MUTANT_CAP:
                break
        if not progressed:
            break
    return found


def _site_kind(label: str) -> str:
    if label.startswith("op-"):
        return label.split("-to-", 1)[0]
    if label.startswith(("int-", "bool-", "float-", "return-")):
        return label.split("-", 1)[0]
    if label.startswith("not-"):
        return "not"
    if label.startswith("neg-"):
        return "neg"
    return label


def _spread(items: list[_Site], seed: int) -> list[_Site]:
    count = len(items)
    if count <= 1:
        return list(items)
    step = (seed % count) | 1
    if step >= count:
        step = 1
    while math.gcd(step, count) != 1:
        step += 2
        if step >= count:
            step = 1
            break
    start = seed % count
    order: list[_Site] = []
    pos = start
    while len(order) < count:
        order.append(items[pos])
        pos = (pos + step) % count
    return order


def _apply_site(source: str, site: _Site) -> str | None:
    _label, start, end, replacement = site
    if start < 0 or end > len(source) or start > end:
        return None
    if source[start:end] == replacement:
        return None
    text = source[:start] + replacement + source[end:]
    if text == source:
        return None
    return text


def _well_typed(source: str) -> bool:
    module, diagnostics = _parse("candidate.tersa", source)
    if module is None or _errors(diagnostics) or not module.path:
        return False
    filename = "/".join(module.path) + ".tersa"
    module, diagnostics = _parse(filename, source)
    if module is None or _errors(diagnostics):
        return False
    return not _errors(check_module(module, mode="rl"))


def _ret_name(ty: TypeExpr) -> str | None:
    if ty.kind != "named" or ty.path:
        return None
    if ty.name in {"Int", "Bool", "Float", "Text"}:
        return ty.name
    return None


def _collect_block(source: str, block: Block, sites: list[_Site], ret: str | None) -> None:
    for stmt in block.stmts:
        _collect_stmt(source, stmt, sites, ret)


def _collect_stmt(source: str, stmt: object, sites: list[_Site], ret: str | None) -> None:
    if isinstance(stmt, ReturnStmt):
        if stmt.expr is not None:
            _replace_return(source, stmt, sites, ret)
            _collect_expr(source, stmt.expr, sites)
    elif isinstance(stmt, LetStmt):
        _collect_expr(source, stmt.expr, sites)
    elif isinstance(stmt, SetStmt):
        _collect_expr(source, stmt.expr, sites)
    elif isinstance(stmt, (FailStmt, ExpectStmt, ExprStmt)):
        _collect_expr(source, stmt.expr, sites)
    elif isinstance(stmt, IfStmt):
        for if_arm in stmt.arms:
            _collect_expr(source, if_arm.cond, sites)
            _collect_block(source, if_arm.block, sites, ret)
        if stmt.else_block is not None:
            _collect_block(source, stmt.else_block, sites, ret)
    elif isinstance(stmt, MatchStmt):
        _collect_expr(source, stmt.expr, sites)
        for match_arm in stmt.arms:
            if match_arm.guard is not None:
                _collect_expr(source, match_arm.guard, sites)
            _collect_block(source, match_arm.block, sites, ret)
    elif isinstance(stmt, WhileStmt):
        _collect_expr(source, stmt.cond, sites)
        _collect_block(source, stmt.body, sites, ret)
    elif isinstance(stmt, ForStmt):
        _collect_expr(source, stmt.expr, sites)
        _collect_block(source, stmt.body, sites, ret)
    elif isinstance(stmt, UsingStmt):
        _collect_expr(source, stmt.expr, sites)
        _collect_block(source, stmt.body, sites, ret)


def _collect_expr(source: str, expr: Expr, sites: list[_Site]) -> None:
    if isinstance(expr, BinaryExpr):
        _swap_binary(source, expr, sites)
        _collect_expr(source, expr.left, sites)
        _collect_expr(source, expr.right, sites)
    elif isinstance(expr, UnaryExpr):
        if expr.op == "not":
            _drop_not(source, expr, sites)
        elif expr.op == "-":
            _drop_unary_minus(source, expr, sites)
        _collect_expr(source, expr.expr, sites)
    elif isinstance(expr, LiteralExpr):
        _tweak_literal(source, expr, sites)
    elif isinstance(expr, CallExpr):
        _collect_expr(source, expr.func, sites)
        for arg in expr.args:
            _collect_expr(source, arg.expr, sites)
    elif isinstance(expr, FieldExpr):
        _collect_expr(source, expr.recv, sites)
    elif isinstance(expr, WithExpr):
        _collect_expr(source, expr.recv, sites)
        for field in expr.fields:
            _collect_expr(source, field.expr, sites)
    elif isinstance(expr, LambdaExpr):
        _collect_expr(source, expr.body, sites)
    elif isinstance(expr, ListExpr):
        for item in expr.elements:
            _collect_expr(source, item, sites)
    elif isinstance(expr, MapExpr):
        for key, value in expr.entries:
            _collect_expr(source, key, sites)
            _collect_expr(source, value, sites)
    elif isinstance(expr, (GroupExpr, OldExpr)):
        _collect_expr(source, expr.expr, sites)


def _swap_binary(source: str, expr: BinaryExpr, sites: list[_Site]) -> None:
    swap = _OP_SWAP.get(expr.op)
    if swap is None:
        return
    gap_start = expr.left.span.end
    gap_end = expr.right.span.start
    if gap_start < 0 or gap_end > len(source) or gap_start > gap_end:
        return
    index = _locate_op(source[gap_start:gap_end], expr.op)
    if index < 0:
        return
    start = gap_start + index
    label = f"op-{_OP_LABEL.get(expr.op, expr.op)}-to-{_OP_LABEL.get(swap, swap)}"
    sites.append((label, start, start + len(expr.op), swap))


def _locate_op(gap: str, op: str) -> int:
    start = 0
    while True:
        index = gap.find(op, start)
        if index < 0:
            return -1
        after = index + len(op)
        if after < len(gap) and gap[after] in "=<>":
            start = index + 1
            continue
        return index


def _drop_not(source: str, expr: UnaryExpr, sites: list[_Site]) -> None:
    start = expr.span.start
    if source[start : start + 3] != "not":
        return
    end = start + 3
    if end < len(source) and source[end] == " ":
        end += 1
    sites.append(("not-removed", start, end, ""))


def _drop_unary_minus(source: str, expr: UnaryExpr, sites: list[_Site]) -> None:
    start = expr.span.start
    if start >= len(source) or source[start] != "-":
        return
    sites.append(("neg-removed", start, start + 1, ""))


def _tweak_literal(source: str, expr: LiteralExpr, sites: list[_Site]) -> None:
    text = source[expr.span.start : expr.span.end]
    replacement = ""
    label = ""
    if expr.kind == "int" and isinstance(expr.value, int):
        replacement = "1" if expr.value == 0 else "0"
        label = f"int-{text}-to-{replacement}"
    elif expr.kind == "bool":
        replacement = "false" if expr.value is True else "true"
        label = f"bool-{text}-to-{replacement}"
    elif expr.kind == "float":
        replacement = "1.0" if expr.value == 0.0 else "0.0"
        label = f"float-{text}-to-{replacement}"
    else:
        return
    if replacement == text:
        return
    sites.append((label, expr.span.start, expr.span.end, replacement))


def _replace_return(source: str, stmt: ReturnStmt, sites: list[_Site], ret: str | None) -> None:
    expr = stmt.expr
    if expr is None or ret is None:
        return
    text = source[expr.span.start : expr.span.end]
    replacement = _return_literal(ret, text)
    if replacement is None or replacement == text:
        return
    sites.append((f"return-to-{replacement}", expr.span.start, expr.span.end, replacement))


def _return_literal(ret: str, text: str) -> str | None:
    if ret == "Int":
        return "1" if text == "0" else "0"
    if ret == "Bool":
        return "false" if text == "true" else "true"
    if ret == "Float":
        return "1.0" if text == "0.0" else "0.0"
    if ret == "Text":
        return '"mut"' if text == '""' else '""'
    return None


def _source_bytes(source: str) -> bytes:
    """The attempt's original bytes. Invalid UTF-8 was decoded to lone surrogates.

    A caller's `str` can hold a surrogate that `surrogateescape` cannot map
    back to a byte, so that text is hashed with `surrogatepass` instead.
    """
    try:
        return source.encode("utf-8", errors="surrogateescape")
    except UnicodeEncodeError:
        return source.encode("utf-8", errors="surrogatepass")


def _source_hash(source: str) -> str:
    return "sha256:" + hashlib.sha256(_source_bytes(source)).hexdigest()


def _read_attempt(attempt: Path) -> str:
    return decode_source_bytes(attempt.read_bytes()) if attempt.is_file() else ""


def _sources(directory: Path) -> list[tuple[str, str]]:
    files = sorted(path for path in directory.rglob("*.tersa") if path.is_file())
    return [(f"hidden/{path.name}", path.read_text(encoding="utf-8")) for path in files]


def _read(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def _string(data: object, key: str) -> str:
    if not isinstance(data, dict):
        return ""
    value = data.get(key)
    return value if isinstance(value, str) else ""


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise TaskLoadError("effects must be a list of names", "I9022")
    return list(value)


def _positive(table: dict[str, object], key: str) -> int | None:
    if key not in table:
        return None
    value = table[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise TaskLoadError(f"{key} must be an integer", "I9022")
    if value <= 0:
        return None
    return value


def _optional_int(table: dict[str, object], key: str, default: int) -> int:
    if key not in table:
        return default
    value = table[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise TaskLoadError(f"{key} must be an integer", "I9022")
    return value


def _reference_fuel_field(table: dict[str, object]) -> int | None:
    if "reference_fuel" not in table:
        return None
    value = table["reference_fuel"]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TaskLoadError("reference_fuel must be an integer >= 0", "I9022")
    return value


def _float(table: object, key: str, default: float) -> float:
    if not isinstance(table, dict) or key not in table:
        return default
    value = table[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TaskLoadError(f"{key} must be a number", "I9022")
    return float(value)


def worker_main() -> int:
    """Child entry point: run the attempt the stdin request names and print its episode JSON.

    The `TERSALANG_HARNESS_*` variables are test hooks: `CRASH=1` exits 2 with
    no output, `FORGE=1` prints a forged result, and `SIGNAL` names a signal
    the worker sends itself.
    """
    if os.environ.get("TERSALANG_HARNESS_CRASH") == "1":
        return 2
    # Test hook: a result the parent must reject (it claims reward 1).
    if os.environ.get("TERSALANG_HARNESS_FORGE") == "1":
        sys.stdout.write(json.dumps({"schema": RESULT_SCHEMA, "reward": 1.0}) + "\n")
        return 0
    # Test hook, not a language feature. The child dies with a named signal
    # so a backend with no resource cap can still be classified.
    forced = os.environ.get("TERSALANG_HARNESS_SIGNAL")
    if forced:
        import signal

        number = getattr(signal, forced)
        signal.signal(number, signal.SIG_DFL)
        os.kill(os.getpid(), number)
    request = json.loads(sys.stdin.read() or "{}")
    task = load_task(Path(str(request["task"])))
    source = _read_attempt(Path(str(request["attempt"])))
    warning = request.get("isolation_warning")
    episode = run_episode(
        task,
        source,
        attempt_id=str(request.get("attempt_id") or ""),
        seed=int(request.get("seed") or 0),
        filename=Path(str(request["attempt"])).name,
        isolation=str(request.get("isolation") or "none"),
        isolation_warning=warning if isinstance(warning, str) else None,
    )
    sys.stdout.write(episode.to_json())
    return 0
