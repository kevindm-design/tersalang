# SPDX-License-Identifier: Apache-2.0
"""Run the .tersa programs under conformance/."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from tersalang.driver import check_text, run_tests, run_text
from tersalang.limits import LimitConfig
from tersalang.source import decode_source_bytes

ROOT = Path(__file__).resolve().parents[1]
PROGRAMS = sorted((ROOT / "conformance").rglob("*.tersa"))


def _doc_script() -> ModuleType:
    path = ROOT / "scripts" / "gen_diagnostics_doc.py"
    spec = importlib.util.spec_from_file_location("gen_diagnostics_doc", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


DOCS = _doc_script()
FIXED = [path for path in PROGRAMS if b"\n# fixed: " in path.read_bytes()]


def _header(text: str) -> dict[str, object]:
    expect = "check-ok"
    stdout: list[str] = []
    allows: list[str] = []
    bits = 65536
    fuel: int | None = None
    cases = 5
    mode = "dev"
    mode_set = False
    memory: int | None = None
    depth = 1000
    output: int | None = None
    interface: str | None = None
    for line in text.splitlines():
        if not line.startswith("#"):
            continue
        body = line[1:].strip()
        if body.startswith("|"):
            stdout.append(body[1:])
            continue
        if ":" not in body:
            continue
        key, value = body.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key == "expect":
            expect = value
        elif key == "allow":
            allows.append(value)
        elif key == "max-int-bits":
            bits = int(value)
        elif key == "fuel":
            fuel = int(value)
        elif key == "cases":
            cases = int(value)
        elif key == "mode":
            mode = value
            mode_set = True
        elif key == "memory":
            memory = int(value)
        elif key == "depth":
            depth = int(value)
        elif key == "output-bytes":
            output = int(value)
        elif key == "interface":
            interface = value
    return {
        "expect": expect,
        "stdout": "\n".join(stdout) + ("\n" if stdout else ""),
        "allows": allows,
        "bits": bits,
        "fuel": fuel,
        "cases": cases,
        "mode": mode,
        "mode_set": mode_set,
        "memory": memory,
        "depth": depth,
        "output": output,
        "interface": interface,
    }


def _interface(path: Path, header: dict[str, object]) -> tuple[str, str]:
    name = header["interface"]
    assert isinstance(name, str), f"{path.name}: harness-error needs `# interface: FILE`"
    return name, decode_source_bytes((path.parent / name).read_bytes())


def _grants(allows: list[str]) -> dict[str, list[str]]:
    grants: dict[str, list[str]] = {}
    for item in allows:
        if "=" in item:
            effect, scope = item.split("=", 1)
            grants.setdefault(effect, []).append(scope)
        else:
            grants.setdefault(item, [])
    return grants


@pytest.mark.parametrize("path", PROGRAMS, ids=lambda path: path.stem)
def test_program(path: Path) -> None:
    text = decode_source_bytes(path.read_bytes())
    header = _header(text.lstrip("\ufeff"))
    expect = str(header["expect"])
    mode = str(header["mode"])
    limits = LimitConfig(
        fuel=header["fuel"] if isinstance(header["fuel"], int) else None,
        memory_units=header["memory"] if isinstance(header["memory"], int) else None,
        max_int_bits=int(header["bits"]),
        max_depth=int(header["depth"]),
        output_bytes=header["output"] if isinstance(header["output"], int) else None,
    )
    grants = _grants(list(header["allows"]))  # type: ignore[arg-type]
    if expect == "check-ok":
        outcome = check_text(path.name, text, mode=mode)
        assert outcome.exit_code == 0, outcome.stderr
        return
    if expect.startswith("check-error"):
        code = expect.split()[1]
        outcome = check_text(path.name, text, mode=mode)
        assert outcome.exit_code == 3, outcome.stderr
        assert any(item.code == code for item in outcome.diagnostics), outcome.stderr
        return
    if expect.startswith("harness-error"):
        code = expect.split()[1]
        outcome = check_text(path.name, text, mode="rl", interface=_interface(path, header))
        assert outcome.exit_code == 3, outcome.stderr
        assert any(item.code == code for item in outcome.diagnostics), outcome.stderr
        return
    if expect.startswith("check-warn") or expect.startswith("no-warn"):
        code = expect.split()[1]
        outcome = check_text(path.name, text, mode=mode)
        assert outcome.exit_code == 0, outcome.stderr
        present = any(item.code == code for item in outcome.diagnostics)
        assert present if expect.startswith("check-warn") else not present, outcome.stderr
        return
    if expect.startswith("trap"):
        code = expect.split()[1]
        outcome = run_text(path.name, text, mode=mode, grants=grants, limits=limits)
        assert outcome.exit_code == 2, outcome.stderr
        assert any(item.code == code for item in outcome.diagnostics), outcome.stderr
        return
    if expect.startswith("run-error"):
        code = expect.split()[1]
        outcome = run_text(path.name, text, mode=mode, grants=grants, limits=limits)
        assert outcome.exit_code == 3, outcome.stderr
        assert any(item.code == code for item in outcome.diagnostics), outcome.stderr
        return
    if expect.startswith("test-fail"):
        code = expect.split()[1]
        outcome = run_tests(
            path.name, text, mode="test", grants=grants, cases=int(header["cases"]), limits=limits
        )
        assert outcome.exit_code == 1, outcome.stderr
        assert any(item.code == code for item in outcome.diagnostics), outcome.stderr
        return
    if expect.startswith("run-note"):
        code = expect.split()[1]
        outcome = run_text(path.name, text, mode=mode, grants=grants, limits=limits)
        assert outcome.exit_code == 0, outcome.stderr
        assert any(item.code == code for item in outcome.diagnostics), outcome.stderr
        return
    if expect == "stdout":
        outcome = run_text(path.name, text, mode=mode, grants=grants, limits=limits)
        assert outcome.exit_code == 0, outcome.stderr
        assert outcome.stdout == header["stdout"]
        return
    if expect == "tests-pass":
        test_mode = mode if bool(header["mode_set"]) else "test"
        outcome = run_tests(
            path.name,
            text,
            mode=test_mode,
            grants=grants,
            cases=int(header["cases"]),
            limits=limits,
        )
        assert outcome.exit_code == 0, outcome.stderr
        return
    if expect == "run-ok":
        outcome = run_text(path.name, text, mode=mode, grants=grants, limits=limits)
        assert outcome.exit_code == 0, outcome.stderr
        return
    raise AssertionError(f"unknown expect {expect}")


@pytest.mark.parametrize("path", FIXED, ids=lambda path: path.stem)
def test_fixed_example(path: Path) -> None:
    """The `# fixed:` edits turn a wrong program into a clean one (docs/diagnostics.md)."""
    text = decode_source_bytes(path.read_bytes())
    header = _header(text)
    expect = str(header["expect"])
    kind, code = expect.split()
    fixed = DOCS.apply_fixes(text, DOCS.fix_edits(text))
    mode = str(header["mode"])
    limits = LimitConfig(
        fuel=header["fuel"] if isinstance(header["fuel"], int) else None,
        memory_units=header["memory"] if isinstance(header["memory"], int) else None,
        max_int_bits=int(header["bits"]),
        max_depth=int(header["depth"]),
        output_bytes=header["output"] if isinstance(header["output"], int) else None,
    )
    grants = _grants(list(header["allows"]))  # type: ignore[arg-type]
    if kind in {"check-error", "check-warn"}:
        outcome = check_text(path.name, fixed, mode=mode)
    elif kind == "harness-error":
        outcome = check_text(path.name, fixed, mode="rl", interface=_interface(path, header))
    elif kind == "test-fail":
        outcome = run_tests(
            path.name, fixed, mode="test", grants=grants, cases=int(header["cases"]), limits=limits
        )
    else:
        outcome = run_text(path.name, fixed, mode=mode, grants=grants, limits=limits)
    assert outcome.exit_code == 0, (fixed, outcome.stderr)
    assert code not in {item.code for item in outcome.diagnostics}, (fixed, outcome.stderr)
    assert not [item for item in outcome.diagnostics if item.severity == "error"], outcome.stderr


def test_every_fixed_example_has_a_wrong_program_the_doc_shows() -> None:
    chosen = DOCS.examples()
    for path in FIXED:
        header = _header(decode_source_bytes(path.read_bytes()))
        code = str(header["expect"]).split()[1]
        assert chosen[code].path == path, code


def test_every_wrong_example_has_a_fixed_form_or_says_why_not() -> None:
    for code, example in DOCS.examples().items():
        assert example.fixes or example.no_fix, code
