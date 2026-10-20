# SPDX-License-Identifier: Apache-2.0
"""Pins the behavior behind five points where the spec wording was clarified."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from pathlib import Path

import pytest

from tersalang.ast import BinaryExpr, GroupExpr, Module
from tersalang.cli import episode_exit, main
from tersalang.driver import check_text, run_tests, run_text
from tersalang.fmt import EXACT_FMT_SKIP, format_source
from tersalang.gbnf import gbnf_accepts, generate_gbnf
from tersalang.lexer import lex_text
from tersalang.parser import parse_module
from tersalang.source import Span, decode_source_bytes

ROOT = Path(__file__).resolve().parents[2]
PROGRAMS = sorted((ROOT / "conformance").rglob("*.tersa")) + sorted(
    (ROOT / "examples").rglob("*.tersa")
)


def _parse(filename: str, text: str) -> Module | None:
    source, tokens, diagnostics = lex_text(filename, text)
    module = parse_module(source, tokens, diagnostics)
    if module is None or any(item.severity == "error" for item in diagnostics):
        return None
    return module


def strict_shape(node: object) -> object:
    """Every AST field except spans. Groups are kept, so `(a)` != `a`."""
    if isinstance(node, Span):
        return None
    if is_dataclass(node) and not isinstance(node, type):
        return (
            type(node).__name__,
            tuple(
                (f.name, strict_shape(getattr(node, f.name)))
                for f in fields(node)
                if f.name != "span"
            ),
        )
    if isinstance(node, (list, tuple)):
        return tuple(strict_shape(item) for item in node if not isinstance(item, Span))
    return node


def _groups_inserted(before: object, after: object) -> object:
    """Strip groups from `after` that wrap an `and` directly under an `or`
    and are absent in `before`; everything else must match exactly."""
    if isinstance(after, GroupExpr) and not isinstance(before, GroupExpr):
        inner = after.expr
        if isinstance(inner, BinaryExpr) and inner.op == "and":
            return _groups_inserted(before, inner)
    if is_dataclass(after) and not isinstance(after, type) and type(before) is type(after):
        values = {
            f.name: _groups_inserted(getattr(before, f.name), getattr(after, f.name))
            for f in fields(after)
        }
        return type(after)(**values)
    if isinstance(after, list) and isinstance(before, list) and len(before) == len(after):
        return [_groups_inserted(b, a) for b, a in zip(before, after, strict=True)]
    return after


def _sorted_imports(module: Module) -> Module:
    imports = sorted(module.imports, key=lambda item: (item.path, item.alias or ""))
    return Module(module.span, module.path, imports, module.decls)


# --- Issue 2: the formatter and the AST -----------------------------------------------


def test_parentheses_are_ast_nodes() -> None:
    text = "module m\n\nfunction main() returns Int\ndo\n  return (1)\nend\n"
    module = _parse("m.tersa", text)
    assert module is not None
    assert "GroupExpr" in repr(strict_shape(module))


def test_formatter_keeps_every_written_parenthesis() -> None:
    body = [
        "  let a = ((1))",
        "  let b = (1 + 2) * 3",
        "  let c = (1 + 2)",
        "  let d = 1 + (2 * 3)",
        "  let e = (true and false) or true",
        "  return a + b + c + d",
    ]
    text = "module m\n\nfunction main() returns Int\ndo\n" + "\n".join(body) + "\nend\n"
    assert format_source("m.tersa", text) == text


def test_formatter_inserts_only_the_and_under_or_group() -> None:
    text = "module m\n\nfunction main() returns Bool\ndo\n  return true or false and true\nend\n"
    out = format_source("m.tersa", text)
    assert "true or (false and true)" in out
    before, after = _parse("m.tersa", text), _parse("m.tersa", out)
    assert before is not None and after is not None
    assert strict_shape(before) != strict_shape(after)
    assert strict_shape(before) == strict_shape(_groups_inserted(before, after))


def _without_skip_marker(text: str) -> str:
    return "".join(
        line for line in text.splitlines(keepends=True) if line.strip() != EXACT_FMT_SKIP
    )


PARSEABLE = [
    path
    for path in PROGRAMS
    if _parse(str(path), _without_skip_marker(decode_source_bytes(path.read_bytes()))) is not None
]


def test_ast_preservation_covers_the_corpus() -> None:
    assert len(PARSEABLE) >= 100
    assert any("examples" in path.parts for path in PARSEABLE)


@pytest.mark.parametrize("path", PARSEABLE, ids=lambda p: str(p.relative_to(ROOT)))
def test_parse_fmt_parse_preserves_the_ast(path: Path) -> None:
    """parse -> fmt -> parse over every example and corpus file.

    A `# fmt: skip` file has its marker lines removed first so the formatter
    actually rewrites it. The only allowed AST changes are sorted imports and
    a group inserted around `and` under `or`.
    """
    text = _without_skip_marker(decode_source_bytes(path.read_bytes()))
    before = _parse(str(path), text)
    assert before is not None
    formatted = format_source(str(path), text)
    after = _parse(str(path), formatted)
    assert after is not None
    assert format_source(str(path), formatted) == formatted
    normalized = _groups_inserted(_sorted_imports(before), _sorted_imports(after))
    assert strict_shape(_sorted_imports(before)) == strict_shape(normalized)


# --- Issue 3: keyword used as a name --------------------------------------------------


KEYWORD_AS_NAME = {
    "let": (
        "function main() returns Unit\ndo\n  let do = 1\n  return\nend\n",
        "do",
        "expected a lower name",
    ),
    "var": (
        "function main() returns Unit\ndo\n  var result = 1\n  return\nend\n",
        "result",
        "expected a lower name",
    ),
    "function": (
        "function end() returns Int\ndo\n  return 1\nend\n",
        "end",
        "expected a function name",
    ),
    "parameter": (
        "function f(match: Int) returns Int\ndo\n  return 1\nend\n",
        "match",
        "expected a parameter name",
    ),
    "field": ("record P\n  then: Int\nend\n", "then", "expected a field name"),
}


@pytest.mark.parametrize("case", sorted(KEYWORD_AS_NAME))
def test_keyword_as_name_is_one_parser_e1000(case: str) -> None:
    body, keyword, prefix = KEYWORD_AS_NAME[case]
    text = "module m\n\n" + body
    _source, _tokens, lexed = lex_text("m.tersa", text)
    assert lexed == [], "the lexer accepts a keyword token; it does not reject it"
    outcome = check_text("m.tersa", text)
    assert outcome.exit_code == 3
    assert [item.code for item in outcome.diagnostics] == ["E1000"]
    message = outcome.diagnostics[0].message
    assert message.startswith(prefix)
    assert f"found the keyword `{keyword}`" in message
    assert "reserved" in message
    for profile in ("full", "decoding"):
        assert not gbnf_accepts(generate_gbnf(profile), text), profile


def test_keyword_module_name_reports_the_keyword() -> None:
    outcome = check_text("m.tersa", "module if\n")
    assert [item.code for item in outcome.diagnostics] == ["E1000"]
    assert "found the keyword `if`" in outcome.diagnostics[0].message


# --- Issue 4: what the decoding profile restricts ------------------------------------

HEAD = "module m\n\nfunction main() returns Int\ndo\n"

# The parser rejects these, and since both profiles require `nl`, reserve
# keywords, and follow the lexer's layout rules, so does each grammar.
BOTH_PROFILES_REJECT = {
    "do on the header line": "module m\n\nfunction main() returns Int do\n  return 1\nend\n",
    "uses on the header line": "module m\n\nfunction main() returns Unit uses Console\ndo\n  return\nend\n",
    "two statements on a line": HEAD + "  let x = 1 return x\nend\n",
    "statement and end on a line": HEAD + "  return 1 end\n",
    "keyword as a name": HEAD + "  let type = 1\n  return type\nend\n",
    "keyword run into a name": "module m\n\nfunctionmain() returns Int\ndo\n  return 1\nend\n",
    "operator run into its operand": HEAD + "  let b = true\n  return b andb\nend\n",
    "line break before an operator": HEAD + "  return 1\n    + 2\nend\n",
    "line break inside a let": HEAD + "  let x\n    = 1\n  return x\nend\n",
}

DECODING_REJECTS = {
    "CRLF": (HEAD + "  return 1\nend\n").replace("\n", "\r\n"),
    "two spaces between tokens": HEAD + "  return  1\nend\n",
    "trailing comment after one space": HEAD + "  return 1 # note\nend\n",
    "trailing whitespace": HEAD + "  return 1 \nend\n",
    "no final newline": HEAD + "  return 1\nend",
    "several blank lines": "module m\n\n\n\nfunction main() returns Int\ndo\n  return 1\nend\n",
    "blank line opening the file": "\n" + HEAD + "  return 1\nend\n",
}

# Not canonical, yet the decoding profile accepts them. `tersa fmt --check` is the gate.
DECODING_ACCEPTS_NON_CANONICAL = {
    "no spaces around an operator": HEAD + "  return 1+2\nend\n",
    "spaces inside parentheses": HEAD + "  return abs( 1 )\nend\n",
    "no space after a comma": HEAD + "  return max(1,2)\nend\n",
    "space before call parentheses": HEAD + "  return abs (1)\nend\n",
    "line break after `=`": HEAD + "  let x =\n    1\n  return x\nend\n",
    "line break after `+`": HEAD + "  return 1 +\n    2\nend\n",
    "wrong indentation depth": HEAD + "      return 1\nend\n",
    "no indentation": HEAD + "return 1\nend\n",
    "odd indentation": HEAD + "   return 1\nend\n",
    "no blank line between declarations": "module m\nfunction main() returns Int\ndo\n  return 1\nend\n",
    "blank line after do": HEAD + "\n  return 1\nend\n",
    "blank line before end": HEAD + "  return 1\n\nend\n",
    "unsorted imports": "module m\n\nimport std.text\nimport std.math\n\nfunction main() returns Int\ndo\n  return 1\nend\n",
    "and under or without parentheses": "module m\n\nfunction main() returns Bool\ndo\n  return true and false or true\nend\n",
}


@pytest.mark.parametrize("name", sorted(BOTH_PROFILES_REJECT))
def test_both_profiles_reject_what_the_parser_rejects(name: str) -> None:
    text = BOTH_PROFILES_REJECT[name]
    assert check_text("m.tersa", text).exit_code == 3
    for profile in ("full", "decoding"):
        assert not gbnf_accepts(generate_gbnf(profile), text), profile


@pytest.mark.parametrize("name", sorted(DECODING_REJECTS))
def test_decoding_rejects_what_full_accepts(name: str) -> None:
    text = DECODING_REJECTS[name]
    assert gbnf_accepts(generate_gbnf("full"), text)
    assert not gbnf_accepts(generate_gbnf("decoding"), text)


@pytest.mark.parametrize("name", sorted(DECODING_ACCEPTS_NON_CANONICAL))
def test_decoding_accepts_layouts_the_formatter_would_change(name: str) -> None:
    text = DECODING_ACCEPTS_NON_CANONICAL[name]
    assert gbnf_accepts(generate_gbnf("decoding"), text)
    try:
        canonical = format_source("m.tersa", text) == text
    except Exception:
        canonical = False
    assert not canonical


# --- Issue 5: W1104 from fmt and check; run, sandbox, and test only beside errors ----

NEAR_MISS_BROKEN = "#fmt:skip\nmodule m\n\nfunction main() returns Int\ndo\n  return nope\nend\n"
NEAR_MISS_OK = "#fmt:skip\nmodule m\n\nfunction main() returns Unit\ndo\n  return\nend\n"


@pytest.mark.parametrize(
    ("text", "shown"), [(NEAR_MISS_BROKEN, True), (NEAR_MISS_OK, False)], ids=["errors", "clean"]
)
def test_run_sandbox_and_test_emit_w1104_only_beside_errors(text: str, shown: bool) -> None:
    for outcome in (
        run_text("m.tersa", text),
        run_text("m.tersa", text, mode="rl"),
        run_tests("m.tersa", text),
    ):
        assert ("W1104" in [item.code for item in outcome.diagnostics]) is shown
        assert ("W1104" in outcome.stderr) is shown


def test_check_still_emits_w1104_with_errors_and_without() -> None:
    broken = check_text("m.tersa", NEAR_MISS_BROKEN)
    assert broken.exit_code == 3
    assert [item.code for item in broken.diagnostics] == ["E2000", "W1104"]
    clean = check_text("m.tersa", NEAR_MISS_OK)
    assert clean.exit_code == 0
    assert [item.code for item in clean.diagnostics] == ["W1104"]


def test_cli_w1104_per_subcommand(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "m.tersa"
    path.write_text(NEAR_MISS_BROKEN, encoding="utf-8", newline="\n")
    for argv, code, warns in (
        (["run", str(path)], 3, True),
        (["sandbox", str(path)], 3, True),
        (["test", str(path)], 3, True),
        (["check", str(path)], 3, True),
        (["check", "--parse-only", str(path)], 0, True),
    ):
        assert main(argv) == code, argv
        assert ("W1104" in capsys.readouterr().err) is warns, argv


# --- Issue 1: scored resource traps versus infrastructure errors -----------------------


@pytest.mark.parametrize("code", ["T6206", "T6207", "T6208"])
def test_resource_traps_exit_2(code: str) -> None:
    body = {"infrastructure_error": None, "reward": 0.0, "diagnostics": [{"code": code}]}
    assert episode_exit(body) == 2


@pytest.mark.parametrize("code", ["I9010", "I9013", "I9014", "I9024"])
def test_infrastructure_codes_exit_4(code: str) -> None:
    body = {"infrastructure_error": {"code": code, "message": "x"}, "reward": None}
    assert episode_exit(body) == 4


def test_harness_doc_headings_split_traps_from_infrastructure() -> None:
    text = (ROOT / "docs" / "harness.md").read_text(encoding="utf-8")
    traps = text.split("## Scored resource traps", 1)[1].split("\n## ", 1)[0]
    infra = text.split("## Infrastructure errors", 1)[1].split("\n## ", 1)[0]
    for code in ("T6206", "T6207", "T6208"):
        assert f"`{code}`" in traps
    for code in ("I9010", "I9013", "I9024"):
        assert f"`{code}`" in infra
    assert "reward 0" in traps and "exit 2" in traps
    assert "reward null" in infra and "exit 4" in infra
