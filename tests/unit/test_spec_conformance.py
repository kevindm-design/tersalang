# SPDX-License-Identifier: Apache-2.0
"""Spec rules that the conformance corpus does not reach."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pytest

from tersalang.cli import build_parser, main
from tersalang.driver import check_text, run_tests, run_text
from tersalang.lexer import lex_text
from tersalang.limits import LimitConfig


def _show(expr: str) -> tuple[int, str, list[str]]:
    src = (
        "module p\n\nimport std.console exposing print\nimport std.math\n\n"
        "function main() returns Unit\n  uses Console\ndo\n"
        f"  print(show({expr}))\n  return\nend\n"
    )
    outcome = run_text("p.tersa", src, grants={"Console": []}, limits=LimitConfig())
    return outcome.exit_code, outcome.stdout.strip(), [d.code for d in outcome.diagnostics]


@pytest.mark.parametrize(
    ("expr", "shown"),
    [
        ("1.0 / 0.0", "Float.infinity"),
        ("-1.0 / 0.0", "-Float.infinity"),
        ("1.0 / -0.0", "-Float.infinity"),
        ("0.0 / 0.0", "Float.nan"),
        ("Float.sqrt(-1.0)", "Float.nan"),
        ("math.sqrt(-1.0)", "Float.nan"),
        ("math.log(0.0)", "-Float.infinity"),
        ("math.log2(0.0)", "-Float.infinity"),
        ("math.log(-1.0)", "Float.nan"),
        ("math.log10(-1.0)", "Float.nan"),
        ("math.exp(1000.0)", "Float.infinity"),
        ("math.asin(2.0)", "Float.nan"),
        ("math.acos(2.0)", "Float.nan"),
        ("math.sin(Float.infinity)", "Float.nan"),
        ("math.float_pow(10.0, 400.0)", "Float.infinity"),
        ("math.float_pow(-10.0, 401.0)", "-Float.infinity"),
        ("math.float_pow(-8.0, 0.5)", "Float.nan"),
        ("math.float_pow(0.0, -1.0)", "Float.infinity"),
        ("Float.fma(Float.infinity, 0.0, 1.0)", "Float.nan"),
        ("Float.fma(1.0e308, 10.0, 0.0)", "Float.infinity"),
    ],
)
def test_float_operations_follow_ieee_instead_of_raising(expr: str, shown: str) -> None:
    assert _show(expr) == (0, shown, [])


def test_named_argument_token_never_swallows_equality() -> None:
    _source, tokens, diagnostics = lex_text("p.tersa", "f(x == y, z = 1)\n")
    assert not diagnostics
    assert [(token.kind, token.text) for token in tokens][2:8] == [
        ("lower", "x"),
        ("==", "=="),
        ("lower", "y"),
        (",", ","),
        ("named_arg", "z"),
        ("int", "1"),
    ]


def _check(body: str, decls: str = "") -> list[str]:
    src = f"module p\n\n{decls}function main() returns Unit\ndo\n{body}  return\nend\n"
    return [d.code for d in check_text("p.tersa", src).diagnostics]


@pytest.mark.parametrize(
    "body",
    [
        "  let s = Set.from_list([1.5])\n",
        "  let s: Set[Float] = Set.empty()\n",
        "  let m: MutableMap[Float, Int] = MutableMap.new()\n",
        "  let f = function (x: Int) returns Int\n    do\n      x\n    end\n"
        "  let s = Set.from_list([f])\n",
    ],
)
def test_unhashable_set_elements_and_map_keys_are_e3042(body: str) -> None:
    assert _check(body) == ["E3042"]


def test_unhashable_key_in_a_signature_is_reported_once() -> None:
    decls = "function size(m: Map[Float, Int]) returns Int\ndo\n  return m.length()\nend\n\n"
    assert _check("", decls) == ["E3042"]


def test_hashable_sets_check_cleanly() -> None:
    assert _check('  let s = Set.from_list(["a", "b"])\n  let n = s.length()\n') == []


GENERIC = (
    "function pick[T](a: T, b: T) returns T\ndo\n  return a\nend\n\n"
    "function first[T](xs: List[T]) returns Option[T]\ndo\n  return xs.get(0)\nend\n\n"
)


@pytest.mark.parametrize(
    ("body", "codes"),
    [
        ("  let n: Int = pick(1, 2)\n", []),
        ('  let o: Option[Text] = first(["a"])\n', []),
        ("  let e: Option[Int] = first([])\n", []),
        ('  let n = pick(1, "a")\n', ["E3000"]),
        ("  let t: Text = pick(1, 2)\n", ["E3000", "E3000"]),
        ('  let o: Option[Int] = first(["a"])\n', ["E3000"]),
    ],
)
def test_generic_calls_infer_type_arguments(body: str, codes: list[str]) -> None:
    assert _check(body, GENERIC) == codes


SPIN_TESTS = """module p

function spin(n: Int) returns Int
do
  var i = 0
  while i < n
  do
    set i = i + 1
  end
  return i
end

test "one"
do
  expect spin(300) == 300
end

test "two"
do
  expect spin(300) == 300
end

test "three"
do
  expect 1 == 2
end

test "four"
do
  fail "boom"
end
"""


def test_tersa_test_reports_every_failing_test() -> None:
    outcome = run_tests("p.tersa", SPIN_TESTS)
    assert outcome.exit_code == 1
    assert [d.code for d in outcome.diagnostics] == ["T6031", "T6030"]
    assert outcome.stderr.count("trap[") == 2


def test_tersa_test_fuel_is_per_test_and_exhaustion_is_a_trap() -> None:
    one_test = run_tests("p.tersa", SPIN_TESTS.split('test "two"')[0])
    budget = one_test.fuel_used + 10
    roomy = run_tests("p.tersa", SPIN_TESTS, limits=LimitConfig(fuel=budget))
    assert [d.code for d in roomy.diagnostics] == ["T6031", "T6030"]
    tight = run_tests("p.tersa", SPIN_TESTS, limits=LimitConfig(fuel=budget // 2))
    assert [d.code for d in tight.diagnostics] == ["T6201", "T6201", "T6031", "T6030"]
    assert tight.exit_code == 1


def test_tersa_test_memory_and_depth_exhaustion_are_traps() -> None:
    deep = (
        "module p\n\nfunction down(n: Int) returns Int\ndo\n  if n == 0 then\n    return 0\n"
        "  end\n  return 1 + down(n - 1)\nend\n\n"
        'test "deep"\ndo\n  expect down(5000) == 5000\nend\n\n'
        'test "list"\ndo\n  let xs = [1, 2, 3, 4, 5, 6, 7, 8]\n  expect xs.length() == 8\nend\n'
    )
    outcome = run_tests("p.tersa", deep, limits=LimitConfig(memory_units=5))
    assert [d.code for d in outcome.diagnostics] == ["T6203", "T6202"]


SLOW_CONST = """module p

import std.console exposing print

let big: Int = spin(100000)

## Example: spin(100000) > 0
function spin(n: Int) returns Int
do
  var i = 0
  while i < n
  do
    set i = i + 1
  end
  return i
end

function main() returns Unit
  uses Console
do
  print(show(big))
end

test "uses the constant"
do
  expect big > 0
end

test "does not"
do
  expect spin(1) == 1
end
"""


def test_running_out_inside_a_constant_is_a_trap() -> None:
    outcome = run_text("p.tersa", SLOW_CONST, grants={"Console": []}, limits=LimitConfig(fuel=1000))
    assert outcome.exit_code == 2
    assert [(d.code, d.span.start_line) for d in outcome.diagnostics] == [("T6201", 5)]


def test_tersa_test_traps_a_constant_and_a_doc_example_per_test() -> None:
    outcome = run_tests("p.tersa", SLOW_CONST, limits=LimitConfig(fuel=1000))
    assert outcome.exit_code == 1
    assert [(d.code, d.span.start_line) for d in outcome.diagnostics] == [
        ("T6201", 5),
        ("T6201", 5),
        ("T6201", 5),
    ]
    deep = SLOW_CONST.replace("let big: Int = spin(100000)", "let big: Int = 1").replace(
        "spin(100000) > 0", "spin(-1) > 0\n## Example: spin(100000) > 0"
    )
    outcome = run_tests("p.tersa", deep, limits=LimitConfig(fuel=1000))
    assert [(d.code, d.span.start_line) for d in outcome.diagnostics] == [
        ("T6031", 9),
        ("T6201", 9),
    ]


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ("12", "Some(12)"),
        ("-7", "Some(-7)"),
        ("²", "None"),
        ("١٢", "None"),
        ("𝟗", "None"),
        ("1²", "None"),
    ],
)
def test_int_parse_accepts_only_ascii_digits(text: str, shown: str) -> None:
    assert _show(f'Int.parse("{text}")') == (0, shown, [])


@pytest.mark.parametrize("text", ["²", "[1, ٣]", "١٢", "1.²", "1e²"])
def test_json_numbers_use_ascii_digits(text: str) -> None:
    src = (
        "module p\n\nimport std.console exposing print\nimport std.json\n\n"
        "function main() returns Unit\n  uses Console\ndo\n"
        f'  print(show(json.parse("{text}")))\nend\n'
    )
    outcome = run_text("p.tersa", src, grants={"Console": []}, limits=LimitConfig())
    assert outcome.exit_code == 0
    assert outcome.stdout.startswith("Error(Invalid(")


@pytest.mark.parametrize(
    "call", ["file.read_text(PATH)", 'file.write_text(PATH, "x")', "file.list_dir(PATH)"]
)
@pytest.mark.parametrize(
    ("path", "shown"),
    [
        ("a\\u{0}b", 'Error(Io("path contains a NUL character"))'),
        ("loop1", 'Error(Io("path `loop1` has a symlink loop"))'),
        ("x" * 300, None),
    ],
    ids=["nul", "symlink-loop", "long-name"],
)
def test_unresolvable_paths_are_file_errors_not_crashes(
    tmp_path: Path, call: str, path: str, shown: str | None
) -> None:
    try:
        os.symlink(tmp_path / "loop2", tmp_path / "loop1")
        os.symlink(tmp_path / "loop1", tmp_path / "loop2")
    except OSError:
        if path == "loop1":
            pytest.skip("this OS user cannot create symlinks")
    src = (
        "module p\n\nimport std.console exposing print\nimport std.file\n\n"
        "function main() returns Unit\n  uses Console, FileRead, FileWrite\ndo\n"
        f"  print(show({call.replace('PATH', chr(34) + path + chr(34))}))\nend\n"
    )
    scope = [str(tmp_path)]
    grants = {"Console": [], "FileRead": scope, "FileWrite": scope}
    outcome = run_text("p.tersa", src, grants=grants, limits=LimitConfig())
    assert (outcome.exit_code, [d.code for d in outcome.diagnostics]) == (0, [])
    assert outcome.stdout.startswith("Error(")
    if shown is not None:
        assert outcome.stdout.strip() == shown


HELLO = (
    "module hello\n\nimport std.console exposing print\n\n"
    'function main() returns Unit\n  uses Console\ndo\n  print("hi")\nend\n'
)


@pytest.mark.parametrize(
    "flags",
    [
        ["--max-int-bits", "0"],
        ["--max-depth", "0"],
        ["--wall-ms", "0"],
        ["--wall-ms", "-5"],
        ["--fuel", "abc"],
        ["--no-such-flag"],
    ],
)
@pytest.mark.parametrize("command", ["run", "sandbox", "test"])
def test_invalid_cli_limits_exit_4_not_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: str, flags: list[str]
) -> None:
    source = tmp_path / "hello.tersa"
    source.write_text(HELLO, encoding="utf-8")
    try:
        code = main([command, str(source), "--allow", "Console", *flags])
    except SystemExit as exc:
        code = exc.code
    assert code == 4, flags
    captured = capsys.readouterr()
    assert "hi" not in captured.out
    assert "I9013" not in captured.err


def _parsers(parser: argparse.ArgumentParser) -> list[argparse.ArgumentParser]:
    found = [parser]
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for child in action.choices.values():
                found.extend(_parsers(child))
    return found


def test_every_cli_flag_has_help() -> None:
    missing = [
        f"{parser.prog} {'/'.join(action.option_strings) or action.dest}"
        for parser in _parsers(build_parser())
        for action in parser._actions
        if not isinstance(action, argparse._SubParsersAction) and not action.help
    ]
    assert missing == []


def _json_tail(out: str) -> list[dict[str, object]]:
    lines = out.splitlines()
    assert lines, "stdout is empty"
    payload = json.loads(lines[-1])
    assert isinstance(payload, list)
    return payload


JSON_PROGRAM = """module w

import std.console exposing print

function main() returns Unit
  uses Console
do
  print("hi")
  let x = 1 div 0
  return
end
"""


@pytest.mark.parametrize(
    ("argv", "exit_code", "codes", "printed"),
    [
        (["check"], 0, [], []),
        (["check", "--parse-only"], 0, [], []),
        (["run", "--allow", "Console"], 2, ["T6002"], ["hi"]),
        (["sandbox", "--allow", "Console"], 2, ["T6002"], ["hi"]),
        (["run", "--allow", "Console", "--fuel", "0"], 4, ["I9010"], []),
    ],
)
def test_json_goes_to_stdout_as_one_final_line(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    exit_code: int,
    codes: list[str],
    printed: list[str],
) -> None:
    source = tmp_path / "w.tersa"
    source.write_text(JSON_PROGRAM, encoding="utf-8")
    code = main([argv[0], str(source), *argv[1:], "--json"])
    captured = capsys.readouterr()
    assert code == exit_code
    assert captured.err == ""
    payload = _json_tail(captured.out)
    assert [item["code"] for item in payload] == codes
    assert captured.out.splitlines()[:-1] == printed


def test_json_for_a_failing_test_file_goes_to_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "t.tersa"
    source.write_text('module t\n\ntest "no"\ndo\n  expect 1 == 2\nend\n', encoding="utf-8")
    code = main(["test", str(source), "--json"])
    captured = capsys.readouterr()
    assert code == 1
    assert "T6031" in [item["code"] for item in _json_tail(captured.out)]
    assert "T6031" not in captured.err


def _file_call(tmp_path: Path, call: str) -> str:
    src = (
        "module p\n\nimport std.console exposing print\nimport std.file\n\n"
        "function main() returns Unit\n  uses Console, FileRead, FileWrite\ndo\n"
        f"  print(show({call}))\nend\n"
    )
    scope = [str(tmp_path)]
    grants = {"Console": [], "FileRead": scope, "FileWrite": scope}
    outcome = run_text("p.tersa", src, grants=grants, limits=LimitConfig())
    assert (outcome.exit_code, [d.code for d in outcome.diagnostics]) == (0, [])
    return outcome.stdout.strip()


@pytest.mark.parametrize(
    "call",
    [
        'File.write_text("d", "x")',
        'File.write_text("d/missing/x.txt", "x")',
        'File.read_text("bad.txt")',
    ],
)
def test_file_errors_name_only_the_path_the_program_passed(tmp_path: Path, call: str) -> None:
    (tmp_path / "d").mkdir()
    (tmp_path / "bad.txt").write_bytes(b"\xff\xfe")
    shown = _file_call(tmp_path, call)
    assert shown.startswith("Error(")
    for host in {str(tmp_path), str(tmp_path.resolve()), tmp_path.name}:
        assert host not in shown
    assert any(token in shown for token in ("`d`", '"d"', '"d/missing/x.txt"', "`bad.txt`"))


@pytest.mark.skipif(
    not hasattr(os, "geteuid") or os.geteuid() == 0, reason="needs a non-root POSIX user"
)
def test_an_unreadable_file_is_denied_with_the_program_path(tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("x", encoding="utf-8")
    secret.chmod(0)
    try:
        shown = _file_call(tmp_path, 'File.read_text("secret.txt")')
    finally:
        secret.chmod(0o600)
    assert shown == 'Error(Denied("secret.txt"))'


READER = (
    "module r\n\nimport std.console exposing print\nimport std.file\n\n"
    "function main() returns Unit\n  uses Console, FileRead\ndo\n"
    '  print(show(File.read_text("r.tersa")))\nend\n'
)


@pytest.mark.parametrize(
    ("allow", "message"),
    [
        ("Bogus", "unknown effect `Bogus`"),
        ("console", "unknown effect `console`"),
        ("FileRead", "FileRead needs a scope: --allow FileRead=FOLDER"),
        ("FileRead=", "FileRead needs a scope: --allow FileRead=FOLDER"),
        ("FileWrite", "FileWrite needs a scope: --allow FileWrite=FOLDER"),
        ("Net", "Net needs a scope: --allow Net=HOST"),
        ("Console=x", "Console does not take a scope"),
    ],
)
@pytest.mark.parametrize("command", ["run", "test"])
def test_bad_grants_are_i9010_before_anything_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: str, allow: str, message: str
) -> None:
    source = tmp_path / "r.tersa"
    source.write_text(READER, encoding="utf-8")
    code = main([command, str(source), "--allow", "Console", "--allow", allow, "--json"])
    captured = capsys.readouterr()
    assert code == 4
    payload = _json_tail(captured.out)
    assert [(item["code"], item["message"]) for item in payload] == [("I9010", message)]


def test_file_read_needs_its_folder_and_then_reads(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "r.tersa"
    source.write_text(READER, encoding="utf-8")
    code = main(["run", str(source), "--allow", "Console", "--allow", f"FileRead={tmp_path}"])
    assert code == 0
    assert capsys.readouterr().out.startswith('Ok("module r')


def test_the_python_api_rejects_a_scoped_grant_without_a_scope() -> None:
    outcome = run_text("r.tersa", READER, grants={"Console": [], "FileRead": []})
    assert outcome.exit_code == 4
    assert [(d.code, d.message) for d in outcome.diagnostics] == [
        ("I9010", "FileRead needs a scope: --allow FileRead=FOLDER")
    ]


@pytest.mark.parametrize("allow", ["FileRead=.", "FileWrite=.", "Net=example.com", "Python"])
@pytest.mark.parametrize(
    "command", [["sandbox"], ["run", "--mode", "rl"], ["test", "--mode", "rl"]]
)
def test_rl_mode_refuses_file_net_and_python_grants(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: list[str], allow: str
) -> None:
    source = tmp_path / "r.tersa"
    source.write_text(READER, encoding="utf-8")
    code = main(
        [command[0], str(source), *command[1:], "--allow", "Console", "--allow", allow, "--json"]
    )
    captured = capsys.readouterr()
    assert code == 4
    effect = allow.split("=", 1)[0]
    assert [(item["code"], item["message"]) for item in _json_tail(captured.out)] == [
        ("I9017", f"RL mode cannot grant {effect}")
    ]
    assert "module r" not in captured.out


def test_run_sandboxed_refuses_a_file_read_grant(tmp_path: Path) -> None:
    from tersalang.sandbox import run_sandboxed

    outcome = run_sandboxed("r.tersa", READER, grants={"Console": [], "FileRead": [str(tmp_path)]})
    assert outcome.exit_code == 4
    assert [(d.code, d.message) for d in outcome.diagnostics] == [
        ("I9017", "RL mode cannot grant FileRead")
    ]
