# SPDX-License-Identifier: Apache-2.0
"""Property tests: generated programs against a Python model of the spec.

Programs are built as a small AST, rendered with random layout (spacing,
redundant parentheses), and evaluated by `_Model`, which follows the
Language Reference: floored `div`/`mod` (§5.2), `T6002` on a zero divisor,
`T6001` on `Int64` overflow (§5.2a; `Int64.min mod -1` is 0), the `Int` size cap `T6204` (§11.4),
short-circuit `and`/`or`, and the precedence table (§4.1).
"""

from __future__ import annotations

import importlib.util
import os
import random
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tersalang.driver import check_text, run_tests, run_text
from tersalang.fmt import FormatError, format_source
from tersalang.gbnf import gbnf_accepts, generate_gbnf
from tersalang.lexer import lex_text
from tersalang.limits import LimitConfig
from tersalang.parser import parse_module

ROOT = Path(__file__).resolve().parents[2]
INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1
# TERSA_FUZZ_SCALE=20 runs twenty times the examples, for a local soak.
SCALE = int(os.environ.get("TERSA_FUZZ_SCALE", "1"))
SETTINGS = settings(
    max_examples=60 * SCALE,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)


@cache
def _meaning_shape():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(
        "fmt_helpers", ROOT / "tests" / "unit" / "test_fmt.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.meaning_shape


@cache
def _grammar(profile: str) -> str:
    return generate_gbnf(profile)


def _ast(text: str) -> object:
    source, tokens, diagnostics = lex_text("p.tersa", text)
    module = parse_module(source, tokens, diagnostics)
    assert module is not None, [d.code for d in diagnostics]
    return _meaning_shape()(module)


class Trap(Exception):
    def __init__(self, code: str) -> None:
        self.code = code


# --- expressions -----------------------------------------------------------------

Expr = tuple  # ("lit", n) ("var", name) ("neg", e) ("bin", op, l, r) ("call", f, args)
#             ("cmp", op, l, r) ("not", e) ("and", l, r) ("or", l, r)

LEVEL = {"+": 5, "-": 5, "*": 4, "div": 4, "mod": 4}
CMP_OPS = ("==", "!=", "<", "<=", ">", ">=")


def _level(expr: Expr) -> int:
    kind = expr[0]
    if kind in ("lit", "var", "call"):
        return 1
    if kind == "neg":
        return 3
    if kind == "bin":
        return LEVEL[expr[1]]
    return {"cmp": 6, "not": 7, "and": 8, "or": 9}[kind]


class Layout:
    """Random but valid spacing and redundant parentheses."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng

    def pad(self) -> str:
        return self.rng.choice(("", "", " "))

    def op(self, op: str) -> str:
        if op.isalpha() or self.rng.random() < 0.6:
            return f" {op} "
        return op

    def render(self, expr: Expr, need: int = 99) -> str:
        text = self._bare(expr)
        level = _level(expr)
        if level > need or self.rng.random() < 0.08:
            return f"({self.pad()}{text}{self.pad()})"
        return text

    def _bare(self, expr: Expr) -> str:
        kind = expr[0]
        if kind == "lit":
            return str(expr[1])
        if kind == "var":
            return str(expr[1])
        if kind == "call":
            sep = self.rng.choice((", ", ","))
            args = sep.join(self.render(arg) for arg in expr[2])
            return f"{expr[1]}({self.pad()}{args}{self.pad()})"
        if kind == "neg":
            inner = self.render(expr[1], 3)
            return "-" + (" " if inner.startswith("-") or self.rng.random() < 0.3 else "") + inner
        if kind == "not":
            return "not " + self.render(expr[1], 7)
        if kind == "bin":
            level = LEVEL[expr[1]]
            return self.render(expr[2], level) + self.op(expr[1]) + self.render(expr[3], level - 1)
        if kind == "cmp":
            return self.render(expr[2], 5) + self.op(expr[1]) + self.render(expr[3], 5)
        if kind == "and":
            return self.render(expr[1], 8) + " and " + self.render(expr[2], 7)
        if kind == "or":
            # Parenthesize `and` under `or` so the source has no W1103.
            return self.render(expr[1], 7) + " or " + self.render(expr[2], 7)
        raise AssertionError(kind)


# --- programs --------------------------------------------------------------------


@dataclass
class Helper:
    name: str
    params: list[str]
    body: list[tuple]
    result: Expr


@dataclass
class Program:
    helpers: list[Helper] = field(default_factory=list)
    main: list[tuple] = field(default_factory=list)


def _int_expr(draw, names: list[str], helpers: list[Helper], depth: int) -> Expr:  # type: ignore[no-untyped-def]
    if depth <= 0 or draw(st.integers(0, 3)) == 0:
        if names and draw(st.booleans()):
            return ("var", draw(st.sampled_from(names)))
        return ("lit", draw(st.one_of(st.integers(0, 9), st.integers(0, 2**70))))
    choice = draw(st.integers(0, 9))
    if choice == 0:
        return ("neg", _int_expr(draw, names, helpers, depth - 1))
    if choice == 1 and helpers:
        helper = draw(st.sampled_from(helpers))
        return (
            "call",
            helper.name,
            [_int_expr(draw, names, helpers, depth - 1) for _ in helper.params],
        )
    op = draw(st.sampled_from(sorted(LEVEL)))
    return (
        "bin",
        op,
        _int_expr(draw, names, helpers, depth - 1),
        _int_expr(draw, names, helpers, depth - 1),
    )


def _bool_expr(draw, names: list[str], helpers: list[Helper], depth: int) -> Expr:  # type: ignore[no-untyped-def]
    choice = draw(st.integers(0, 4)) if depth > 0 else 0
    if choice <= 1:
        op = draw(st.sampled_from(CMP_OPS))
        return ("cmp", op, _int_expr(draw, names, helpers, 2), _int_expr(draw, names, helpers, 2))
    if choice == 2:
        return ("not", _bool_expr(draw, names, helpers, depth - 1))
    kind = "and" if choice == 3 else "or"
    return (
        kind,
        _bool_expr(draw, names, helpers, depth - 1),
        _bool_expr(draw, names, helpers, depth - 1),
    )


class _Names:
    def __init__(self) -> None:
        self.count = 0

    def fresh(self, prefix: str) -> str:
        self.count += 1
        return f"{prefix}{self.count}"


def _block(
    draw,
    names: list[str],
    mutable: list[str],
    helpers: list[Helper],
    fresh: _Names,  # type: ignore[no-untyped-def]
    depth: int,
    console: bool,
) -> list[tuple]:
    stmts: list[tuple] = []
    names = list(names)
    mutable = list(mutable)
    for _ in range(draw(st.integers(1, 4))):
        choice = draw(st.integers(0, 6))
        if choice == 0 or not names:
            name = fresh.fresh("x")
            stmts.append(("let", name, _int_expr(draw, names, helpers, 3)))
            names.append(name)
        elif choice == 1:
            name = fresh.fresh("v")
            stmts.append(("var", name, _int_expr(draw, names, helpers, 3)))
            names.append(name)
            mutable.append(name)
        elif choice == 2 and mutable:
            target = draw(st.sampled_from(mutable))
            stmts.append(("set", target, _int_expr(draw, names, helpers, 3)))
        elif choice == 3 and depth > 0:
            cond = _bool_expr(draw, names, helpers, 2)
            then = _block(draw, names, mutable, helpers, fresh, depth - 1, console)
            other = (
                _block(draw, names, mutable, helpers, fresh, depth - 1, console)
                if draw(st.booleans())
                else None
            )
            stmts.append(("if", cond, then, other))
        elif choice == 4 and depth > 0:
            counter = fresh.fresh("i")
            bound = draw(st.integers(0, 3))
            body = _block(draw, names + [counter], mutable, helpers, fresh, depth - 1, console)
            stmts.append(("while", counter, bound, body))
        elif console:
            stmts.append(("print", _int_expr(draw, names, helpers, 3)))
        else:
            name = fresh.fresh("x")
            stmts.append(("let", name, _int_expr(draw, names, helpers, 2)))
            names.append(name)
    return stmts


@st.composite
def programs(draw) -> Program:  # type: ignore[no-untyped-def]
    fresh = _Names()
    program = Program()
    for index in range(draw(st.integers(0, 2))):
        params = [fresh.fresh("p") for _ in range(draw(st.integers(1, 2)))]
        body = _block(draw, params, [], program.helpers, fresh, 1, console=False)
        visible = params + [stmt[1] for stmt in body if stmt[0] in ("let", "var")]
        result = _int_expr(draw, visible, program.helpers, 2)
        program.helpers.append(Helper(f"h{index}", params, body, result))
    program.main = _block(draw, [], [], program.helpers, fresh, 2, console=True)
    program.main.append(("print", _int_expr(draw, [], program.helpers, 1)))
    return program


def render(program: Program, rng: random.Random) -> str:
    layout = Layout(rng)
    out = ["module p", "", "import std.console exposing print", ""]

    def block(stmts: list[tuple], indent: str) -> None:
        for stmt in stmts:
            kind = stmt[0]
            if kind in ("let", "var"):
                out.append(
                    f"{indent}{kind} {stmt[1]} ={layout.pad() or ' '}{layout.render(stmt[2])}"
                )
            elif kind == "set":
                out.append(f"{indent}set {stmt[1]} = {layout.render(stmt[2])}")
            elif kind == "print":
                out.append(f"{indent}print(show({layout.render(stmt[1])}))")
            elif kind == "if":
                out.append(f"{indent}if {layout.render(stmt[1])} then")
                block(stmt[2], indent + "  ")
                if stmt[3] is not None:
                    out.append(f"{indent}else")
                    block(stmt[3], indent + "  ")
                out.append(f"{indent}end")
            elif kind == "while":
                counter, bound, body = stmt[1], stmt[2], stmt[3]
                out.append(f"{indent}var {counter} = 0")
                out.append(f"{indent}while {counter} < {bound}")
                out.append(f"{indent}do")
                block(body, indent + "  ")
                out.append(f"{indent}  set {counter} = {counter} + 1")
                out.append(f"{indent}end")
            else:
                raise AssertionError(kind)

    for helper in program.helpers:
        params = ", ".join(f"{name}: Int" for name in helper.params)
        out.append(f"function {helper.name}({params}) returns Int")
        out.append("do")
        block(helper.body, "  ")
        out.append(f"  return {layout.render(helper.result)}")
        out.append("end")
        out.append("")
    out += ["function main() returns Unit", "  uses Console", "do"]
    block(program.main, "  ")
    out += ["end", ""]
    return "\n".join(out)


class _Model:
    def __init__(self, program: Program, max_int_bits: int) -> None:
        self.helpers = {helper.name: helper for helper in program.helpers}
        self.limit = 2**max_int_bits
        self.stdout: list[str] = []

    def cap(self, value: int) -> int:
        if abs(value) >= self.limit:
            raise Trap("T6204")
        return value

    def expr(self, expr: Expr, env: dict[str, int]) -> object:
        kind = expr[0]
        if kind == "lit":
            return self.cap(expr[1])
        if kind == "var":
            return env[expr[1]]
        if kind == "neg":
            return self.cap(-self.expr(expr[1], env))  # type: ignore[operator]
        if kind == "call":
            helper = self.helpers[expr[1]]
            args = [self.expr(arg, env) for arg in expr[2]]
            local = dict(zip(helper.params, args, strict=True))
            self.block(helper.body, local, scoped=False)
            return self.expr(helper.result, local)
        if kind == "bin":
            left = self.expr(expr[2], env)
            right = self.expr(expr[3], env)
            assert isinstance(left, int) and isinstance(right, int)
            op = expr[1]
            if op in ("div", "mod") and right == 0:
                raise Trap("T6002")
            value = {
                "+": lambda: left + right,
                "-": lambda: left - right,
                "*": lambda: left * right,
                "div": lambda: left // right,
                "mod": lambda: left % right,
            }[op]()
            return self.cap(value)
        if kind == "cmp":
            left = self.expr(expr[2], env)
            right = self.expr(expr[3], env)
            return {
                "==": left == right,
                "!=": left != right,
                "<": left < right,  # type: ignore[operator]
                "<=": left <= right,  # type: ignore[operator]
                ">": left > right,  # type: ignore[operator]
                ">=": left >= right,  # type: ignore[operator]
            }[expr[1]]
        if kind == "not":
            return not self.expr(expr[1], env)
        if kind == "and":
            return bool(self.expr(expr[1], env)) and bool(self.expr(expr[2], env))
        if kind == "or":
            return bool(self.expr(expr[1], env)) or bool(self.expr(expr[2], env))
        raise AssertionError(kind)

    def block(self, stmts: list[tuple], env: dict[str, int], *, scoped: bool = True) -> None:
        declared: list[str] = []
        for stmt in stmts:
            kind = stmt[0]
            if kind in ("let", "var"):
                env[stmt[1]] = self.expr(stmt[2], env)  # type: ignore[assignment]
                declared.append(stmt[1])
            elif kind == "set":
                env[stmt[1]] = self.expr(stmt[2], env)  # type: ignore[assignment]
            elif kind == "print":
                self.stdout.append(str(self.expr(stmt[1], env)))
            elif kind == "if":
                branch = stmt[2] if self.expr(stmt[1], env) else stmt[3]
                if branch is not None:
                    self.block(branch, env)
            elif kind == "while":
                counter, bound, body = stmt[1], stmt[2], stmt[3]
                env[counter] = 0
                declared.append(counter)
                while env[counter] < bound:
                    self.block(body, env)
                    env[counter] += 1
        for name in declared if scoped else ():
            env.pop(name, None)

    def run(self, program: Program) -> tuple[str, str | None]:
        try:
            self.block(program.main, {})
        except Trap as trap:
            return "".join(line + "\n" for line in self.stdout), trap.code
        return "".join(line + "\n" for line in self.stdout), None


def _run(text: str, max_int_bits: int = 65536) -> tuple[int, str, list[str]]:
    outcome = run_text(
        "p.tersa", text, grants={"Console": []}, limits=LimitConfig(max_int_bits=max_int_bits)
    )
    return (
        outcome.exit_code,
        outcome.stdout,
        [d.code for d in outcome.diagnostics if d.severity != "warning"],
    )


@SETTINGS
@given(programs(), st.randoms(use_true_random=False), st.sampled_from((64, 80, 65536)))
def test_generated_programs_match_the_model(
    program: Program, rng: random.Random, bits: int
) -> None:
    text = render(program, rng)
    checked = check_text("p.tersa", text)
    assert checked.exit_code == 0, (text, [d.code for d in checked.diagnostics])
    want_stdout, want_trap = _Model(program, bits).run(program)
    exit_code, stdout, codes = _run(text, bits)
    assert stdout == want_stdout, text
    if want_trap is None:
        assert (exit_code, codes) == (0, []), text
    else:
        assert (exit_code, codes) == (2, [want_trap]), text


@SETTINGS
@given(programs(), st.randoms(use_true_random=False))
def test_fmt_is_idempotent_and_keeps_meaning(program: Program, rng: random.Random) -> None:
    text = render(program, rng)
    formatted = format_source("p.tersa", text)
    assert format_source("p.tersa", formatted) == formatted
    assert _ast(formatted) == _ast(text)
    assert _run(formatted) == _run(text)
    assert check_text("p.tersa", formatted).diagnostics == []


@settings(SETTINGS, max_examples=25 * SCALE)
@given(programs(), st.randoms(use_true_random=False))
def test_both_grammar_profiles_accept_generated_programs(
    program: Program, rng: random.Random
) -> None:
    text = render(program, rng)
    assert gbnf_accepts(_grammar("full"), text), text
    assert gbnf_accepts(_grammar("decoding"), format_source("p.tersa", text))


@settings(SETTINGS, max_examples=30 * SCALE)
@given(programs(), st.randoms(use_true_random=False))
def test_runs_are_deterministic(program: Program, rng: random.Random) -> None:
    text = render(program, rng)
    first = run_text("p.tersa", text, grants={"Console": []}, limits=LimitConfig(fuel=10_000))
    second = run_text("p.tersa", text, grants={"Console": []}, limits=LimitConfig(fuel=10_000))
    assert (first.exit_code, first.stdout, first.stderr, first.fuel_used, first.memory_used) == (
        second.exit_code,
        second.stdout,
        second.stderr,
        second.fuel_used,
        second.memory_used,
    )


# --- Int and Int64 arithmetic ----------------------------------------------------


def _show_main(lets: list[str], expr: str) -> str:
    body = "".join(f"  let {line}\n" for line in lets)
    return (
        "module p\n\nimport std.console exposing print\n\n"
        "function main() returns Unit\n  uses Console\ndo\n"
        f"{body}  print(show({expr}))\nend\n"
    )


int64s = st.one_of(
    st.integers(INT64_MIN, INT64_MAX),
    st.sampled_from((INT64_MIN, INT64_MIN + 1, -1, 0, 1, INT64_MAX - 1, INT64_MAX)),
    st.integers(-5, 5),
)


@SETTINGS
@given(int64s, int64s, st.sampled_from(("+", "-", "*", "div", "mod")))
def test_int64_operators_trap_instead_of_wrapping(a: int, b: int, op: str) -> None:
    lets = [
        f'a = Int64.from_int({a}).expect_some("a")',
        f'b = Int64.from_int({b}).expect_some("b")',
    ]
    exit_code, stdout, codes = _run(_show_main(lets, f"a {op} b"))
    if op in ("div", "mod") and b == 0:
        assert (exit_code, codes) == (2, ["T6002"])
        return
    value = {
        "+": a + b,
        "-": a - b,
        "*": a * b,
        "div": a // b if b else 0,
        "mod": a % b if b else 0,
    }[op]
    if INT64_MIN <= value <= INT64_MAX:
        assert (exit_code, stdout, codes) == (0, f"{value}\n", [])
    else:
        assert (exit_code, codes) == (2, ["T6001"])


@SETTINGS
@given(int64s, int64s, st.sampled_from(("add", "sub", "mul")))
def test_int64_checked_operations(a: int, b: int, op: str) -> None:
    lets = [
        f'a = Int64.from_int({a}).expect_some("a")',
        f'b = Int64.from_int({b}).expect_some("b")',
    ]
    exit_code, stdout, codes = _run(_show_main(lets, f"Int64.checked_{op}(a, b)"))
    value = {"add": a + b, "sub": a - b, "mul": a * b}[op]
    shown = f"Some({value})" if INT64_MIN <= value <= INT64_MAX else "None"
    assert (exit_code, stdout, codes) == (0, f"{shown}\n", [])


@SETTINGS
@given(st.integers(-(2**80), 2**80))
def test_int64_from_int_is_none_outside_the_range(n: int) -> None:
    exit_code, stdout, codes = _run(_show_main([], f"Int64.from_int({n})"))
    shown = f"Some({n})" if INT64_MIN <= n <= INT64_MAX else "None"
    assert (exit_code, stdout, codes) == (0, f"{shown}\n", [])


@SETTINGS
@given(st.integers(-(2**200), 2**200), st.integers(-(2**200), 2**200).filter(bool))
def test_div_mod_identity(a: int, b: int) -> None:
    exit_code, stdout, codes = _run(_show_main([], f"[{a} div {b}, {a} mod {b}]"))
    assert (exit_code, codes) == (0, [])
    assert stdout == f"[{a // b}, {a % b}]\n"


# --- no Python exception escapes -------------------------------------------------


@cache
def _corpus() -> tuple[str, ...]:
    paths = sorted((ROOT / "conformance").rglob("*.tersa")) + sorted(
        (ROOT / "examples").rglob("*.tersa")
    )
    return tuple(path.read_bytes().decode("utf-8", errors="replace") for path in paths)


@st.composite
def mutated_programs(draw) -> str:  # type: ignore[no-untyped-def]
    text = draw(st.sampled_from(_corpus()))
    pieces = [
        "(",
        ")",
        "end",
        "do",
        "\n",
        " ",
        "-",
        "0",
        "x",
        '"',
        "#",
        "[",
        ",",
        "=",
        "Int64",
        "with",
        "match",
    ]
    for _ in range(draw(st.integers(1, 4))):
        if not text:
            break
        at = draw(st.integers(0, len(text) - 1))
        action = draw(st.integers(0, 2))
        if action == 0:
            text = text[:at] + text[at + draw(st.integers(1, 8)) :]
        elif action == 1:
            text = text[:at] + draw(st.sampled_from(pieces)) + text[at:]
        else:
            other = draw(st.integers(0, len(text) - 1))
            text = text[:at] + text[other : other + draw(st.integers(1, 20))] + text[at:]
    return text


def _no_internal_errors(diagnostics: list) -> None:  # type: ignore[type-arg]
    for item in diagnostics:
        assert "internal error" not in item.message, item.message
        assert not item.code.startswith("I"), (item.code, item.message)


@settings(SETTINGS, max_examples=120 * SCALE)
@given(mutated_programs())
def test_mutated_corpus_never_raises(text: str) -> None:
    checked = check_text("m.tersa", text)
    _no_internal_errors(checked.diagnostics)
    try:
        formatted = format_source("m.tersa", text)
    except FormatError:
        pass
    else:
        assert format_source("m.tersa", formatted) == formatted
    limits = LimitConfig(fuel=20_000, memory_units=100_000, max_depth=64, output_bytes=4096)
    outcome = run_text("m.tersa", text, grants={"Console": []}, limits=limits)
    _no_internal_errors(outcome.diagnostics)
    tested = run_tests("m.tersa", text, limits=limits, cases=5)
    _no_internal_errors(tested.diagnostics)
