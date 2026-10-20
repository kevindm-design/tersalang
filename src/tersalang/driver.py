# SPDX-License-Identifier: Apache-2.0
"""Load a source file and check, run, or test it."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from tersalang.ast import Module
from tersalang.checker import check_module
from tersalang.diagnostics import Diagnostic, json_all, render_all
from tersalang.eval import ExecResult, Host, Interpreter, Trap
from tersalang.fmt import fmt_skip_warnings
from tersalang.lexer import lex_text
from tersalang.limits import LimitConfig
from tersalang.parser import parse_module
from tersalang.show import show
from tersalang.task_interface import signature_diagnostics
from tersalang.typesys import EFFECTS
from tersalang.values import VChoice
from tersalang.version import (
    DEFAULT_PROPERTY_CASES,
    DEFAULT_TEST_OUTPUT_BYTES,
    MIN_INT_BITS,
)


@dataclass
class Outcome:
    """What one check, run, or test produced: the CLI exit code, output, and diagnostics."""

    exit_code: int
    stdout: str = ""
    stderr: str = ""
    diagnostics: list[Diagnostic] = field(default_factory=list)
    fuel_used: int = 0
    memory_used: int = 0


def compile_text(filename: str, text: str, *, mode: str) -> tuple[Module | None, list[Diagnostic]]:
    """Lex, parse, and check `text`; the checker runs only when the parse had no error."""
    _source, tokens, diagnostics = lex_text(filename, text)
    module = parse_module(_source, tokens, diagnostics)
    if module is not None and not _errors(diagnostics):
        diagnostics.extend(check_module(module, mode=mode))
    return module, diagnostics


def check_text(
    filename: str,
    text: str,
    *,
    mode: str = "dev",
    as_json: bool = False,
    interface: tuple[str, str] | None = None,
) -> Outcome:
    """Compile without running. `check` and `fmt` always report `W1104`.

    `run`, `sandbox`, and `test` report it only beside an error that stops
    the run, and the harness never does. `interface` is a task interface's
    file name and text; the program is then also held to its signatures
    (`E3047`), as `tersa harness run` does.
    """
    module, diagnostics = compile_text(filename, text, mode=mode)
    if interface is not None and module is not None:
        name, source = interface
        _source, tokens, parsed = lex_text(name, source)
        required = parse_module(_source, tokens, parsed)
        if required is not None and not _errors(parsed):
            diagnostics.extend(signature_diagnostics(module, required))
    diagnostics.extend(fmt_skip_warnings(filename, text))
    code = 3 if _errors(diagnostics) else 0
    return diagnostics_outcome(code, diagnostics, as_json=as_json)


def run_text(
    filename: str,
    text: str,
    *,
    mode: str = "dev",
    grants: dict[str, list[str]] | None = None,
    seed: int = 0,
    limits: LimitConfig | None = None,
    args: tuple[str, ...] = (),
    env: dict[str, str] | None = None,
    stdin: str = "",
    as_json: bool = False,
) -> Outcome:
    """Compile `text` and run `main`.

    The exit code is 0 on success, 1 when `main` returns `Error`, 2 for a trap,
    3 when the program does not compile, and 4 for a bad grant (`I9010`, or
    `I9017` in RL mode) or a wall-clock stop (`I9013`). Warnings are reported
    only beside a diagnostic that stops the run.
    """
    invalid = validate_grants(grants or {}, mode=mode)
    if invalid is not None:
        return diagnostics_outcome(4, [invalid], as_json=as_json)
    module, diagnostics = compile_text(filename, text, mode=mode)
    if module is None or _errors(diagnostics):
        return _stopped_by_check(filename, text, diagnostics, as_json=as_json)
    host = _host(
        filename,
        mode=mode,
        grants=grants or {},
        seed=seed,
        limits=limits or LimitConfig(),
        args=args,
        env=env or {},
        stdin=stdin,
    )
    try:
        result = Interpreter(module, host).run_main()
    except Trap as trapped:
        result = ExecResult(None, "", "", trapped.diagnostic, 0, 0, False)
    return _from_exec(result, as_json=as_json, warnings=_warnings(filename, text, diagnostics))


def run_tests(
    filename: str,
    text: str,
    *,
    mode: str = "test",
    grants: dict[str, list[str]] | None = None,
    seed: int = 0,
    cases: int = DEFAULT_PROPERTY_CASES,
    limits: LimitConfig | None = None,
    as_json: bool = False,
) -> Outcome:
    """Compile `text` and run its doc examples, then its tests, `cases` cases per property.

    Output is capped at `DEFAULT_TEST_OUTPUT_BYTES` unless `limits` says otherwise.
    A failure or trap exits 1; without `as_json`, stdout ends with the counts line.
    """
    invalid = validate_grants(grants or {}, mode=mode)
    if invalid is not None:
        return diagnostics_outcome(4, [invalid], as_json=as_json)
    module, diagnostics = compile_text(filename, text, mode=mode)
    if module is None or _errors(diagnostics):
        return _stopped_by_check(filename, text, diagnostics, as_json=as_json)
    config = limits or LimitConfig(output_bytes=DEFAULT_TEST_OUTPUT_BYTES)
    host = _host(
        filename,
        mode=mode,
        grants=grants or {},
        seed=seed,
        limits=config,
        args=(),
        env={},
        stdin="",
    )
    try:
        result = Interpreter(module, host).run_tests(cases=cases)
    except Trap as trapped:
        result = ExecResult(None, "", "", trapped.diagnostic, 0, 0, False)
    if result.counts is not None and not as_json:
        if result.stdout and not result.stdout.endswith("\n"):
            result.stdout += "\n"
        result.stdout += result.counts.summary() + "\n"
    return _from_exec(
        result, as_json=as_json, test=True, warnings=_warnings(filename, text, diagnostics)
    )


def _warnings(filename: str, text: str, diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    """The warnings to print beside an error that stops the run, `W1104` included.

    Warnings are printed only alongside such an error (Design §18.2.1).
    """
    return [item for item in diagnostics if item.severity == "warning"] + fmt_skip_warnings(
        filename, text
    )


def _stopped_by_check(
    filename: str, text: str, diagnostics: list[Diagnostic], *, as_json: bool
) -> Outcome:
    return diagnostics_outcome(3, diagnostics + fmt_skip_warnings(filename, text), as_json=as_json)


def validate_limits(limits: LimitConfig) -> Diagnostic | None:
    """An `I9010` for the first limit out of range, or None when every limit is usable."""
    if limits.max_int_bits < MIN_INT_BITS:
        return _config_error(f"max_int_bits must be at least {MIN_INT_BITS}")
    if limits.max_depth < 1:
        return _config_error("max_depth must be at least 1")
    if limits.fuel is not None and limits.fuel < 1:
        return _config_error("fuel must be at least 1")
    if limits.memory_units is not None and limits.memory_units < 1:
        return _config_error("memory_units must be at least 1")
    if limits.output_bytes is not None and limits.output_bytes < 0:
        return _config_error("output_bytes must be at least 0")
    if limits.wall_ms is not None and limits.wall_ms < 1:
        return _config_error("wall_ms must be at least 1")
    return None


SCOPED_EFFECTS = frozenset({"FileRead", "FileWrite", "Net"})
# RL mode never grants these. File and net access would let an attempt read
# hidden tests or leave the interpreter. Python is host mode only.
RL_DENIED_EFFECTS = frozenset({"FileRead", "FileWrite", "Net", "Python"})
_SCOPE_KIND = {"FileRead": "FOLDER", "FileWrite": "FOLDER", "Net": "HOST"}


def parse_allows(items: list[str]) -> tuple[dict[str, list[str]], Diagnostic | None]:
    """`--allow EFFECT` or `--allow EFFECT=SCOPE`. A scoped effect needs its scope (§11.2)."""
    grants: dict[str, list[str]] = {}
    for item in items:
        effect, has_scope, scope = item.partition("=")
        grants.setdefault(effect, [])
        if has_scope:
            grants[effect].append(scope)
        problem = _grant_problem(effect, grants[effect], given=bool(has_scope))
        if problem is not None:
            return grants, _config_error(problem)
    return grants, None


def validate_grants(grants: dict[str, list[str]], *, mode: str = "dev") -> Diagnostic | None:
    """The first bad grant: `I9010` for an unknown effect or scope misuse, `I9017` in RL mode.

    RL mode refuses every effect in `RL_DENIED_EFFECTS`. None means all grants are usable.
    """
    for effect, scopes in grants.items():
        problem = _grant_problem(effect, scopes, given=bool(scopes))
        if problem is not None:
            return _config_error(problem)
        if mode == "rl" and effect in RL_DENIED_EFFECTS:
            return _config_error(f"RL mode cannot grant {effect}", code="I9017")
    return None


def _grant_problem(effect: str, scopes: list[str], *, given: bool) -> str | None:
    if effect not in EFFECTS:
        return f"unknown effect `{effect}`"
    if effect in SCOPED_EFFECTS:
        if not scopes or any(scope == "" for scope in scopes):
            kind = _SCOPE_KIND[effect]
            return f"{effect} needs a scope: --allow {effect}={kind}"
    elif given:
        return f"{effect} does not take a scope"
    return None


def _host(
    filename: str,
    *,
    mode: str,
    grants: dict[str, list[str]],
    seed: int,
    limits: LimitConfig,
    args: tuple[str, ...],
    env: dict[str, str],
    stdin: str,
) -> Host:
    path = Path(filename)
    source_dir = str(path.parent.resolve()) if path.parent != Path("") else "."
    return Host(
        grants=grants,
        seed=seed,
        args=args,
        env=env,
        stdin=stdin,
        mode=mode,
        limits=limits,
        source_dir=source_dir if source_dir else ".",
        filename=filename,
    )


def _from_exec(
    result: ExecResult,
    *,
    as_json: bool,
    test: bool = False,
    warnings: list[Diagnostic] | None = None,
) -> Outcome:
    diagnostics: list[Diagnostic] = []
    stderr = result.stderr
    exit_code = 0
    if result.diagnostic is not None:
        diagnostics.append(result.diagnostic)
        diagnostics.extend(result.more_failures)
        diagnostics.extend(warnings or [])
        exit_code = _exit_for(result.diagnostic, test=test)
    elif (
        isinstance(result.value, VChoice)
        and result.value.type_name == "Result"
        and result.value.case == "Error"
    ):
        exit_code = 1
        shown = show(result.value.fields[0])
        stderr += f"error: {shown}\n"
    if result.output_truncated:
        from tersalang.source import Span

        note = Diagnostic(
            code="W6205",
            message="console output was truncated",
            file="<run>",
            span=Span("<run>", 0, 0, 1, 1, 1, 1),
        )
        diagnostics.append(note)
    outcome = diagnostics_outcome(
        exit_code, diagnostics, as_json=as_json, stdout=result.stdout, stderr=stderr
    )
    outcome.fuel_used = result.fuel_used
    outcome.memory_used = result.memory_used
    return outcome


def diagnostics_outcome(
    code: int,
    diagnostics: list[Diagnostic],
    *,
    as_json: bool,
    stdout: str = "",
    stderr: str = "",
) -> Outcome:
    """Human diagnostics go to stderr. `--json` ends stdout with one JSON array line."""
    if as_json:
        if stdout and not stdout.endswith("\n"):
            stdout += "\n"
        return Outcome(code, stdout + json_all(diagnostics), stderr, diagnostics)
    return Outcome(code, stdout, stderr + render_all(diagnostics), diagnostics)


def _exit_for(diagnostic: Diagnostic, *, test: bool) -> int:
    if diagnostic.code in {"I9010", "I9013"}:
        return 4
    if diagnostic.code.startswith("T"):
        return 1 if test else 2
    if diagnostic.code.startswith("E") or diagnostic.code.startswith("W"):
        return 3
    return 2


def _errors(diagnostics: list[Diagnostic]) -> bool:
    return any(item.severity == "error" for item in diagnostics)


def _config_error(message: str, *, code: str = "I9010") -> Diagnostic:
    from tersalang.source import Span

    return Diagnostic(
        code=code, message=message, file="<cli>", span=Span("<cli>", 0, 0, 1, 1, 1, 1)
    )


def default_limits(
    *,
    test: bool,
    fuel: int | None,
    memory: int | None,
    bits: int,
    depth: int,
    output: int | None,
    wall_ms: int | None = None,
) -> LimitConfig:
    """The limits the CLI flags ask for.

    Under `test`, an unset output cap becomes `DEFAULT_TEST_OUTPUT_BYTES`.
    """
    if output is None and test:
        output = DEFAULT_TEST_OUTPUT_BYTES
    return LimitConfig(
        fuel=fuel,
        memory_units=memory,
        max_int_bits=bits,
        max_depth=depth,
        output_bytes=output,
        wall_ms=wall_ms,
    )
