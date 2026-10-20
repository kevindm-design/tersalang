# SPDX-License-Identifier: Apache-2.0
"""Generated GBNF matches spec/tersa.gbnf and accepts the parseable corpus."""

from __future__ import annotations

from pathlib import Path

import pytest

from tersalang.driver import check_text
from tersalang.fmt import FormatError, format_source
from tersalang.gbnf import (
    COMMENT_CHARS,
    COMMENT_LINES,
    HEADER_LINES,
    GChoice,
    GLit,
    GNode,
    GRef,
    GRep,
    GSeq,
    _parse_gbnf,
    _Recognizer,
    cap_cases,
    gbnf_accepts,
    gbnf_failure,
    generate_gbnf,
    llama_gbnf_accepts,
    reserved_words,
)
from tersalang.lexer import KEYWORDS, lex_text
from tersalang.parser import parse_module
from tersalang.source import decode_source_bytes

ROOT = Path(__file__).resolve().parents[2]
PROGRAMS = sorted((ROOT / "conformance").rglob("*.tersa")) + sorted(
    (ROOT / "examples").rglob("*.tersa")
)


def _rules(text: str) -> str:
    lines = text.splitlines()
    start = next(index for index, line in enumerate(lines) if line.startswith("root "))
    return "\n".join(lines[start:])


def _accepted_by_parser(path: Path, text: str) -> bool:
    source, tokens, diagnostics = lex_text(str(path), text)
    module = parse_module(source, tokens, diagnostics)
    return module is not None and not any(item.severity == "error" for item in diagnostics)


def test_committed_gbnf_matches_a_fresh_generation() -> None:
    committed = (ROOT / "spec" / "tersa.gbnf").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert generate_gbnf("full").replace("\r\n", "\n") == committed


def test_decoding_profile_is_a_stricter_separator() -> None:
    full = generate_gbnf("full")
    decoding = generate_gbnf("decoding")
    assert "Profile: full" in full
    assert "Profile: decoding" in decoding
    assert "(!" not in full
    assert "(!" not in decoding
    assert _rules(full) != _rules(decoding)
    assert "break ::=" in decoding


def test_gbnf_accepts_every_parseable_program() -> None:
    grammar = (ROOT / "spec" / "tersa.gbnf").read_text(encoding="utf-8")
    checked = 0
    for path in PROGRAMS:
        text = decode_source_bytes(path.read_bytes())
        if not _accepted_by_parser(path, text):
            continue
        checked += 1
        assert llama_gbnf_accepts(grammar, text), f"{path}: {gbnf_failure(grammar, text)}"
    assert checked > 100


_LITERALS = (
    "0",
    "1",
    "1_000",
    "0x0",
    "0xF_f",
    "0b0",
    "0b1_0",
    "1.0",
    "1.0e10",
    "1.0e+2",
    "1.0e-2",
    "1e10",
    "1e+2",
    "1e-2",
    "1_0.5",
    '"hi"',
    '"a\\"b"',
    '"\\\\"',
    '"\\n"',
    '"\\t"',
    '"\\r"',
    '"\\{"',
    '"\\}"',
    '"\\u{1}"',
    '"\\u{1F}"',
    "true",
    "false",
)


def test_gbnf_accepts_every_lexer_literal() -> None:
    grammar = generate_gbnf("full")
    for literal in _LITERALS:
        program = (
            f"module m\n\nfunction main() returns Unit\ndo\n  let _ = {literal}\n  return\nend\n"
        )
        _source, _tokens, diagnostics = lex_text("m.tersa", program)
        errors = [item for item in diagnostics if item.severity == "error"]
        assert not errors, (literal, [(item.code, item.message) for item in errors])
        assert llama_gbnf_accepts(grammar, program), f"{literal}: {gbnf_failure(grammar, program)}"


def test_decoding_profile_accepts_formatter_output() -> None:
    grammar = generate_gbnf("decoding")
    checked = 0
    skipped = 0
    for path in PROGRAMS:
        text = decode_source_bytes(path.read_bytes())
        if any(line.strip() == "# fmt: skip" for line in text.splitlines()):
            skipped += 1
            continue
        try:
            formatted = format_source(str(path), text)
        except FormatError:
            continue
        checked += 1
        assert llama_gbnf_accepts(grammar, formatted), f"{path}: {gbnf_failure(grammar, formatted)}"
    assert checked > 100
    assert skipped == 3


def test_decoding_profile_rejects_a_same_line_do() -> None:
    grammar = generate_gbnf("decoding")
    text = "module m\n\nfunction main() returns Unit do\n  return\nend\n"
    assert not gbnf_accepts(grammar, text)


@pytest.mark.parametrize("profile", ["full", "decoding"])
def test_both_profiles_reject_a_same_line_do_like_the_parser(profile: str) -> None:
    path = ROOT / "conformance" / "syntax" / "same_line_function.tersa"
    text = path.read_text(encoding="utf-8")
    source, tokens, diagnostics = lex_text(str(path), text)
    parse_module(source, tokens, diagnostics)
    assert any(item.code == "E1000" for item in diagnostics)
    assert not gbnf_accepts(generate_gbnf(profile), text)


def test_reserved_words_are_the_lexer_keywords() -> None:
    lark = (ROOT / "spec" / "tersa.lark").read_text(encoding="utf-8")
    lower = next(line for line in lark.splitlines() if line.startswith("LOWER:"))
    assert set(reserved_words(lower)) == set(KEYWORDS)


def _named(name: str) -> str:
    return f"module m\n\nfunction main() returns Int\ndo\n  let {name} = 1\n  return {name}\nend\n"


@pytest.mark.parametrize("profile", ["full", "decoding"])
def test_no_keyword_is_a_name_and_every_other_word_is(profile: str) -> None:
    grammar = _parse_gbnf(generate_gbnf(profile))
    recognizer = _Recognizer(grammar)
    lower = grammar["lower"]
    for keyword in sorted(KEYWORDS):
        assert not recognizer.accepts(_named(keyword)), keyword
        candidates = {keyword + "x", keyword + "_x", keyword + "1", keyword[:-1], "x" + keyword}
        for name in sorted(candidates - set(KEYWORDS) - {""}):
            recognizer.text = name
            recognizer.memo.clear()
            assert len(name) in recognizer._parse(lower, 0), name
            assert recognizer.accepts(_named(name)), name


@pytest.mark.parametrize("profile", ["full", "decoding"])
def test_end_closes_a_function_body(profile: str) -> None:
    # Before keywords were reserved, `end` was also a name, so a body never
    # had to close and text after it was more statements.
    grammar = generate_gbnf(profile)
    head = "module m\n\nfunction main() returns Int\ndo\n  return 1\nend\n"
    assert gbnf_accepts(grammar, head)
    assert not gbnf_accepts(grammar, head + "  end\nend\n")
    assert not gbnf_accepts(grammar, head.replace("\nend\n", "\n  e nd\nend\n"))


def test_full_profile_accepts_a_missing_final_newline_and_only_there() -> None:
    grammar = generate_gbnf("full")
    head = "module m\n\nfunction main() returns Int\ndo\n  return 1\nend"
    assert gbnf_accepts(grammar, head)
    assert gbnf_accepts(grammar, head + "  # done")
    assert gbnf_accepts(grammar, "module m")
    assert gbnf_accepts(grammar, "module m\n\nlet x: Int = 1")
    assert not gbnf_accepts(grammar, "module m\n\nlet x: Int = 1 let y: Int = 2")
    assert not gbnf_accepts(generate_gbnf("decoding"), head)


def test_full_profile_comments_run_to_the_line_break() -> None:
    # The comment used to be allowed to stop mid-line, so its last words were
    # read as code: `# Test the function` ended with the keyword `function`.
    grammar = generate_gbnf("full")
    text = "module m\n\n# see function f() returns Int\ndo\n  return 1\nend\n"
    assert check_text("m.tersa", text).exit_code == 3
    assert not gbnf_accepts(grammar, text)
    assert gbnf_accepts(grammar, "module m\n\n# see function f() returns Int\n")
    assert gbnf_accepts(grammar, "module m\n# last line, no newline")


def _commented(lines: int, width: int = 10) -> str:
    comment = "".join(f"  # {'c' * (width - 2)}\n" for _ in range(lines))
    return f"module m\n\nfunction main() returns Int\ndo\n{comment}  return 1\nend\n"


def _lines_between(lines: str) -> str:
    return f"module m\n\nlet x: Int = 1\n{lines}let y: Int = 2\n"


def test_caps_are_a_long_header_and_short_runs_after_code() -> None:
    assert COMMENT_CHARS + 1 == 500
    assert HEADER_LINES == 100
    assert COMMENT_LINES == 30


@pytest.mark.parametrize("profile", ["full", "decoding"])
@pytest.mark.parametrize("case", cap_cases(), ids=lambda case: case[0])
def test_both_profiles_cap_comments_at_the_same_lines(
    profile: str, case: tuple[str, str, bool]
) -> None:
    _label, text, accepted = case
    assert format_source("m.tersa", text) == text
    assert check_text("m.tersa", text).exit_code == 0
    assert gbnf_accepts(generate_gbnf(profile), text) is accepted


@pytest.mark.parametrize("profile", ["full", "decoding"])
def test_the_header_cap_ends_at_the_first_token(profile: str) -> None:
    grammar = generate_gbnf(profile)
    after_module = "module m\n\n" + "# c\n" * (COMMENT_LINES + 1) + "let x: Int = 1\n"
    assert not gbnf_accepts(grammar, after_module)
    assert gbnf_accepts(grammar, "# c\n" * (COMMENT_LINES + 1) + "module m\n\nlet x: Int = 1\n")
    assert gbnf_accepts(grammar, _commented(1, width=COMMENT_CHARS + 1))
    assert not gbnf_accepts(grammar, _commented(1, width=COMMENT_CHARS + 2))


def test_full_profile_caps_comments_inside_brackets() -> None:
    grammar = generate_gbnf("full")

    def call(lines: int) -> str:
        comments = "    # c\n" * lines
        return f"{FN}  return max(1,\n{comments}    2)\nend\n"

    assert _parses(call(COMMENT_LINES + 1))
    assert gbnf_accepts(grammar, call(COMMENT_LINES))
    assert not gbnf_accepts(grammar, call(COMMENT_LINES + 1))


def test_full_profile_does_not_cap_blank_lines() -> None:
    grammar = generate_gbnf("full")
    assert gbnf_accepts(grammar, "\n" * 300 + _lines_between("\n" * 300 + "# c\n" + "\n" * 300))


def test_decoding_keeps_the_formatters_blank_lines() -> None:
    grammar = generate_gbnf("decoding")
    assert gbnf_accepts(grammar, _lines_between(""))
    assert gbnf_accepts(grammar, _lines_between("\n"))
    assert not gbnf_accepts(grammar, _lines_between("\n\n"))
    assert gbnf_accepts(grammar, _lines_between("\n# c\n\n# d\n\n"))
    assert not gbnf_accepts(grammar, _lines_between("# c\n\n\n# d\n"))
    assert not gbnf_accepts(grammar, "\n" + _lines_between(""))
    banner = "# b\n" * HEADER_LINES + "module m\n"
    assert gbnf_accepts(grammar, banner)
    assert not gbnf_accepts(grammar, "# b\n" + banner)
    assert gbnf_accepts(grammar, "# b\n\n# c\n\nmodule m\n")
    assert not gbnf_accepts(grammar, "# b\n\n\nmodule m\n")


def test_decoding_accepts_a_formatted_license_header_and_long_comments() -> None:
    header = "".join(
        f"# Line {index} of the license text, as long as a real one.\n" for index in range(60)
    )
    wide = "# " + "w" * 300
    text = (
        f"{header}\n\n\nmodule m\n\n\n{wide}\nfunction main() returns Int\ndo\n\n"
        f"  {wide}\n  return 1  {wide}\n\nend\n"
    )
    formatted = format_source("m.tersa", text)
    assert formatted != text
    assert check_text("m.tersa", formatted).exit_code == 0
    for profile in ("full", "decoding"):
        assert gbnf_accepts(generate_gbnf(profile), formatted), profile


LEXER_NAMES = {
    "a": True,
    "a_b": True,
    "a1_2b": True,
    "a" * 64: True,
    "end_x": True,
    "a__b": False,
    "a_": False,
    "end_": False,
    "a" * 65: False,
    "e" + "x" * 64: False,
    "a_" + "b" * 62: True,
    "a_" + "b" * 63: False,
    "B" * 64: True,
    "B" * 65: False,
}


@pytest.mark.parametrize("profile", ["full", "decoding"])
def test_names_follow_e0010_and_e0012(profile: str) -> None:
    grammar = generate_gbnf(profile)
    for name, good in LEXER_NAMES.items():
        if name[0].isupper():
            text = f"module m\n\nrecord {name}\n  x: Int\nend\n"
        else:
            text = _named(name)
        codes = {
            item.code
            for item in check_text("m.tersa", text).diagnostics
            if item.severity == "error"
        }
        assert (not codes & {"E0010", "E0012"}) is good, (name, codes)
        assert gbnf_accepts(grammar, text) is good, name


FN = "module m\n\nfunction f(x: Bool) returns Int\ndo\n"
APPLY = "module m\n\nfunction apply(f: function(Int) returns Int, x: Int) returns Int\ndo\n  return f(x)\nend\n\n"

# The lexer drops a newline inside brackets and after a continuation token,
# and splits `x and(y)`. The grammar's gaps follow those rules.
LAYOUT_ACCEPTS = {
    "line break inside call parentheses": FN + "  return apply(f,\n    1)\nend\n",
    "line break after an operator": FN + "  return 1 +\n    2\nend\n",
    "comment after a continuation": FN + "  return 1 + # one\n    2\nend\n",
    "statement on the then line": FN + "  if x then return 1\n  end\n  return 0\nend\n",
    "empty block on the then line": FN + "  if x then end\n  return 0\nend\n",
    "unindented arms after a block": FN
    + "if x then\nreturn 1\nelseif not x then\nreturn 3\nelse\nreturn 2\nend\nend\n",
    "word after an opening parenthesis": FN
    + "  return 1\nend\n\nfunction g() returns Bool\ndo\n  return x and(false)\nend\n",
    "lambda body inside a call": APPLY
    + "function main() returns Int\ndo\n  return apply(function(x: Int) returns Int\n    do\n      x + 1\n    end, 1)\nend\n",
    "blank line inside a record": "module m\n\nrecord P\n  x: Int\n\n  y: Int\nend\n",
}

# Both grammars want a space here; the lexer splits the tokens anyway.
LAYOUT_STRICTER_THAN_THE_PARSER = {
    "word right after a closing parenthesis": FN
    + "  return 1\nend\n\nfunction g() returns Bool\ndo\n  return (true)and false\nend\n",
    "word right after a number": FN + "  return 7mod 2\nend\n",
}


def _parses(text: str) -> bool:
    return not any(
        item.code.startswith(("E0", "E1")) for item in check_text("m.tersa", text).diagnostics
    )


@pytest.mark.parametrize("name", sorted(LAYOUT_ACCEPTS))
def test_full_profile_follows_the_lexers_line_rules(name: str) -> None:
    text = LAYOUT_ACCEPTS[name]
    assert _parses(text)
    assert gbnf_accepts(generate_gbnf("full"), text)


@pytest.mark.parametrize("name", sorted(LAYOUT_STRICTER_THAN_THE_PARSER))
def test_grammars_want_a_space_before_a_word_after_a_mixed_ending(name: str) -> None:
    text = LAYOUT_STRICTER_THAN_THE_PARSER[name]
    assert _parses(text)
    for profile in ("full", "decoding"):
        assert not gbnf_accepts(generate_gbnf(profile), text), profile
        assert gbnf_accepts(
            generate_gbnf(profile), text.replace(")and", ") and").replace("7mod", "7 mod")
        )


def test_generated_line_break_between_operands_is_rejected() -> None:
    # A model wrote this under an older grammar: a gap could break the line
    # anywhere, so `*c` continued the expression on the line before.
    text = FN + "  let b = 1\n  let c = b\n  let d = c *b\n  *c + 1\n  return 0\nend\n"
    assert not _parses(text)
    for profile in ("full", "decoding"):
        assert not gbnf_accepts(generate_gbnf(profile), text), profile


def test_bounded_repetition_round_trips() -> None:
    grammar = _parse_gbnf('root ::= "a"{0,2} "b"\n')
    assert grammar["root"] == GSeq((GRep(GLit("a"), "{0,2}"), GLit("b")))
    text = 'root ::= "a"{1,2} "b"\n'
    for source, expected in (("b", False), ("ab", True), ("aab", True), ("aaab", False)):
        assert gbnf_accepts(text, source) is expected, source


TOKEN_RULES = {"lower", "upper", "int", "float", "text"}


def _sequences(node: GNode) -> list[tuple[GNode, ...]]:
    if isinstance(node, GSeq):
        found = [node.items]
        for item in node.items:
            found.extend(_sequences(item))
        return found
    if isinstance(node, GChoice):
        return [seq for option in node.options for seq in _sequences(option)]
    if isinstance(node, GRep):
        return _sequences(node.item)
    return []


@pytest.mark.parametrize("profile", ["full", "decoding"])
def test_every_gap_belongs_to_the_token_after_it(profile: str) -> None:
    """llama.cpp keeps a stack per reading. Two gaps that could share one
    space, or a gap in front of a rule, multiply those stacks."""
    rules = _parse_gbnf(generate_gbnf(profile))
    gaps = {GRef(name) for name in ("gap", "gap1", "sgap", "sgap1")}
    separators = {
        "root",
        "blank",
        "break",
        "nl",
        "banner",
        "comment-line",
        "trail",
        "hash-rest",
        "indent",
    }
    for name, body in rules.items():
        if name in separators or GRef(name) in gaps:
            continue
        for items in _sequences(body):
            for index, item in enumerate(items):
                if item not in gaps:
                    continue
                assert index + 1 < len(items), f"{name}: gap at the end of a sequence"
                after = items[index + 1]
                assert isinstance(after, GLit) or (
                    isinstance(after, GRef) and after.name in TOKEN_RULES
                ), f"{name}: gap before {after}"


def test_precedence_rules_are_left_factored() -> None:
    lines = set(generate_gbnf("full").splitlines())
    for line in (
        'or-expr ::= and-expr ( sgap1 "or" and-expr-wc )*',
        'and-expr ::= not-expr ( sgap1 "and" not-expr-wc )*',
        "comparison ::= additive ( comp-op additive-c )?",
        "additive ::= multiplicative ( add-op multiplicative-c )*",
        'multiplicative ::= prefix ( ( sgap "*" | sgap "/" ) prefix-c | ( sgap1 "div" | sgap1 "mod" ) prefix-wc )*',
        "postfix ::= primary postfix-op*",
        "block-some-n ::= statement nl ( statement nl )*",
    ):
        assert line in lines, line
