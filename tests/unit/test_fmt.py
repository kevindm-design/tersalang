# SPDX-License-Identifier: Apache-2.0
"""Canonical formatter: idempotent, meaning-preserving, comment-preserving."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import fields, is_dataclass
from pathlib import Path

import pytest

from tersalang.ast import BinaryExpr, GroupExpr, Import, Module
from tersalang.cli import main
from tersalang.driver import check_text
from tersalang.fmt import (
    EXACT_FMT_SKIP,
    FMT_SKIP_NEAR_MISS,
    FormatError,
    _split_comment,
    fmt_skip_warnings,
    format_source,
    is_fmt_skip,
)
from tersalang.lexer import lex_text
from tersalang.parser import parse_module
from tersalang.source import Span, decode_source_bytes

ROOT = Path(__file__).resolve().parents[2]
PROGRAMS = sorted((ROOT / "conformance").rglob("*.tersa")) + sorted(
    (ROOT / "examples").rglob("*.tersa")
)


def meaning_shape(node: object, parent_op: str | None = None) -> object:
    """AST shape for a format round trip.

    Spans move when a space is removed. Imports are sorted. A group that the
    formatter inserts around `and` under `or` compares equal to the bare `and`.
    Other groups stay, so `(a + b) * c` does not compare equal to `a + b * c`.
    """
    if isinstance(node, Span):
        return None
    if isinstance(node, GroupExpr):
        inner = node.expr
        if parent_op == "or" and isinstance(inner, BinaryExpr) and inner.op == "and":
            return meaning_shape(inner, "or")
        return ("group", meaning_shape(inner, None))
    if isinstance(node, BinaryExpr):
        return (
            "bin",
            node.op,
            meaning_shape(node.left, node.op),
            meaning_shape(node.right, node.op),
        )
    if isinstance(node, Module):
        imports = tuple(sorted((meaning_shape(item) for item in node.imports), key=repr))
        decls = tuple(meaning_shape(item) for item in node.decls)
        return ("module", tuple(node.path), imports, decls)
    if isinstance(node, Import):
        exposing = None
        if node.exposing is not None:
            exposing = tuple(sorted(name for name, _span in node.exposing))
        return ("import", tuple(node.path), node.alias, exposing)
    if is_dataclass(node) and not isinstance(node, type):
        parts = tuple(
            (item.name, meaning_shape(getattr(node, item.name)))
            for item in fields(node)
            if item.name != "span"
        )
        return (type(node).__name__, parts)
    if isinstance(node, list):
        return tuple(meaning_shape(item) for item in node)
    if isinstance(node, tuple):
        return tuple(meaning_shape(item) for item in node if not isinstance(item, Span))
    return node


def _docs(node: object) -> list[object]:
    found: list[object] = []
    if is_dataclass(node) and not isinstance(node, type):
        for item in fields(node):
            value = getattr(node, item.name)
            if item.name == "doc":
                found.append(value)
            else:
                found.extend(_docs(value))
    elif isinstance(node, (list, tuple)):
        for item in node:
            found.extend(_docs(item))
    return found


def _comments(text: str) -> list[str]:
    found: list[str] = []
    for line in text.splitlines():
        _code, comment = _split_comment(line)
        if comment is not None:
            found.append(comment)
    return sorted(found)


def _parsed(filename: str, text: str) -> Module | None:
    source, tokens, diagnostics = lex_text(filename, text)
    module = parse_module(source, tokens, diagnostics)
    if module is None or any(item.severity == "error" for item in diagnostics):
        return None
    return module


def test_hello_is_already_canonical() -> None:
    text = (ROOT / "examples" / "hello.tersa").read_text(encoding="utf-8")
    assert format_source("hello.tersa", text) == text


def test_idempotent_and_do_on_its_own_line() -> None:
    source = "module m\nfunction main() returns Int\ndo\nreturn 1\nend\n"
    once = format_source("m.tersa", source)
    twice = format_source("m.tersa", once)
    assert once == twice
    assert "\ndo\n" in once
    assert "  return 1\n" in once


def test_lambda_do_is_indented_under_the_statement() -> None:
    source = """module m

function main() returns Int
do
  let double = function (v: Int) returns Int
  do
    v * 2
  end
  return double(1)
end
"""
    formatted = format_source("m.tersa", source)
    assert format_source("m.tersa", formatted) == formatted
    assert "  let double = function (v: Int) returns Int\n" in formatted
    assert "    do\n" in formatted
    assert "      v * 2\n" in formatted
    assert "    end\n" in formatted


def test_function_type_drops_the_space_and_lambda_keeps_it() -> None:
    source = """module m

function apply(f: function (Int) returns Int) returns Int
do
  return f(1)
end
"""
    formatted = format_source("m.tersa", source)
    assert "function apply(f: function(Int) returns Int) returns Int\n" in formatted
    assert format_source("m.tersa", formatted) == formatted


def test_and_under_or_gains_parentheses_once() -> None:
    source = """module m

function main() returns Bool
do
  return true and false or true
end
"""
    once = format_source("m.tersa", source)
    twice = format_source("m.tersa", once)
    assert "(true and false) or true" in once
    assert once == twice
    before = _parsed("m.tersa", source)
    after = _parsed("m.tersa", once)
    assert before is not None and after is not None
    assert meaning_shape(before) == meaning_shape(after)


@pytest.mark.parametrize(
    "expr",
    [
        "a - b * c",
        "a * b - c",
        "a - b - c",
        "a - b div c",
        "-a - b mod c",
        "a - -b * c",
        "not x == y",
        "not a < b and x",
        "not not x",
        "(-a) * b",
        "-(a * b)",
        "not (x and y)",
        "(not x) == y",
    ],
)
def test_fmt_adds_no_parentheses_beyond_w1103(expr: str) -> None:
    source = f"module m\n\nfunction f(a: Int, b: Int, c: Int, x: Bool, y: Bool) returns Unit\ndo\n  let r = {expr}\nend\n"
    formatted = format_source("m.tersa", source)
    assert formatted == source
    before = _parsed("m.tersa", source)
    assert before is not None
    assert meaning_shape(before) == meaning_shape(_parsed("m.tersa", formatted))


@pytest.mark.parametrize(
    "body",
    [
        "  return 1 end\n",
        "  if a then\n    return 1 else\n    return 2\n  end\nend\n",
        "  let x = 1\n  x  end\n",
    ],
)
def test_statement_and_end_on_one_line_is_a_syntax_error_not_a_crash(body: str) -> None:
    source = f"module m\n\nfunction f(a: Bool) returns Int\ndo\n{body}"
    try:
        format_source("m.tersa", source)
    except FormatError as exc:
        assert [item.code for item in exc.diagnostics][:1] == ["E1000"]
    else:
        raise AssertionError("expected a FormatError")


def test_imports_and_exposing_are_sorted() -> None:
    source = """module m

import b.widgets
import a.widgets exposing name, Value

function main() returns Int
do
  return 1
end
"""
    formatted = format_source("m.tersa", source)
    assert formatted.index("import a.widgets exposing Value, name") < formatted.index(
        "import b.widgets"
    )
    assert format_source("m.tersa", formatted) == formatted


def test_import_may_follow_a_declaration() -> None:
    text = """module import_order

function ready() returns Int
do
  return 1
end

import std.math

function main() returns Int
do
  return math.abs(ready())
end
"""
    outcome = check_text("import_order.tersa", text)
    assert outcome.exit_code == 0


def test_doc_and_trailing_comments_round_trip() -> None:
    source = """# spec: sample
# expect: check-ok
module comments_ok

## Adds one.
## Example: bump(1) == 2
function bump(n: Int) returns Int
do
  return n + 1
end

function main() returns Unit
do
  let _ = bump(1)  # trailing comment
  return
end
"""
    formatted = format_source("comments_ok.tersa", source)
    assert format_source("comments_ok.tersa", formatted) == formatted
    assert _comments(source) == _comments(formatted)
    before = _parsed("comments_ok.tersa", source)
    after = _parsed("comments_ok.tersa", formatted)
    assert before is not None and after is not None
    assert _docs(before) == _docs(after)
    assert "# expect: check-ok" in formatted.splitlines()[1]


def test_crlf_becomes_lf_unless_the_file_is_skipped() -> None:
    source = "module m\r\nfunction main() returns Int\r\ndo\r\n  return 1\r\nend\r\n"
    formatted = format_source("m.tersa", source)
    assert "\r" not in formatted
    assert formatted.endswith("\n")
    skipped = "# fmt: skip\r\n" + source
    assert format_source("m.tersa", skipped) == skipped


def test_crlf_fixture_is_byte_stable() -> None:
    path = ROOT / "conformance" / "lex" / "crlf_ok.tersa"
    raw = path.read_bytes()
    assert raw.startswith(b"# fmt: skip\r\n")
    assert b"\n" not in raw.replace(b"\r\n", b"")
    text = decode_source_bytes(raw)
    assert format_source(str(path), text) == text


def test_fmt_skip_keeps_the_warning_fixture() -> None:
    path = ROOT / "conformance" / "syntax" / "mixed_and_or.tersa"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# fmt: skip\n")
    assert format_source(str(path), text) == text
    assert "true and false or true" in text
    assert fmt_skip_warnings(str(path), text) == []


def test_marked_skip_fixtures_parse_and_stay_byte_stable() -> None:
    paths = [
        ROOT / "conformance" / "lex" / "crlf_ok.tersa",
        ROOT / "conformance" / "lex" / "nl_suppress_ok.tersa",
        ROOT / "conformance" / "syntax" / "mixed_and_or.tersa",
    ]
    for path in paths:
        text = decode_source_bytes(path.read_bytes())
        assert is_fmt_skip(text), path
        assert format_source(str(path), text) == text
        outcome = check_text(path.name, text)
        assert outcome.exit_code == 0, outcome.stderr
        assert not any(item.code == "W1104" for item in outcome.diagnostics)


def test_skipped_file_that_does_not_parse_exits_3(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "broken.tersa"
    original = "# fmt: skip\nmodule m\nfunction main() returns Unit do\n  return\nend\n"
    path.write_text(original, encoding="utf-8", newline="\n")
    try:
        format_source(str(path), original)
    except FormatError as exc:
        assert any(item.code == "E1000" for item in exc.diagnostics)
    else:
        raise AssertionError("expected FormatError")
    assert main(["fmt", str(path)]) == 3
    assert path.read_text(encoding="utf-8") == original
    err = capsys.readouterr().err
    assert "E1000" in err
    assert main(["fmt", "--check", str(path)]) == 3
    assert "E1000" in capsys.readouterr().err


def test_near_miss_is_formatted_and_warns(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    source = "#fmt:skip\nmodule m\nfunction main() returns Int\ndo\nreturn 1\nend\n"
    path = tmp_path / "m.tersa"
    path.write_text(source, encoding="utf-8", newline="\n")
    formatted = format_source(str(path), source)
    assert "#fmt:skip\n" in formatted
    assert "  return 1\n" in formatted
    assert format_source(str(path), formatted) == formatted
    assert not is_fmt_skip(source)
    notes = fmt_skip_warnings(str(path), source)
    assert [item.code for item in notes] == ["W1104"]
    assert notes[0].message == FMT_SKIP_NEAR_MISS
    assert EXACT_FMT_SKIP in notes[0].message
    assert main(["fmt", "--check", str(path)]) == 1
    err = capsys.readouterr().err
    assert "W1104" in err
    assert EXACT_FMT_SKIP in err
    assert "would reformat" in err
    assert main(["check", str(path)]) == 0
    checked = capsys.readouterr().err
    assert "W1104" in checked
    assert "warning[W1104]" in checked
    assert EXACT_FMT_SKIP in checked
    assert main(["check", "--parse-only", str(path)]) == 0
    assert "W1104" in capsys.readouterr().err


def test_fmt_stdin_warns_on_a_near_miss(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    text = "# FMT: skip\nmodule m\n\nfunction main() returns Unit\ndo\n  return\nend\n"
    monkeypatch.setattr(sys, "stdin", _input(text))
    assert main(["fmt", "--check"]) == 0
    err = capsys.readouterr().err
    assert "W1104" in err
    assert EXACT_FMT_SKIP in err
    assert "error: input is not formatted" not in err


def test_near_miss_spellings_and_non_markers() -> None:
    body = "module m\n\nfunction main() returns Unit\ndo\n  return\nend\n"
    near = [
        "#fmt:skip",
        "# FMT: skip",
        "# fmt:skip",
        "#  fmt: skip",
        "# fmt:  skip",
        "#fmt :skip",
        "#\tfmt:\tskip",
    ]
    for line in near:
        text = f"{line}\n{body}"
        notes = fmt_skip_warnings("m.tersa", text)
        assert [item.code for item in notes] == ["W1104"], line
        assert not is_fmt_skip(text), line
    silent = [
        "# fmt: skip",
        "  # fmt: skip  ",
        "# fmt: skip (reason)",
        "# format: skip",
        "return 1  # fmt: skip",
        "# fmt: skip please",
    ]
    for line in silent:
        text = f"{line}\n{body}"
        assert fmt_skip_warnings("m.tersa", text) == [], line
    padded = f"  # fmt: skip\n{body}"
    assert is_fmt_skip(padded)
    assert format_source("m.tersa", padded) == padded


def test_long_call_breaks_the_lambda_and_stays_stable() -> None:
    callee = "f" * 60
    source = f"""module m

function main() returns Int
do
  let n = {callee}(1, 2, function (x: Int) returns Int
  do
    x
  end)
  return n
end
"""
    once = format_source("m.tersa", source)
    twice = format_source("m.tersa", once)
    assert once == twice
    assert "end," in once
    assert f"  let n = {callee}(\n" in once


def test_unparseable_source_is_rejected() -> None:
    try:
        format_source("bad.tersa", "module m\nfunction main() returns Unit do\n  return\nend\n")
    except FormatError as exc:
        assert any(item.code == "E1000" for item in exc.diagnostics)
        return
    raise AssertionError("expected FormatError")


def test_fmt_stdin_and_check(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        sys, "stdin", _input("module m\nfunction main() returns Int\ndo\nreturn 1\nend\n")
    )
    assert main(["fmt"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("module m\n")
    assert "  return 1\n" in out

    monkeypatch.setattr(sys, "stdin", _input("module   m\n"))
    assert main(["fmt", "--check"]) == 1
    err = capsys.readouterr().err
    assert "error: input is not formatted" in err


def test_fmt_check_skips_a_directory_syntax_error(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    good = "module m\n\nfunction main() returns Int\ndo\n  return 1\nend\n"
    # newline="\n" keeps the fixture LF. The default text mode on Windows
    # would write CRLF, and the formatter would then report a change.
    (tmp_path / "good.tersa").write_text(good, encoding="utf-8", newline="\n")
    (tmp_path / "bad.tersa").write_text(
        "module bad\nfunction main() returns Unit do\n  return\nend\n",
        encoding="utf-8",
        newline="\n",
    )
    assert main(["fmt", "--check", str(tmp_path)]) == 3
    err = capsys.readouterr().err
    assert "E1000" in err
    assert "bad.tersa" in err
    assert main(["fmt", str(tmp_path / "bad.tersa")]) == 3


def test_fmt_check_reports_a_dirty_file(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "dirty.tersa"
    path.write_text("module m\nfunction main() returns Int\ndo\nreturn 1\nend\n", encoding="utf-8")
    assert main(["fmt", "--check", str(path)]) == 1
    err = capsys.readouterr().err
    assert "would reformat" in err


def test_corpus_preserves_meaning_comments_and_is_idempotent() -> None:
    for path in PROGRAMS:
        text = decode_source_bytes(path.read_bytes())
        if any(line.strip() == "# fmt: skip" for line in text.splitlines()):
            assert format_source(str(path), text) == text
            continue
        before = _parsed(str(path), text)
        if before is None:
            continue
        formatted = format_source(str(path), text)
        again = format_source(str(path), formatted)
        assert again == formatted, path
        after = _parsed(str(path), formatted)
        assert after is not None, path
        assert meaning_shape(before) == meaning_shape(after), path
        assert _docs(before) == _docs(after), path
        assert _comments(text) == _comments(formatted), path
        assert formatted == text, path


def test_check_fmt_rejects_a_broken_skip_and_keeps_unmarked_errors(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    script = ROOT / "scripts" / "check_fmt.py"
    loaded = importlib.util.spec_from_file_location("check_fmt_script", script)
    assert loaded is not None and loaded.loader is not None
    module = importlib.util.module_from_spec(loaded)
    loaded.loader.exec_module(module)
    (tmp_path / "conformance").mkdir()
    (tmp_path / "examples").mkdir()
    (tmp_path / "conformance" / "broken.tersa").write_text(
        "# fmt: skip\nmodule m\nfunction main() returns Unit do\n  return\nend\n",
        encoding="utf-8",
        newline="\n",
    )
    (tmp_path / "conformance" / "negative.tersa").write_text(
        "this is not tersa\n",
        encoding="utf-8",
        newline="\n",
    )
    (tmp_path / "examples" / "good.tersa").write_text(
        "module good\n\nfunction main() returns Int\ndo\n  return 1\nend\n",
        encoding="utf-8",
        newline="\n",
    )
    files, status = module.corpus_files(tmp_path)
    err = capsys.readouterr().err
    assert status == 3
    assert "E1000" in err
    assert any(name.endswith("good.tersa") for name in files)
    assert all("broken.tersa" not in name and "negative.tersa" not in name for name in files)


class _input:
    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> str:
        return self._text
