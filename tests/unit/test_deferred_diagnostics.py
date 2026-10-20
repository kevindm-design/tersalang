# SPDX-License-Identifier: Apache-2.0
"""Diagnostics that a .tersa program cannot produce yet, plus the closed-file trap."""

from __future__ import annotations

import pytest

from tersalang.driver import compile_text
from tersalang.eval import Host, Interpreter, Trap
from tersalang.values import VResource


def test_t6012_closed_file_is_a_trap() -> None:
    source = "module closed\n\nfunction main() returns Unit\ndo\n  return\nend\n"
    module, diagnostics = compile_text("closed.tersa", source, mode="dev")
    assert module is not None
    assert not any(item.severity == "error" for item in diagnostics)
    interpreter = Interpreter(module, Host())
    resource = VResource("File", "closed.txt", closed=True, lines=["x"])
    with pytest.raises(Trap) as caught:
        interpreter._file_builtin("file.read_line", [resource], module.span)
    assert caught.value.diagnostic.code == "T6012"


@pytest.mark.skip(
    reason=(
        "E2101 needs a lockfile reader. The catalog says a dependency's content "
        "hash does not match tersa.lock, and nothing loads tersa.lock."
    )
)
def test_e2101_lockfile_hash_mismatch() -> None:
    raise AssertionError("lockfiles are not implemented")


@pytest.mark.skip(
    reason=(
        "I9011 means the Unicode version does not match the language pin, "
        "which matches spec/diagnostics.yaml and Language Reference v0.5.6. "
        "No pin is implemented (version.UNICODE_NOTE is host-unicodedata), "
        "so nothing emits I9011."
    )
)
def test_i9011_unicode_pin() -> None:
    raise AssertionError("no Unicode version pin is implemented")


def test_i9013_os_backstop() -> None:
    """The wall-clock backstop is covered in tests/unit/test_harness.py."""
    from tersalang.limits import LimitConfig
    from tersalang.sandbox import run_sandboxed

    program = (
        "module spin\n\nfunction main() returns Unit\ndo\n"
        "  while true\n  do\n    let _ = 1\n  end\n  return\nend\n"
    )
    outcome = run_sandboxed("spin.tersa", program, limits=LimitConfig(fuel=10_000_000, wall_ms=30))
    assert any(item.code == "I9013" for item in outcome.diagnostics)
