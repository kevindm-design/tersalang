# SPDX-License-Identifier: Apache-2.0
"""Tree-walking evaluator. Limits and integer checks happen before large work."""

from __future__ import annotations

import functools
import math
import time
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import NoReturn

from tersalang.ast import (
    BinaryExpr,
    BindPat,
    Block,
    BreakStmt,
    CallExpr,
    ChoiceDecl,
    ConstDecl,
    ContinueStmt,
    Contract,
    CtorPat,
    ExpectStmt,
    Expr,
    ExprStmt,
    FailStmt,
    FieldExpr,
    ForeignDecl,
    ForStmt,
    FunctionDecl,
    FunctionSig,
    GroupExpr,
    IfStmt,
    ImplementsDecl,
    InterfaceDecl,
    LambdaExpr,
    LetStmt,
    ListExpr,
    LiteralExpr,
    LitPat,
    MapExpr,
    MatchStmt,
    Module,
    NameExpr,
    OldExpr,
    Pattern,
    RecordDecl,
    ResultExpr,
    ReturnStmt,
    SetStmt,
    TestDecl,
    UnaryExpr,
    UsingStmt,
    WhileStmt,
    WithExpr,
)
from tersalang.builtins import BY_ID, methods_of, module_members, statics_of
from tersalang.diagnostics import Diagnostic, Related
from tersalang.integers import (
    INT64_MAX,
    INT64_MIN,
    DivisionByZero,
    Int64Overflow,
    IntCapExceeded,
    add64,
    add_int,
    div64,
    div_int,
    mod64,
    mod_int,
    mul64,
    mul_int,
    neg64,
    neg_int,
    pow_int,
    sub64,
    sub_int,
)
from tersalang.limits import (
    FuelExhausted,
    LimitConfig,
    MemoryExhausted,
    Meter,
    RecursionLimit,
    WallClockExceeded,
    in_process_wall_message,
)
from tersalang.namespacing import public_name
from tersalang.show import show
from tersalang.source import Span
from tersalang.typesys import COMPARABLE
from tersalang.values import (
    Value,
    VBool,
    VBytes,
    VChoice,
    VFloat,
    VInt,
    VInt64,
    VList,
    VMap,
    VMutableList,
    VMutableMap,
    VRecord,
    VResource,
    VSet,
    VText,
    VUnit,
    equal,
    map_get,
    map_put,
    set_has,
)

UNIT = VUnit()
NONE = VChoice("Option", "None", ())
LESS = VChoice("Ordering", "Less", ())
EQUAL = VChoice("Ordering", "Equal", ())
GREATER = VChoice("Ordering", "Greater", ())
NULL = VChoice("Json", "Null", ())


class Trap(Exception):
    """A runtime error that stops evaluation; `diagnostic` says what went wrong."""

    def __init__(self, diagnostic: Diagnostic) -> None:
        self.diagnostic = diagnostic


class _Return(Exception):
    def __init__(self, value: Value) -> None:
        self.value = value


class _Break(Exception):
    pass


class _Continue(Exception):
    pass


class _Propagate(Exception):
    def __init__(self, value: Value) -> None:
        self.value = value


@dataclass
class VBuiltin:
    """A standard-library function value, named by its `Builtin.id`."""

    ident: str


@dataclass
class VCtor:
    """The constructor of a choice case that has fields; a field-less case is a `VChoice`."""

    type_name: str
    case: str
    fields: tuple[str, ...]


@dataclass
class VRecordCtor:
    """A record constructor.

    Building or updating a record checks `invariants` (`T6103`, or `T6104` if one traps).
    `texts` holds their source text for the failure message.
    """

    name: str
    fields: tuple[str, ...]
    invariants: tuple[Expr, ...]
    texts: tuple[str, ...] = ()


@dataclass
class VNamespace:
    """A type or module namespace, such as `Int` or `Json`, whose members are `Name.member`."""

    members: dict[str, Value]


@dataclass
class VUserFunc:
    """A function declared in the program."""

    decl: FunctionDecl
    # (interface parameter name, own parameter name) pairs, so inherited
    # interface contracts can name parameters the implementation renamed.
    aliases: tuple[tuple[str, str], ...] = ()


@dataclass
class VIfaceFn:
    """An interface function that picks its implementation from an argument."""

    iface: str
    name: str
    index: int


@dataclass
class VForeign:
    """A `foreign` Python function; calling it outside host mode traps with `E4012`."""

    decl: ForeignDecl


@dataclass
class VLambda:
    """A lambda with a snapshot of every name visible where it was created."""

    params: tuple[str, ...]
    body: Expr
    captured: dict[str, Value]


@dataclass
class VBound:
    """A method value: calling it calls `target` with `receiver` as the first argument."""

    receiver: Value
    target: Value


@dataclass
class Host:
    """What the process is allowed to do for one run."""

    grants: dict[str, list[str]] = field(default_factory=dict)
    seed: int = 0
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    stdin: str = ""
    mode: str = "dev"
    limits: LimitConfig = field(default_factory=LimitConfig)
    source_dir: str = "."
    filename: str = "<stdin>"


@dataclass
class ExecResult:
    """How a run ended.

    `diagnostic` is the trap or first failure, or `None`. `more_failures` holds any later
    test failures, and `counts` is set only by `Interpreter.run_tests`. `memory_used` is in
    memory units.
    """

    value: Value | None
    stdout: str
    stderr: str
    diagnostic: Diagnostic | None
    fuel_used: int
    memory_used: int
    output_truncated: bool
    more_failures: tuple[Diagnostic, ...] = ()
    counts: TestCounts | None = None


@dataclass
class TestCounts:
    """Passed and failed counts for tests and doc examples."""

    # Keeps pytest from collecting this class as a test.
    __test__ = False

    tests_passed: int = 0
    tests_failed: int = 0
    examples_passed: int = 0
    examples_failed: int = 0

    def add(self, kind: str, failed: bool) -> None:
        """Count one result of `kind`, which is `tests` or `examples`."""
        name = f"{kind}_{'failed' if failed else 'passed'}"
        setattr(self, name, getattr(self, name) + 1)

    def summary(self) -> str:
        """`4 tests passed, 1 doc example passed` (Language Reference §19).

        Failure counts are added when nonzero.
        """
        parts = [_counted(self.tests_passed, "test", "passed")]
        if self.tests_failed:
            parts.append(_counted(self.tests_failed, "test", "failed"))
        parts.append(_counted(self.examples_passed, "doc example", "passed"))
        if self.examples_failed:
            parts.append(_counted(self.examples_failed, "doc example", "failed"))
        return ", ".join(parts)


def _counted(count: int, noun: str, verb: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'} {verb}"


class Rng:
    """splitmix64. The same seed yields the same stream on every platform."""

    def __init__(self, seed: int) -> None:
        self.state = seed & 0xFFFFFFFFFFFFFFFF

    def next_u64(self) -> int:
        """The next 64-bit value in the stream."""
        self.state = (self.state + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
        return (z ^ (z >> 31)) & 0xFFFFFFFFFFFFFFFF


def _main_returns_unit(decl: FunctionDecl) -> bool:
    ret = decl.sig.ret
    if ret.name == "Unit":
        return True
    return ret.name == "Result" and bool(ret.args) and ret.args[0].name == "Unit"


def _some(value: Value) -> VChoice:
    return VChoice("Option", "Some", (value,))


def _ok(value: Value) -> VChoice:
    return VChoice("Result", "Ok", (value,))


def _err(value: Value) -> VChoice:
    return VChoice("Result", "Error", (value,))


def _foreign_returns_python_result(decl: ForeignDecl) -> bool:
    return _type_is_python_result(decl.sig.ret)


def _type_is_python_result(ty: object) -> bool:
    from tersalang.ast import TypeExpr

    return (
        isinstance(ty, TypeExpr)
        and ty.kind == "named"
        and ty.name == "Result"
        and len(ty.args) == 2
        and ty.args[1].name == "PythonError"
    )


def _ordering(delta: int) -> VChoice:
    if delta < 0:
        return LESS
    if delta > 0:
        return GREATER
    return EQUAL


def _as_bool(value: Value) -> bool:
    if isinstance(value, VBool):
        return value.value
    raise Trap(_bare("T6030", "condition was not Bool"))


def _bare(code: str, message: str) -> Diagnostic:
    span = Span("<runtime>", 0, 0, 1, 1, 1, 1)
    return Diagnostic(code=code, message=message, file=span.file, span=span)


def _hex_bytes(text: str) -> bytes | None:
    """Same acceptance as `bytes.fromhex`, after an even-length check.

    Whitespace is accepted when the raw text length is even. `Bytes.of_hex`
    applies the same rule.
    """
    if len(text) % 2 != 0:
        return None
    try:
        return bytes.fromhex(text)
    except ValueError:
        return None


def _byte_list(items: tuple[Value, ...] | list[Value]) -> bytes | None:
    data = bytearray()
    for item in items:
        number = _int(item)
        if number < 0 or number > 255:
            return None
        data.append(number)
    return bytes(data)


def _ascii_digit(char: str) -> bool:
    """`str.isdigit` also accepts `²` and other scripts' digits, which `int` and JSON reject."""
    return "0" <= char <= "9"


class _PathError(Exception):
    """A path the OS can't resolve; the message never names the granted root."""


def _file_error(exc: OSError, shown: str) -> VChoice:
    """Map an OS error to `FileError` using only the path text the program passed.

    `str(exc)` names the resolved host path, which would leak the granted root.
    """
    if isinstance(exc, FileNotFoundError):
        return VChoice("FileError", "NotFound", (VText(shown),))
    if isinstance(exc, PermissionError):
        return VChoice("FileError", "Denied", (VText(shown),))
    reason = exc.strerror or type(exc).__name__
    return VChoice("FileError", "Io", (VText(f"`{shown}`: {reason}"),))


def _is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def _is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


class Interpreter:
    """Evaluates one checked module under the grants and limits of a `Host`."""

    def __init__(self, module: Module, host: Host) -> None:
        self.module = module
        self.host = host
        self.meter = Meter(host.limits)
        if host.limits.wall_ms is not None:
            self.meter.wall_deadline = time.monotonic() + (host.limits.wall_ms / 1000.0)
        self.globals: dict[str, Value] = {}
        self.stack: list[dict[str, Value]] = []
        self.stdout: list[str] = []
        self.stderr: list[str] = []
        self.rng = Rng(host.seed)
        self.monotonic = 0
        self.stdin_lines = host.stdin.splitlines(keepends=False)
        self.stdin_index = 0
        self._olds: dict[int, Value] = {}
        self._result: Value | None = None
        self._call_span: Span | None = None
        self.impls: dict[tuple[str, str], dict[str, VUserFunc]] = {}
        self.iface_fns: dict[str, VIfaceFn] = {}
        self._install_prelude()
        self._install_module()

    def run_main(self) -> ExecResult:
        """The result of calling `main`.

        No `main` is `E2000`, a return type other than `Unit` or `Result[Unit, E]` is `E3034`,
        and an effect the host did not grant is `E4010`. Running out of fuel, memory units, or
        call depth is `T6201`, `T6202`, or `T6203`; the wall-clock backstop is `I9013`. A value
        propagated by `try` out of `main` becomes the result value.
        """
        main = self.globals.get("main")
        if not isinstance(main, VUserFunc):
            return self._finish(
                None,
                self._diagnostic("E2000", "this file has no `main` function", self.module.span),
            )
        if not _main_returns_unit(main.decl):
            return self._finish(
                None,
                self._diagnostic(
                    "E3034",
                    "main must return Unit or Result[Unit, E]",
                    main.decl.sig.ret.span,
                ),
            )
        effects = {name for name, _span in main.decl.sig.effects}
        missing = sorted(effects - set(self.host.grants))
        if missing:
            uses = main.decl.sig.effects[0][1]
            hint = f"run with --allow {missing[0]}"
            return self._finish(
                None,
                self._diagnostic(
                    "E4010",
                    f"main uses {missing[0]}, but {missing[0]} was not granted",
                    uses,
                    fix=hint,
                ),
            )
        try:
            self._install_consts()
            value = self.apply(main, [], main.decl.span)
        except Trap as trapped:
            return self._finish(None, trapped.diagnostic)
        except _Propagate as propagated:
            value = propagated.value
        except FuelExhausted:
            return self._finish(None, self._diagnostic("T6201", "fuel exhausted", main.decl.span))
        except MemoryExhausted:
            return self._finish(
                None, self._diagnostic("T6202", "memory limit exceeded", main.decl.span)
            )
        except RecursionLimit:
            return self._finish(
                None, self._diagnostic("T6203", "call depth exceeded", main.decl.span)
            )
        except WallClockExceeded:
            return self._finish(
                None,
                self._diagnostic(
                    "I9013", in_process_wall_message(self.host.limits.wall_ms), main.decl.span
                ),
            )
        return self._finish(value, None)

    def run_tests(self, *, cases: int) -> ExecResult:
        """The result of running every doc example, then every `test`.

        Each runs under its own limits, so running out fails only that one. A property test
        tries up to `cases` generated inputs. A wall-clock stop (`I9013`) ends the whole run.
        """
        failures: list[Diagnostic] = []
        counts = TestCounts()
        kind = "examples"
        try:
            for text, span in self._doc_examples():
                before = len(failures)
                self._with_own_limits(
                    span, failures, functools.partial(self._run_doc_example, text, span, failures)
                )
                counts.add(kind, len(failures) > before)
            kind = "tests"
            for decl in self.module.decls:
                if isinstance(decl, TestDecl):
                    before = len(failures)
                    self._run_test_with_own_limits(decl, cases, failures)
                    counts.add(kind, len(failures) > before)
        except Trap as trapped:
            failures.append(trapped.diagnostic)
            counts.add(kind, True)
        except WallClockExceeded:
            failures.append(
                self._diagnostic(
                    "I9013", in_process_wall_message(self.host.limits.wall_ms), self.module.span
                )
            )
            counts.add(kind, True)
        diagnostic = failures[0] if failures else None
        result = self._finish(None, diagnostic, extra=failures[1:])
        result.counts = counts
        return result

    def _finish(
        self,
        value: Value | None,
        diagnostic: Diagnostic | None,
        extra: list[Diagnostic] | None = None,
    ) -> ExecResult:
        return ExecResult(
            value=value,
            stdout="".join(self.stdout),
            stderr="".join(self.stderr),
            diagnostic=diagnostic,
            fuel_used=self.meter.fuel_used,
            memory_used=self.meter.memory_used,
            output_truncated=self.meter.output_truncated,
            more_failures=tuple(extra or ()),
        )

    def _install_prelude(self) -> None:
        def ctor(type_name: str, case: str, fields: tuple[str, ...]) -> Value:
            if not fields:
                return VChoice(type_name, case, ())
            return VCtor(type_name, case, fields)

        cases = {
            "Some": ctor("Option", "Some", ("value",)),
            "None": NONE,
            "Ok": ctor("Result", "Ok", ("value",)),
            "Error": ctor("Result", "Error", ("error",)),
            "Less": LESS,
            "Equal": EQUAL,
            "Greater": GREATER,
            "NotFound": ctor("FileError", "NotFound", ("path",)),
            "Denied": ctor("FileError", "Denied", ("path",)),
            "Io": ctor("FileError", "Io", ("message",)),
            "Invalid": ctor("Utf8Error", "Invalid", ("index",)),
            "Null": NULL,
            "Unit": UNIT,
        }
        self.globals.update(cases)
        self.globals["show"] = VBuiltin("show")
        self.globals["PythonError"] = VRecordCtor("PythonError", ("type_name", "message"), ())
        json_members: dict[str, Value] = {
            "Null": NULL,
            "Bool": ctor("Json", "Bool", ("value",)),
            "Number": ctor("Json", "Number", ("literal",)),
            "String": ctor("Json", "String", ("value",)),
            "Array": ctor("Json", "Array", ("items",)),
            "Object": ctor("Json", "Object", ("entries",)),
        }
        type_names = (
            "Int",
            "Int64",
            "Float",
            "Text",
            "Bytes",
            "List",
            "Map",
            "Set",
            "MutableList",
            "MutableMap",
            "Option",
            "Result",
            "File",
            "Random",
        )
        for type_name in type_names:
            members: dict[str, Value] = {}
            for name, builtin in statics_of(type_name).items():
                members[name] = VBuiltin(builtin.id)
            if type_name == "Int64":
                members["min"] = VInt64(INT64_MIN)
                members["max"] = VInt64(INT64_MAX)
            if type_name == "Float":
                members["infinity"] = VFloat(math.inf)
                members["nan"] = VFloat(math.nan)
            self.globals[type_name] = VNamespace(members)
        self.globals["Json"] = VNamespace(json_members)
        modules = {
            "std.core": ["show"],
            "std.console": ["print", "print_error", "read_line"],
            "std.math": list(module_members("std.math")),
            "std.list": list(module_members("std.list")),
            "std.map": list(module_members("std.map")),
            "std.set": list(module_members("std.set")),
            "std.mutable": list(module_members("std.mutable")),
            "std.text": list(module_members("std.text")),
            "std.file": list(module_members("std.file")),
            "std.clock": ["now", "monotonic"],
            "std.random": list(module_members("std.random")),
            "std.env": ["args", "get"],
            "std.testing": ["approx"],
            "std.json": ["parse", "stringify"],
        }
        for module, names in modules.items():
            bucket: dict[str, Value] = {}
            members = module_members(module)
            for name in names:
                builtin = members.get(name) or next(
                    item for item in BY_ID.values() if item.module == module and item.name == name
                )
                bucket[name] = VBuiltin(builtin.id)
            if module == "std.file":
                for case in ("NotFound", "Denied", "Io"):
                    bucket[case] = cases[case]
            if module == "std.text":
                bucket["Invalid"] = cases["Invalid"]
            if module == "std.json":
                bucket.update(json_members)
            self.globals[module] = VNamespace(bucket)

    def _install_module(self) -> None:
        for imported in self.module.imports:
            key = ".".join(imported.path)
            namespace = self.globals.get(key)
            if isinstance(namespace, VNamespace):
                qualifier = imported.alias or imported.path[-1]
                self.globals[qualifier] = namespace
                if imported.exposing is not None:
                    for name, _span in imported.exposing:
                        if name in namespace.members:
                            self.globals[name] = namespace.members[name]
                        type_ns = self.globals.get(name)
                        if isinstance(type_ns, VNamespace):
                            for child, value in type_ns.members.items():
                                if isinstance(value, (VCtor, VChoice)):
                                    self.globals[child] = value
        for decl in self.module.decls:
            if isinstance(decl, FunctionDecl):
                self.globals[decl.sig.name] = VUserFunc(decl)
            elif isinstance(decl, RecordDecl):
                self.globals[decl.name] = VRecordCtor(
                    decl.name,
                    tuple(param.name for param in decl.fields),
                    tuple(decl.invariants),
                    tuple(decl.invariant_texts),
                )
            elif isinstance(decl, ChoiceDecl):
                for case in decl.cases:
                    names = tuple(param.name for param in case.params)
                    if names:
                        self.globals[case.name] = VCtor(decl.name, case.name, names)
                    else:
                        self.globals[case.name] = VChoice(decl.name, case.name, ())
            elif isinstance(decl, ForeignDecl):
                self.globals[decl.sig.name] = VForeign(decl)
        self._install_interfaces()
        self._consts_ready = False

    def _install_interfaces(self) -> None:
        headers: dict[tuple[str, str], FunctionSig] = {}
        for decl in self.module.decls:
            if not isinstance(decl, InterfaceDecl):
                continue
            type_param = decl.type_params[0].name if decl.type_params else None
            for header in decl.headers:
                headers.setdefault((decl.name, header.name), header)
                index = next(
                    (
                        position
                        for position, param in enumerate(header.params)
                        if param.ty.kind == "named"
                        and not param.ty.path
                        and not param.ty.args
                        and param.ty.name == type_param
                    ),
                    None,
                )
                if index is not None:
                    self.iface_fns.setdefault(header.name, VIfaceFn(decl.name, header.name, index))
        self.iface_fns.setdefault("compare", VIfaceFn("Comparable", "compare", 0))
        for decl in self.module.decls:
            if not isinstance(decl, ImplementsDecl):
                continue
            owner = decl.interface.args[0].name if decl.interface.args else ""
            table = self.impls.setdefault((decl.interface.name, owner), {})
            for fn in decl.functions:
                if fn.sig.name in table:
                    continue
                inherited = headers.get((decl.interface.name, fn.sig.name))
                if inherited is None:
                    table[fn.sig.name] = VUserFunc(fn)
                    continue
                own = tuple(param.name for param in fn.sig.params)
                aliases = tuple(
                    (theirs.name, mine)
                    for theirs, mine in zip(inherited.params, own, strict=False)
                    if theirs.name != mine and theirs.name not in own
                )
                sig = replace(fn.sig, contracts=[*inherited.contracts, *fn.sig.contracts])
                table[fn.sig.name] = VUserFunc(replace(fn, sig=sig), aliases)

    def _implementation(self, iface: str, type_name: str, name: str, span: Span) -> Value:
        found = self.impls.get((iface, type_name), {}).get(name)
        if found is not None:
            return found
        if iface == "Comparable" and name == "compare" and type_name in COMPARABLE:
            return VBuiltin("comparable.compare")
        self._trap("E3046", f"`{type_name}` does not implement `{iface}`", span)
        return UNIT

    def _install_consts(self) -> None:
        """Evaluate top-level constants once, inside the caller's limits.

        Running out of fuel, memory units, or call depth here is a trap at the
        constant, never an uncaught exception.
        """
        if self._consts_ready:
            return
        for decl in self.module.decls:
            if not isinstance(decl, ConstDecl):
                continue
            try:
                self.globals[decl.name] = self.eval_expr(decl.expr)
            except FuelExhausted:
                raise Trap(self._diagnostic("T6201", "fuel exhausted", decl.span)) from None
            except MemoryExhausted:
                raise Trap(self._diagnostic("T6202", "memory limit exceeded", decl.span)) from None
            except RecursionLimit:
                raise Trap(self._diagnostic("T6203", "call depth exceeded", decl.span)) from None
        self._consts_ready = True

    def eval_expr(self, expr: Expr) -> Value:
        """The value of `expr`. Each expression costs one fuel."""
        self.meter.charge_fuel(1)
        if isinstance(expr, LiteralExpr):
            return self._literal(expr)
        if isinstance(expr, NameExpr):
            return self._name(expr)
        if isinstance(expr, GroupExpr):
            return self.eval_expr(expr.expr)
        if isinstance(expr, UnaryExpr):
            return self._unary(expr)
        if isinstance(expr, BinaryExpr):
            return self._binary(expr)
        if isinstance(expr, FieldExpr):
            return self._field(expr)
        if isinstance(expr, CallExpr):
            return self._call(expr)
        if isinstance(expr, ListExpr):
            items = tuple(self.eval_expr(item) for item in expr.elements)
            self.meter.charge_memory(1 + len(items))
            return VList(items)
        if isinstance(expr, MapExpr):
            entries: list[tuple[Value, Value]] = []
            for key_expr, value_expr in expr.entries:
                entries = map_put(
                    entries,
                    self.eval_expr(key_expr),
                    self.eval_expr(value_expr),
                    move_existing=False,
                )
            self.meter.charge_memory(1 + 2 * len(entries))
            return VMap(tuple(entries))
        if isinstance(expr, WithExpr):
            return self._with(expr)
        if isinstance(expr, LambdaExpr):
            captured = self._snapshot()
            self.meter.charge_memory(1 + len(captured))
            return VLambda(tuple(param.name for param in expr.params), expr.body, captured)
        if isinstance(expr, ResultExpr):
            if self._result is None:
                self._trap("E2000", "`result` is only available in ensures", expr.span)
            return self._result
        if isinstance(expr, OldExpr):
            # `_preload_old` evaluates these on entry to the call, keyed by node identity.
            key = id(expr)
            if key not in self._olds:
                self._olds[key] = self.eval_expr(expr.expr)
            return self._olds[key]
        self._trap("E1000", "unsupported expression", expr.span)
        return UNIT

    def exec_block(self, block: Block) -> None:
        """Executes `block` in a new local scope."""
        self.stack.append({})
        try:
            for stmt in block.stmts:
                self.exec_stmt(stmt)
        finally:
            self.stack.pop()

    def exec_stmt(self, stmt: object) -> None:
        """Executes one statement.

        `return`, `break`, and `continue` unwind as `_Return`, `_Break`, and `_Continue`.
        `fail` traps with `T6030`, a false `expect` with `T6031`, and a `match` with no
        matching arm with `E3030`.
        """
        if isinstance(
            stmt,
            (LetStmt, SetStmt, ReturnStmt, FailStmt, ExpectStmt, BreakStmt, ContinueStmt, ExprStmt),
        ):
            self.meter.charge_fuel(1)
        if isinstance(stmt, LetStmt):
            if not stmt.discard:
                self._define(stmt.name, self.eval_expr(stmt.expr))
            else:
                self.eval_expr(stmt.expr)
            return
        if isinstance(stmt, SetStmt):
            self._set_place(stmt.place, self.eval_expr(stmt.expr), stmt.span)
            return
        if isinstance(stmt, ReturnStmt):
            raise _Return(UNIT if stmt.expr is None else self.eval_expr(stmt.expr))
        if isinstance(stmt, FailStmt):
            message = self.eval_expr(stmt.expr)
            text = message.value if isinstance(message, VText) else show(message)
            self._trap("T6030", text, stmt.span, values={"message": text})
        if isinstance(stmt, ExpectStmt):
            if not _as_bool(self.eval_expr(stmt.expr)):
                self._trap("T6031", "expect failed", stmt.span)
            return
        if isinstance(stmt, BreakStmt):
            raise _Break
        if isinstance(stmt, ContinueStmt):
            raise _Continue
        if isinstance(stmt, ExprStmt):
            self.eval_expr(stmt.expr)
            return
        if isinstance(stmt, IfStmt):
            for arm in stmt.arms:
                self.meter.charge_fuel(1)
                if _as_bool(self.eval_expr(arm.cond)):
                    self.exec_block(arm.block)
                    return
            if stmt.else_block is not None:
                self.exec_block(stmt.else_block)
            return
        if isinstance(stmt, MatchStmt):
            self.meter.charge_fuel(1)
            value = self.eval_expr(stmt.expr)
            for match_arm in stmt.arms:
                bindings = self._match(match_arm.pattern, value)
                if bindings is None:
                    continue
                self.stack.append(bindings)
                try:
                    if match_arm.guard is not None and not _as_bool(
                        self.eval_expr(match_arm.guard)
                    ):
                        continue
                    self.exec_block(match_arm.block)
                    return
                finally:
                    self.stack.pop()
            self._trap("E3030", "match was not exhaustive", stmt.span)
        if isinstance(stmt, WhileStmt):
            while True:
                self.meter.charge_fuel(1)
                if not _as_bool(self.eval_expr(stmt.cond)):
                    return
                try:
                    self.exec_block(stmt.body)
                except _Break:
                    return
                except _Continue:
                    continue
        if isinstance(stmt, ForStmt):
            iterable = self.eval_expr(stmt.expr)
            items = self._iterate(iterable, stmt.span)
            if not items:
                self.meter.charge_fuel(1)
            for item in items:
                self.meter.charge_fuel(1)
                self.stack.append({stmt.name: item})
                try:
                    self.exec_block(stmt.body)
                except _Break:
                    return
                except _Continue:
                    continue
                finally:
                    self.stack.pop()
            return
        if isinstance(stmt, UsingStmt):
            resource = self.eval_expr(stmt.expr)
            self.stack.append({stmt.name: resource})
            try:
                self.exec_block(stmt.body)
            finally:
                self.stack.pop()
                if isinstance(resource, VResource):
                    resource.closed = True
            return

    def apply(self, func: Value, args: list[tuple[str | None, Value]], span: Span) -> Value:
        """The result of calling `func` with `args`, which pair an optional name with a value.

        Costs one fuel. A value that is not callable traps with `E3000`.
        """
        self.meter.charge_fuel(1)
        if isinstance(func, VBound):
            args = [(None, func.receiver), *args]
            func = func.target
        if isinstance(func, VBuiltin):
            return self._builtin(func.ident, [value for _name, value in args], span)
        if isinstance(func, VCtor):
            return self._construct_choice(func, args, span)
        if isinstance(func, VRecordCtor):
            return self._construct_record(func, args, span)
        if isinstance(func, VChoice) and not func.fields:
            if args:
                self._trap("E3003", f"`{func.case}` takes no fields", span)
            return func
        if isinstance(func, VLambda):
            return self._call_lambda(func, args, span)
        if isinstance(func, VUserFunc):
            return self._call_user(func, args, span)
        if isinstance(func, VForeign):
            return self._call_foreign(func, args, span)
        if isinstance(func, VIfaceFn):
            if func.index >= len(args):
                self._trap("E3003", f"`{func.name}` is missing arguments", span)
            target = self._implementation(
                func.iface, _runtime_type(args[func.index][1]), func.name, span
            )
            return self.apply(target, args, span)
        self._trap("E3000", "value is not callable", span)
        return UNIT

    def _call_user(
        self, func: VUserFunc, args: list[tuple[str | None, Value]], span: Span
    ) -> Value:
        decl = func.decl
        frame = self._bind_params(tuple(param.name for param in decl.sig.params), args, span)
        for alias, own in func.aliases:
            frame[alias] = frame[own]
        previous_call = self._call_span
        previous_olds = self._olds
        previous_result = self._result
        self._call_span = span
        self._olds = {}
        self._result = None
        self.stack.append(frame)
        try:
            self._check_contracts(decl.sig.contracts, "requires", decl.sig.name, span)
            self._preload_old(decl.sig.contracts)
            try:
                self.meter.enter()
                try:
                    self.exec_block(decl.body)
                    value: Value = UNIT
                except _Return as returned:
                    value = returned.value
                finally:
                    self.meter.leave()
            except _Propagate as propagated:
                return propagated.value
            self._result = value
            self._check_contracts(decl.sig.contracts, "ensures", decl.sig.name, span)
            return value
        finally:
            self.stack.pop()
            self._call_span = previous_call
            self._olds = previous_olds
            self._result = previous_result

    def _call_foreign(
        self, func: VForeign, args: list[tuple[str | None, Value]], span: Span
    ) -> Value:
        if self.host.mode != "host":
            self._trap("E4012", "foreign calls require host mode", span)
        decl = func.decl
        if "Python" not in self.host.grants:
            self._trap("T6302", "Python was not granted", span)
        target = decl.target
        if not target.startswith("python:") or "." not in target[len("python:") :]:
            self._trap("T6401", f"foreign target `{target}` is not a Python function", span)
        module_name, _, attr_path = target[len("python:") :].partition(".")
        import importlib

        try:
            obj: object = importlib.import_module(module_name)
            for part in attr_path.split("."):
                obj = getattr(obj, part)
        except Exception as exc:
            return self._python_failure(decl, exc, span)
        if not callable(obj):
            self._trap("T6401", f"`{target}` is not callable", span)
        if any(name is not None for name, _value in args):
            self._trap("E3081", "named arguments are only allowed when constructing a record", span)
        py_args = [self._to_python(value, span) for _name, value in args]
        frame = self._bind_params(tuple(param.name for param in decl.sig.params), args, span)
        previous_olds = self._olds
        previous_result = self._result
        self._olds = {}
        self._result = None
        self.stack.append(frame)
        try:
            self._check_contracts(decl.sig.contracts, "requires", decl.sig.name, span)
            self._preload_old(decl.sig.contracts)
            try:
                result = obj(*py_args)
            except Exception as exc:
                return self._python_failure(decl, exc, span)
            value = self._from_python(result, decl.sig.ret, span)
            self._result = value
            self._check_contracts(decl.sig.contracts, "ensures", decl.sig.name, span)
            return value
        finally:
            self.stack.pop()
            self._olds = previous_olds
            self._result = previous_result

    def _python_failure(self, decl: ForeignDecl, exc: Exception, span: Span) -> Value:
        if _foreign_returns_python_result(decl):
            error = VRecord(
                "PythonError",
                ("type_name", "message"),
                (VText(type(exc).__name__), VText(str(exc))),
            )
            return _err(error)
        self._trap("T6401", f"{type(exc).__name__}: {exc}", span)

    def _to_python(self, value: Value, span: Span) -> object:
        if isinstance(value, VInt):
            return value.value
        if isinstance(value, VInt64):
            return value.value
        if isinstance(value, VFloat):
            return value.value
        if isinstance(value, VBool):
            return value.value
        if isinstance(value, VText):
            if any(0xD800 <= ord(char) <= 0xDFFF for char in value.value):
                self._trap(
                    "T6402", "text with a lone surrogate cannot cross the Python boundary", span
                )
            return value.value
        if isinstance(value, VBytes):
            return value.value
        if isinstance(value, VUnit):
            return None
        if isinstance(value, VList):
            return [self._to_python(item, span) for item in value.items]
        if isinstance(value, VChoice) and value.type_name == "Option":
            if value.case == "None":
                return None
            return self._to_python(value.fields[0], span)
        self._trap("T6402", "this value cannot cross the Python boundary", span)

    def _from_python(self, value: object, ty: object, span: Span) -> Value:
        from tersalang.ast import TypeExpr

        if not isinstance(ty, TypeExpr):
            self._trap("T6402", "foreign result has no type", span)
        if _type_is_python_result(ty):
            return _ok(self._from_python(value, ty.args[0], span))
        if ty.kind == "function":
            self._trap("T6402", "a function value cannot cross the Python boundary", span)
        name = ty.name
        if name == "Unit":
            return UNIT
        if name == "Bool":
            if not isinstance(value, bool):
                self._trap("T6402", f"cannot convert {type(value).__name__} to Bool", span)
            return VBool(value)
        if name == "Int":
            if isinstance(value, bool) or not isinstance(value, int):
                self._trap("T6402", f"cannot convert {type(value).__name__} to Int", span)
            if value.bit_length() > self.host.limits.max_int_bits:
                self._int_cap(span)
            return VInt(value)
        if name == "Int64":
            if isinstance(value, bool) or not isinstance(value, int):
                self._trap("T6402", f"cannot convert {type(value).__name__} to Int64", span)
            if value < INT64_MIN or value > INT64_MAX:
                self._trap("T6402", f"{value} is outside the Int64 range", span)
            return VInt64(value)
        if name == "Float":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                self._trap("T6402", f"cannot convert {type(value).__name__} to Float", span)
            return VFloat(float(value))
        if name == "Text":
            if not isinstance(value, str):
                self._trap("T6402", f"cannot convert {type(value).__name__} to Text", span)
            return VText(value)
        if name == "Bytes":
            if not isinstance(value, (bytes, bytearray)):
                self._trap("T6402", f"cannot convert {type(value).__name__} to Bytes", span)
            return VBytes(bytes(value))
        if name == "Option" and ty.args:
            if value is None:
                return NONE
            return _some(self._from_python(value, ty.args[0], span))
        if name == "List" and ty.args and isinstance(value, list):
            items = tuple(self._from_python(item, ty.args[0], span) for item in value)
            return VList(items)
        self._trap("T6402", f"cannot convert {type(value).__name__} to {name}", span)

    def _call_lambda(
        self, func: VLambda, args: list[tuple[str | None, Value]], span: Span
    ) -> Value:
        bound = self._bind_params(func.params, args, span)
        self.stack.append(dict(func.captured))
        self.stack.append(bound)
        try:
            self.meter.enter()
            try:
                try:
                    return self.eval_expr(func.body)
                except _Return as returned:
                    return returned.value
                except _Propagate:
                    raise
            finally:
                self.meter.leave()
        finally:
            self.stack.pop()
            self.stack.pop()

    def _bind_params(
        self,
        names: tuple[str, ...],
        args: list[tuple[str | None, Value]],
        span: Span,
    ) -> dict[str, Value]:
        positional = [value for name, value in args if name is None]
        named = {name: value for name, value in args if name is not None}
        if len(positional) > len(names):
            self._trap("E3003", f"expected {len(names)} arguments", span)
        bound: dict[str, Value] = {}
        for index, name in enumerate(names):
            if index < len(positional):
                bound[name] = positional[index]
            elif name in named:
                bound[name] = named.pop(name)
            else:
                self._trap("E3003", f"missing argument `{name}`", span)
        if named:
            self._trap("E3003", f"unknown argument `{next(iter(named))}`", span)
        return bound

    def _check_contracts(
        self,
        contracts: Sequence[Contract],
        kind: str,
        function: str,
        call_span: Span,
    ) -> None:
        for contract in contracts:
            if not isinstance(contract, Contract) or contract.kind != kind:
                continue
            blame = "caller" if kind == "requires" else "function"
            code = "T6101" if kind == "requires" else "T6102"
            try:
                ok = _as_bool(self.eval_expr(contract.expr))
            except Trap as trapped:
                self._trap(
                    "T6104",
                    f"{kind} trapped with {trapped.diagnostic.code}",
                    contract.span,
                    blame=blame,
                    related_span=call_span,
                    related_message=trapped.diagnostic.message,
                )
            if not ok:
                label = "precondition" if kind == "requires" else "postcondition"
                self._trap(
                    code,
                    f"{label} failed: {_condition_text(contract.text, contract.expr)}",
                    contract.span,
                    blame=blame,
                    values=self._condition_values(contract.expr),
                    related_span=call_span,
                    related_message="called from here",
                )

    def _condition_values(self, expr: Expr) -> dict[str, str] | None:
        """Names and field paths in a failed condition, in order of first appearance.

        Read straight from the frame, so rendering them costs no fuel and cannot trap.
        """
        found: dict[str, str] = {}
        self._collect_values(expr, found)
        return found or None

    def _collect_values(self, expr: Expr, found: dict[str, str]) -> None:
        if isinstance(expr, LambdaExpr):
            return
        if isinstance(expr, ResultExpr):
            if self._result is not None:
                found.setdefault("result", show(self._result))
            return
        if isinstance(expr, OldExpr):
            key = _path_text(expr.expr)
            if key is not None and id(expr) in self._olds:
                found.setdefault(f"old({key})", show(self._olds[id(expr)]))
                return
        if isinstance(expr, (NameExpr, FieldExpr)):
            key = _path_text(expr)
            value = self._path_value(expr)
            if key is not None and value is not None:
                found.setdefault(key, show(value))
                return
            if isinstance(expr, NameExpr):
                return
        if isinstance(expr, CallExpr):
            callee = expr.func
            if isinstance(callee, FieldExpr):
                self._collect_values(callee.recv, found)
            for arg in expr.args:
                self._collect_values(arg.expr, found)
            return
        for child in _child_exprs(expr):
            self._collect_values(child, found)

    def _path_value(self, expr: Expr) -> Value | None:
        if isinstance(expr, NameExpr):
            value = self._lookup(expr.name)
            if isinstance(value, VChoice) and not value.fields and value.case == expr.name:
                return None
            if value is None or _is_callable_or_namespace(value):
                return None
            return value
        if isinstance(expr, FieldExpr):
            recv = self._path_value(expr.recv)
            if isinstance(recv, VRecord) and expr.name in recv.names:
                return recv.get(expr.name)
        return None

    def _preload_old(self, contracts: Sequence[Contract]) -> None:
        for contract in contracts:
            if isinstance(contract, Contract) and contract.kind == "ensures":
                self._collect_old(contract.expr)

    def _collect_old(self, expr: Expr) -> None:
        if isinstance(expr, OldExpr):
            self._olds[id(expr)] = self.eval_expr(expr.expr)
            return
        for child in _child_exprs(expr):
            self._collect_old(child)

    def _construct_choice(
        self, ctor: VCtor, args: list[tuple[str | None, Value]], span: Span
    ) -> Value:
        if len(args) != len(ctor.fields):
            self._trap("E3003", f"`{ctor.case}` expects {len(ctor.fields)} fields", span)
        values = tuple(value for _name, value in args)
        self.meter.charge_memory(1 + len(values))
        return VChoice(ctor.type_name, ctor.case, values)

    def _construct_record(
        self, ctor: VRecordCtor, args: list[tuple[str | None, Value]], span: Span
    ) -> Value:
        provided = {name: value for name, value in args if name is not None}
        if any(name is None for name, _value in args):
            self._trap("E3080", "records are constructed with named fields", span)
        missing = [name for name in ctor.fields if name not in provided]
        extra = [name for name in provided if name not in ctor.fields]
        if missing:
            self._trap("E3082", f"missing field `{missing[0]}`", span)
        if extra:
            self._trap("E3082", f"unknown field `{extra[0]}`", span)
        values = tuple(provided[name] for name in ctor.fields)
        record = VRecord(ctor.name, ctor.fields, values)
        self.meter.charge_memory(1 + len(values))
        self._check_invariants(ctor, record, span)
        return record

    def _check_invariants(self, ctor: VRecordCtor, record: VRecord, span: Span) -> None:
        if not ctor.invariants:
            return
        frame = dict(zip(record.names, record.fields, strict=True))
        self.stack.append(frame)
        try:
            texts = (*ctor.texts, *([""] * len(ctor.invariants)))
            for invariant, text in zip(ctor.invariants, texts, strict=False):
                try:
                    ok = _as_bool(self.eval_expr(invariant))
                except Trap as trapped:
                    self._trap(
                        "T6104",
                        f"invariant trapped with {trapped.diagnostic.code}",
                        invariant.span,
                        blame="constructor",
                    )
                if not ok:
                    self._trap(
                        "T6103",
                        f"invariant failed: {_condition_text(text, invariant)}",
                        invariant.span,
                        blame="constructor",
                        values=self._condition_values(invariant),
                        related_span=span,
                        related_message=f"`{ctor.name}` built or updated here",
                    )
        finally:
            self.stack.pop()

    def _literal(self, expr: LiteralExpr) -> Value:
        if expr.kind == "int":
            raw = expr.value
            number = raw if isinstance(raw, int) else int(str(raw))
            self._charge_int(number)
            if number.bit_length() > self.host.limits.max_int_bits:
                self._int_cap(expr.span)
            return VInt(number)
        if expr.kind == "float":
            return VFloat(float(expr.value))  # type: ignore[arg-type]
        if expr.kind == "text":
            text = str(expr.value)
            self.meter.charge_text(text)
            return VText(text)
        if expr.kind == "bool":
            return VBool(bool(expr.value))
        self._trap("E1000", "bad literal", expr.span)
        return UNIT

    def _name(self, expr: NameExpr) -> Value:
        found = self._lookup(expr.name)
        if found is None and expr.resolved is not None:
            iface, type_name, index = expr.resolved
            if type_name is not None:
                return self._implementation(iface, type_name, expr.name, expr.span)
            return VIfaceFn(iface, expr.name, index or 0)
        if found is None:
            found = self.iface_fns.get(expr.name)
        if found is None:
            self._trap("E2000", f"unknown name `{expr.name}`", expr.span)
        return found

    def _unary(self, expr: UnaryExpr) -> Value:
        if expr.op == "try":
            value = self.eval_expr(expr.expr)
            if isinstance(value, VChoice) and value.case in {"Some", "Ok"} and value.fields:
                return value.fields[0]
            if isinstance(value, VChoice) and value.case in {"None", "Error"}:
                raise _Propagate(value)
            self._trap("E3060", "`try` expects Option or Result", expr.span)
        value = self.eval_expr(expr.expr)
        if expr.op == "not":
            return VBool(not _as_bool(value))
        if expr.op == "-":
            if isinstance(value, VInt):
                self._precheck_ready()
                try:
                    result = neg_int(value.value, self.host.limits.max_int_bits)
                except IntCapExceeded:
                    self._int_cap(expr.span)
                self._charge_int(result)
                return VInt(result)
            if isinstance(value, VInt64):
                try:
                    return VInt64(neg64(value.value))
                except Int64Overflow:
                    self._trap("T6001", "Int64 overflow", expr.span)
            if isinstance(value, VFloat):
                return VFloat(-value.value)
        self._trap("E3000", f"unary `{expr.op}` is not valid here", expr.span)
        return UNIT

    def _binary(self, expr: BinaryExpr) -> Value:
        if expr.op == "and":
            if not _as_bool(self.eval_expr(expr.left)):
                return VBool(False)
            return VBool(_as_bool(self.eval_expr(expr.right)))
        if expr.op == "or":
            if _as_bool(self.eval_expr(expr.left)):
                return VBool(True)
            return VBool(_as_bool(self.eval_expr(expr.right)))
        left = self.eval_expr(expr.left)
        right = self.eval_expr(expr.right)
        op = expr.op
        if op in {"==", "!="}:
            same = equal(left, right)
            return VBool(same if op == "==" else not same)
        if op in {"<", "<=", ">", ">="}:
            return VBool(self._ordered(left, right, op, expr.span))
        if op in {"+", "-", "*", "/", "div", "mod"}:
            return self._arith(op, left, right, expr.span)
        self._trap("E1000", f"unknown operator `{op}`", expr.span)
        return UNIT

    def _arith(self, op: str, left: Value, right: Value, span: Span) -> Value:
        if isinstance(left, VText) and isinstance(right, VText) and op == "+":
            self._trap("E3020", "`+` is not defined on Text", span)
        if isinstance(left, VFloat) or isinstance(right, VFloat):
            if not isinstance(left, VFloat) or not isinstance(right, VFloat):
                self._trap("E3024", "Float arithmetic needs two Floats", span)
            x, y = left.value, right.value
            if op == "+":
                return VFloat(x + y)
            if op == "-":
                return VFloat(x - y)
            if op == "*":
                return VFloat(x * y)
            if op == "/":
                return VFloat(_float_div(x, y))
            self._trap("E3021", "use / for Float division", span)
        if isinstance(left, VInt64) and isinstance(right, VInt64):
            return self._arith64(op, left.value, right.value, span)
        if isinstance(left, VInt) and isinstance(right, VInt):
            return self._arith_int(op, left.value, right.value, span)
        self._trap("E3024", "operands do not have the same numeric type", span)
        return UNIT

    def _arith_int(self, op: str, left: int, right: int, span: Span) -> VInt:
        limit = self.host.limits.max_int_bits
        if (
            op == "*"
            and left != 0
            and right != 0
            and left.bit_length() + right.bit_length() - 1 > limit
        ):
            self._int_cap(span)
        try:
            if op in {"+", "-", "*"}:
                kind = {"+": "+", "-": "-", "*": "*"}[op]
                self.meter.charge_int_op(kind, left, right)
            elif op in {"div", "mod"}:
                self.meter.charge_int_op(op, left, right)
            if op == "+":
                result = add_int(left, right, limit)
            elif op == "-":
                result = sub_int(left, right, limit)
            elif op == "*":
                result = mul_int(left, right, limit)
            elif op == "div":
                result = div_int(left, right, limit)
            elif op == "mod":
                result = mod_int(left, right, limit)
            else:
                self._trap("E3021", "`/` is not defined on Int", span)
                result = 0
        except IntCapExceeded:
            self._int_cap(span)
        except DivisionByZero:
            self._trap("T6002", "division by zero", span)
        except FuelExhausted:
            self._fuel(span)
        self._charge_int(result)
        return VInt(result)

    def _arith64(self, op: str, left: int, right: int, span: Span) -> VInt64:
        try:
            if op == "+":
                return VInt64(add64(left, right))
            if op == "-":
                return VInt64(sub64(left, right))
            if op == "*":
                return VInt64(mul64(left, right))
            if op == "div":
                return VInt64(div64(left, right))
            if op == "mod":
                return VInt64(mod64(left, right))
        except Int64Overflow:
            self._trap("T6001", "Int64 overflow", span)
        except DivisionByZero:
            self._trap("T6002", "division by zero", span)
        self._trap("E3021", "`/` is not defined on Int64", span)
        return VInt64(0)

    def _ordered(self, left: Value, right: Value, op: str, span: Span) -> bool:
        if isinstance(left, VInt) and isinstance(right, VInt):
            self.meter.charge_int_op("cmp", left.value, right.value)
            return _cmp_op(left.value, right.value, op)
        if isinstance(left, VInt64) and isinstance(right, VInt64):
            return _cmp_op(left.value, right.value, op)
        if isinstance(left, VFloat) and isinstance(right, VFloat):
            return _cmp_op(left.value, right.value, op)
        if isinstance(left, VText) and isinstance(right, VText):
            return _cmp_op(left.value, right.value, op)
        self._trap("E3025", "ordering is not defined for this type", span)
        return False

    def _field(self, expr: FieldExpr) -> Value:
        recv = self.eval_expr(expr.recv)
        if isinstance(recv, VNamespace):
            found = recv.members.get(expr.name)
            if found is None:
                self._trap("E2005", f"unknown member `{expr.name}`", expr.span)
            return found
        if isinstance(recv, VRecord):
            if expr.name in recv.names:
                return recv.get(expr.name)
            method = self._user_method(recv.type_name, expr.name)
            if method is not None:
                return VBound(recv, method)
            implemented = self._impl_method(recv.type_name, expr.name)
            if implemented is not None:
                return VBound(recv, implemented)
            self._trap("E3082", f"unknown field `{expr.name}`", expr.span)
        type_name = _runtime_type(recv)
        methods = methods_of(type_name)
        builtin = methods.get(public_name(expr.name))
        if builtin is not None:
            return VBound(recv, VBuiltin(builtin.id))
        method = self._user_method(type_name, expr.name)
        if method is not None:
            return VBound(recv, method)
        implemented = self._impl_method(type_name, expr.name)
        if implemented is not None:
            return VBound(recv, implemented)
        self._trap("E3004", f"unknown field `{expr.name}`", expr.span)
        return UNIT

    def _impl_method(self, type_name: str, name: str) -> Value | None:
        for (_iface, owner), table in self.impls.items():
            if owner == type_name and name in table:
                return table[name]
        if name == "compare" and type_name in COMPARABLE:
            return VBuiltin("comparable.compare")
        return None

    def _user_method(self, type_name: str, name: str) -> VUserFunc | None:
        found = self.globals.get(name)
        if not isinstance(found, VUserFunc):
            return None
        params = found.decl.sig.params
        if not params:
            return None
        if params[0].ty.name == type_name:
            return found
        return None

    def _call(self, expr: CallExpr) -> Value:
        func = self.eval_expr(expr.func)
        args = [(arg.name, self.eval_expr(arg.expr)) for arg in expr.args]
        return self.apply(func, args, expr.span)

    def _with(self, expr: WithExpr) -> Value:
        recv = self.eval_expr(expr.recv)
        if not isinstance(recv, VRecord):
            self._trap("E3000", "`with` updates a record", expr.span)
        ctor = self.globals.get(recv.type_name)
        updates = {field.name: self.eval_expr(field.expr) for field in expr.fields}
        unknown = [name for name in updates if name not in recv.names]
        if unknown:
            self._trap("E3082", f"unknown field `{unknown[0]}`", expr.span)
        values = tuple(
            updates.get(name, current)
            for name, current in zip(recv.names, recv.fields, strict=True)
        )
        record = VRecord(recv.type_name, recv.names, values)
        self.meter.charge_memory(1 + len(values))
        if isinstance(ctor, VRecordCtor):
            self._check_invariants(ctor, record, expr.span)
        return record

    def _set_place(self, place: list[str], value: Value, span: Span) -> None:
        if not place:
            self._trap("E1000", "missing assignment target", span)
        root = place[0]
        if len(place) == 1:
            self._assign(root, value, span)
            return
        current = self._lookup(root)
        if not isinstance(current, VRecord):
            self._trap("E3000", "only record fields can be updated through `set`", span)
        updated = self._update_path(current, place[1:], value, span)
        self._assign(root, updated, span)

    def _update_path(self, record: VRecord, path: list[str], value: Value, span: Span) -> VRecord:
        name = path[0]
        if name not in record.names:
            self._trap("E3082", f"unknown field `{name}`", span)
        index = record.names.index(name)
        fields = list(record.fields)
        if len(path) == 1:
            fields[index] = value
        else:
            nested = fields[index]
            if not isinstance(nested, VRecord):
                self._trap("E3000", "only record fields can be updated through `set`", span)
            fields[index] = self._update_path(nested, path[1:], value, span)
        built = VRecord(record.type_name, record.names, tuple(fields))
        ctor = self.globals.get(record.type_name)
        if isinstance(ctor, VRecordCtor):
            self._check_invariants(ctor, built, span)
        return built

    def _match(self, pattern: Pattern, value: Value) -> dict[str, Value] | None:
        if isinstance(pattern, BindPat) and pattern.name == "_":
            return {}
        if pattern.__class__.__name__ == "WildPat":
            return {}
        if isinstance(pattern, BindPat):
            return {pattern.name: value}
        if isinstance(pattern, LitPat):
            if isinstance(value, VInt) and pattern.kind == "int" and value.value == pattern.value:
                return {}
            if (
                isinstance(value, VFloat)
                and pattern.kind == "float"
                and value.value == pattern.value
            ):
                return {}
            if isinstance(value, VText) and pattern.kind == "text" and value.value == pattern.value:
                return {}
            if isinstance(value, VBool) and pattern.kind == "bool" and value.value == pattern.value:
                return {}
            return None
        if isinstance(pattern, CtorPat):
            if not isinstance(value, VChoice) or value.case != pattern.name:
                return None
            fields = pattern.fields or []
            if len(fields) != len(value.fields):
                return None
            bound: dict[str, Value] = {}
            for sub, item in zip(fields, value.fields, strict=True):
                part = self._match(sub, item)
                if part is None:
                    return None
                bound.update(part)
            return bound
        return None

    def _iterate(self, value: Value, span: Span) -> list[Value]:
        if isinstance(value, VList):
            return list(value.items)
        if isinstance(value, VSet):
            return list(value.items)
        if isinstance(value, VMutableList):
            return list(value.items)
        self._trap("E3000", "`for` iterates a List, Set, or MutableList", span)
        return []

    def _builtin(self, ident: str, args: list[Value], span: Span) -> Value:
        try:
            return self._dispatch(ident, args, span)
        except IntCapExceeded:
            self._int_cap(span)
        except FuelExhausted:
            self._fuel(span)
        except MemoryExhausted:
            self._trap("T6202", "memory limit exceeded", span)
        except RecursionLimit:
            self._trap("T6203", "call depth exceeded", span)
        return UNIT

    def _dispatch(self, ident: str, args: list[Value], span: Span) -> Value:
        if ident == "show":
            text = show(args[0])
            self.meter.charge_text(text)
            return VText(text)
        if ident == "int.parse":
            return self._parse_int(args[0], span)
        if ident == "int.compare":
            return _ordering(_cmp_num(_int(args[0]), _int(args[1])))
        if ident == "comparable.compare":
            return _ordering(_compare_builtin(args[0], args[1]))
        if ident == "int.from_float":
            number = _float(args[0])
            if math.isnan(number) or math.isinf(number):
                return NONE
            result = int(number)
            self._fit_int(result, span)
            return _some(VInt(result))
        if ident == "int64.from_int":
            number = _int(args[0])
            if number < INT64_MIN or number > INT64_MAX:
                return NONE
            return _some(VInt64(number))
        if ident == "int64.to_int":
            return VInt(args[0].value) if isinstance(args[0], VInt64) else VInt(0)
        if ident == "int64.checked_add":
            return self._checked64(add64, args, span)
        if ident == "int64.checked_sub":
            return self._checked64(sub64, args, span)
        if ident == "int64.checked_mul":
            return self._checked64(mul64, args, span)
        if ident == "float.from_int":
            try:
                as_float = float(_int(args[0]))
            except OverflowError:
                self._trap("T6003", "Int is too large for Float", span)
            if math.isinf(as_float):
                self._trap("T6003", "Int is too large for Float", span)
            return VFloat(as_float)
        if ident in {"float.sqrt", "math.sqrt"}:
            return VFloat(_ieee("sqrt", math.sqrt, _float(args[0])))
        if ident == "float.fma":
            return VFloat(_fma(_float(args[0]), _float(args[1]), _float(args[2])))
        if ident == "float.total_compare":
            return _ordering(_total_order(_float(args[0]), _float(args[1])))
        if ident == "float.same":
            return VBool(_float_bits(args[0]) == _float_bits(args[1]))
        if ident == "float.round":
            return self._float_to_int(args[0], lambda n: int(round(n)), span)
        if ident == "float.floor":
            return self._float_to_int(args[0], lambda n: int(math.floor(n)), span)
        if ident == "float.ceil":
            return self._float_to_int(args[0], lambda n: int(math.ceil(n)), span)
        if ident == "list.empty":
            self.meter.charge_memory(1)
            return VList(())
        if ident == "list.range":
            return self._range(_int(args[0]), _int(args[1]), span)
        if (
            ident == "std.list.List.length"
            or ident.endswith(".length")
            and ident.startswith("std.list")
        ):
            return VInt(len(_list(args[0]).items))
        if ident == "std.list.List.is_empty":
            return VBool(len(_list(args[0]).items) == 0)
        if ident == "std.list.List.get":
            return self._list_get(args[0], args[1])
        if ident == "std.list.List.at":
            return self._list_at(args[0], args[1], span)
        if ident == "std.list.List.with_appended":
            appended = (*_list(args[0]).items, args[1])
            self.meter.charge_memory(2)
            self._stdlib_fuel(1)
            return VList(appended)
        if ident == "std.list.List.with_item":
            return self._with_item(args, span)
        if ident == "std.list.List.contains":
            self._stdlib_fuel(len(_list(args[0]).items))
            return VBool(any(equal(item, args[1]) for item in _list(args[0]).items))
        if ident == "std.list.List.map":
            return self._list_map(args, span)
        if ident == "std.list.List.filter":
            return self._list_filter(args, span)
        if ident == "std.list.List.fold":
            return self._list_fold(args, span)
        if ident == "std.list.List.zip_with":
            return self._zip_with(args, span)
        if ident == "list.sort":
            return self._sort(args, span)
        if ident == "map.empty":
            self.meter.charge_memory(1)
            return VMap(())
        if ident == "std.map.Map.get":
            found = map_get(_map(args[0]), args[1])
            return NONE if found is None else _some(found)
        if ident == "std.map.Map.with_entry":
            updated = map_put(_map(args[0]).items, args[1], args[2], move_existing=False)
            self.meter.charge_memory(1 + 2)
            return VMap(tuple(updated))
        if ident == "std.map.Map.without_key":
            kept = [(key, value) for key, value in _map(args[0]).items if not equal(key, args[1])]
            self.meter.charge_memory(1)
            return VMap(tuple(kept))
        if ident == "std.map.Map.contains_key":
            return VBool(map_get(_map(args[0]), args[1]) is not None)
        if ident == "std.map.Map.keys":
            keys = tuple(key for key, _value in _map(args[0]).items)
            self.meter.charge_memory(1 + len(keys))
            self._stdlib_fuel(len(keys))
            return VList(keys)
        if ident == "std.map.Map.entries":
            return self._entries(_map(args[0]).items)
        if ident == "std.map.Map.length":
            return VInt(len(_map(args[0]).items))
        if ident == "std.map.Map.is_empty":
            return VBool(not _map(args[0]).items)
        if ident == "set.empty":
            self.meter.charge_memory(1)
            return VSet(())
        if ident == "set.from_list":
            return self._set_from(args[0])
        if ident == "std.set.Set.contains":
            return VBool(set_has(_set(args[0]).items, args[1]))
        if ident == "std.set.Set.with_element":
            set_items = list(_set(args[0]).items)
            if not set_has(set_items, args[1]):
                set_items.append(args[1])
            self.meter.charge_memory(2)
            return VSet(tuple(set_items))
        if ident == "std.set.Set.without_element":
            remaining = tuple(item for item in _set(args[0]).items if not equal(item, args[1]))
            self.meter.charge_memory(1)
            return VSet(remaining)
        if ident == "std.set.Set.length":
            return VInt(len(_set(args[0]).items))
        if ident == "std.set.Set.is_empty":
            return VBool(not _set(args[0]).items)
        if ident == "mlist.new":
            self.meter.charge_memory(1)
            return VMutableList([])
        if ident == "std.mutable.MutableList.push":
            _mlist(args[0]).items.append(args[1])
            self.meter.charge_memory(1)
            return UNIT
        if ident == "std.mutable.MutableList.get":
            data = _mlist(args[0]).items
            index = self._opt_index(_int(args[1]), len(data))
            return NONE if index is None else _some(data[index])
        if ident == "std.mutable.MutableList.set_at":
            data = _mlist(args[0]).items
            index = self._req_index(_int(args[1]), len(data), span, "T6011")
            data[index] = args[2]
            return UNIT
        if ident == "std.mutable.MutableList.length":
            return VInt(len(_mlist(args[0]).items))
        if ident == "std.mutable.MutableList.freeze":
            frozen_list = tuple(_mlist(args[0]).items)
            self.meter.charge_memory(1 + len(frozen_list))
            return VList(frozen_list)
        if ident == "mmap.new":
            self.meter.charge_memory(1)
            return VMutableMap([])
        if ident == "std.mutable.MutableMap.insert":
            mapping = _mmap(args[0])
            mapping.items = map_put(mapping.items, args[1], args[2], move_existing=True)
            self.meter.charge_memory(2)
            return UNIT
        if ident == "std.mutable.MutableMap.remove":
            mapping = _mmap(args[0])
            mapping.items = [
                (key, value) for key, value in mapping.items if not equal(key, args[1])
            ]
            return UNIT
        if ident == "std.mutable.MutableMap.get":
            found = map_get(_mmap(args[0]), args[1])
            return NONE if found is None else _some(found)
        if ident == "std.mutable.MutableMap.keys":
            keys = tuple(key for key, _value in _mmap(args[0]).items)
            self.meter.charge_memory(1 + len(keys))
            return VList(keys)
        if ident == "std.mutable.MutableMap.entries":
            return self._entries(_mmap(args[0]).items)
        if ident == "std.mutable.MutableMap.length":
            return VInt(len(_mmap(args[0]).items))
        if ident == "std.mutable.MutableMap.freeze":
            frozen_map = tuple(_mmap(args[0]).items)
            self.meter.charge_memory(1 + 2 * len(frozen_map))
            return VMap(frozen_map)
        if ident.startswith("std.text.Text.") or ident.startswith("text."):
            return self._text_builtin(ident, args, span)
        if ident == "bytes.from_hex":
            return self._from_hex(args[0])
        if ident == "bytes.of_hex":
            return self._of_hex(args[0], span)
        if ident == "bytes.from_list":
            return self._bytes_from_list(args[0])
        if ident == "bytes.of_list":
            return self._bytes_of_list(args[0], span)
        if ident == "bytes.get":
            raw_bytes = args[0].value if isinstance(args[0], VBytes) else b""
            byte_index = self._opt_index(_int(args[1]), len(raw_bytes))
            return NONE if byte_index is None else _some(VInt(raw_bytes[byte_index]))
        if ident in {"math.min", "math.max", "math.abs", "math.clamp"}:
            return self._numeric(ident, args, span)
        if ident == "math.gcd":
            return VInt(math.gcd(_int(args[0]), _int(args[1])))
        if ident == "math.pow":
            return self._pow(_int(args[0]), _int(args[1]), span)
        if ident == "console.print":
            self._need_grant("Console", span)
            self._write(self.stdout, _text(args[0]) + "\n")
            return UNIT
        if ident == "console.print_error":
            self._need_grant("Console", span)
            self._write(self.stderr, _text(args[0]) + "\n")
            return UNIT
        if ident == "console.read_line":
            self._need_grant("Console", span)
            if self.stdin_index >= len(self.stdin_lines):
                return NONE
            line = self.stdin_lines[self.stdin_index]
            self.stdin_index += 1
            return _some(VText(line))
        if ident.startswith("file."):
            return self._file_builtin(ident, args, span)
        if ident == "clock.now":
            self._need_grant("Clock", span)
            return VInt(0)
        if ident == "clock.monotonic":
            self._need_grant("Clock", span)
            current = self.monotonic
            self.monotonic += 1
            return VInt(current)
        if ident == "random.int":
            self._need_grant("Random", span)
            return self._random_int(_int(args[0]), _int(args[1]), span)
        if ident == "random.float":
            self._need_grant("Random", span)
            return VFloat(self.rng.next_u64() / 2**64)
        if ident == "random.shuffle":
            self._need_grant("Random", span)
            return self._shuffle(args[0])
        if ident == "env.args":
            self._need_grant("Env", span)
            return VList(tuple(VText(item) for item in self.host.args))
        if ident == "env.get":
            self._need_grant("Env", span)
            found = self.host.env.get(_text(args[0]))
            return NONE if found is None else _some(VText(found))
        if ident == "testing.approx":
            left, right, tolerance = _float(args[0]), _float(args[1]), _float(args[2])
            if math.isnan(left) or math.isnan(right):
                return VBool(False)
            return VBool(abs(left - right) <= tolerance)
        if ident == "json.parse":
            return self._json_parse(_text(args[0]))
        if ident == "json.stringify":
            text = _json_stringify(args[0])
            self.meter.charge_text(text)
            return VText(text)
        if ident.startswith("option."):
            return self._option_builtin(ident, args, span)
        if ident.startswith("result."):
            return self._result_builtin(ident, args, span)
        if ident.startswith("math."):
            return self._transcendental(ident, args, span)
        # Unreachable after a successful check. E4013 is only an unknown std module.
        self._trap("E3000", f"internal error: builtin `{ident}` is not implemented", span)
        return UNIT

    def _text_builtin(self, ident: str, args: list[Value], span: Span) -> Value:
        name = ident.rsplit(".", 1)[-1]
        if name == "concat":
            text = _text(args[0]) + _text(args[1])
            self.meter.charge_text(text)
            self._stdlib_fuel(len(text))
            return VText(text)
        if name == "join":
            parts = [_text(item) for item in _list(args[0]).items]
            text = _text(args[1]).join(parts)
            self.meter.charge_text(text)
            return VText(text)
        if name == "join_lines":
            parts = [_text(item) for item in _list(args[0]).items]
            text = "\n".join(parts)
            self.meter.charge_text(text)
            return VText(text)
        if name == "split":
            text = _text(args[0])
            separator = _text(args[1])
            if separator == "":
                self._trap("T6101", "split separator must not be empty", span, blame="caller")
            pieces = tuple(VText(part) for part in text.split(separator))
            self.meter.charge_memory(1 + len(pieces))
            self._stdlib_fuel(len(text))
            return VList(pieces)
        if name == "trim":
            return VText(_text(args[0]).strip())
        if name == "find":
            index = _text(args[0]).find(_text(args[1]))
            return NONE if index < 0 else _some(VInt(index))
        if name == "replace":
            text = _text(args[0]).replace(_text(args[1]), _text(args[2]))
            self.meter.charge_text(text)
            return VText(text)
        if name == "slice":
            return VText(
                self._slice_text(_text(args[0]), _int(args[1]), _int(args[2]), span, trap=True)
            )
        if name == "try_slice":
            try:
                return _some(
                    VText(
                        self._slice_text(
                            _text(args[0]), _int(args[1]), _int(args[2]), span, trap=False
                        )
                    )
                )
            except ValueError:
                return NONE
        if name == "code_points":
            points = tuple(VInt(ord(char)) for char in _text(args[0]))
            self.meter.charge_memory(1 + len(points))
            return VList(points)
        if name == "code_point_count":
            return VInt(len(_text(args[0])))
        if name == "byte_length":
            return VInt(len(_text(args[0]).encode("utf-8")))
        if name == "graphemes":
            grapheme_parts = tuple(VText(part) for part in _graphemes(_text(args[0])))
            self.meter.charge_memory(1 + len(grapheme_parts))
            return VList(grapheme_parts)
        if name == "to_upper":
            return VText(_text(args[0]).upper())
        if name == "to_lower":
            return VText(_text(args[0]).lower())
        if name == "normalize_nfc":
            return VText(unicodedata.normalize("NFC", _text(args[0])))
        if name == "normalize_nfd":
            return VText(unicodedata.normalize("NFD", _text(args[0])))
        if name == "is_empty":
            return VBool(_text(args[0]) == "")
        if name == "from_utf8":
            data = args[0].value if isinstance(args[0], VBytes) else b""
            try:
                return _ok(VText(data.decode("utf-8")))
            except UnicodeDecodeError as exc:
                return _err(VChoice("Utf8Error", "Invalid", (VInt(exc.start),)))
        self._trap("E3000", f"internal error: unknown text function `{name}`", span)
        return UNIT

    def _option_builtin(self, ident: str, args: list[Value], span: Span) -> Value:
        value = args[0]
        if ident == "option.expect_some":
            if isinstance(value, VChoice) and value.case == "Some":
                return value.fields[0]
            message = _text(args[1])
            self._trap("T6020", message, span, values={"message": message})
        if not isinstance(value, VChoice):
            self._trap("E3000", "expected Option", span)
        if ident == "option.unwrap_or":
            return value.fields[0] if value.case == "Some" else args[1]
        if ident == "option.map":
            if value.case == "None":
                return NONE
            return _some(self.apply(args[1], [(None, value.fields[0])], span))
        if ident == "option.and_then":
            if value.case == "None":
                return NONE
            return self.apply(args[1], [(None, value.fields[0])], span)
        self._trap("E3000", f"internal error: unknown option function `{ident}`", span)
        return UNIT

    def _result_builtin(self, ident: str, args: list[Value], span: Span) -> Value:
        value = args[0]
        if not isinstance(value, VChoice):
            self._trap("E3000", "expected Result", span)
        if ident == "result.unwrap_or":
            return value.fields[0] if value.case == "Ok" else args[1]
        if ident == "result.map":
            if value.case == "Error":
                return value
            return _ok(self.apply(args[1], [(None, value.fields[0])], span))
        if ident == "result.map_error":
            if value.case == "Ok":
                return value
            return _err(self.apply(args[1], [(None, value.fields[0])], span))
        if ident == "result.and_then":
            if value.case == "Error":
                return value
            return self.apply(args[1], [(None, value.fields[0])], span)
        self._trap("E3000", f"internal error: unknown result function `{ident}`", span)
        return UNIT

    def _file_builtin(self, ident: str, args: list[Value], span: Span) -> Value:
        if ident == "file.read_line":
            resource = args[0]
            if not isinstance(resource, VResource):
                self._trap("E3000", "expected File", span)
            if resource.closed:
                self._trap("T6012", "file is closed", span)
            if resource.index >= len(resource.lines):
                return NONE
            line = resource.lines[resource.index]
            resource.index += 1
            return _some(VText(line))
        path = _text(args[0])
        effect = "FileWrite" if ident == "file.write_text" else "FileRead"
        try:
            resolved = self._resolve_path(path, effect, span)
        except _PathError as exc:
            return _err(VChoice("FileError", "Io", (VText(str(exc)),)))
        if ident == "file.read_text":
            return self._read_text(resolved, path)
        if ident == "file.write_text":
            return self._write_text(resolved, path, _text(args[1]))
        if ident == "file.list_dir":
            return self._list_dir(resolved, path)
        if ident == "file.open":
            return self._open_file(resolved, path)
        self._trap("E3000", f"internal error: unknown file function `{ident}`", span)
        return UNIT

    def _need_grant(self, effect: str, span: Span) -> None:
        if effect not in self.host.grants:
            self._trap("T6302", f"{effect} was not granted", span)

    def _resolve_path(self, text: str, effect: str, span: Span) -> Path:
        self._need_grant(effect, span)
        scopes = list(self.host.grants.get(effect) or [])
        if not scopes:
            self._trap("T6301", f"path `{text}` is outside the granted {effect} scope", span)
        if "\x00" in text:
            raise _PathError("path contains a NUL character")
        raw = Path(text)
        for root_text in scopes:
            # Python 3.12 raises RuntimeError on a symlink loop; 3.13+ stops resolving and
            # returns the looping link itself, which a full resolve never otherwise does.
            try:
                root = Path(root_text).resolve()
                candidate = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
                looped = candidate.is_symlink()
            except RuntimeError:
                looped = True
            except OSError:
                raise _PathError(f"path `{text}` cannot be resolved") from None
            if looped:
                raise _PathError(f"path `{text}` has a symlink loop")
            try:
                candidate.relative_to(root)
            except ValueError:
                continue
            return candidate
        self._trap("T6301", f"path `{text}` is outside the granted {effect} scope", span)
        return Path(text)

    def _read_text(self, path: Path, shown: str) -> VChoice:
        if not _is_file(path):
            return _err(VChoice("FileError", "NotFound", (VText(shown),)))
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            return _err(_file_error(exc, shown))
        except UnicodeDecodeError:
            return _err(VChoice("FileError", "Io", (VText(f"`{shown}` is not valid UTF-8"),)))
        self.meter.charge_text(text)
        return _ok(VText(text))

    def _write_text(self, path: Path, shown: str, text: str) -> VChoice:
        try:
            path.write_text(text, encoding="utf-8")
        except OSError as exc:
            return _err(_file_error(exc, shown))
        return _ok(UNIT)

    def _list_dir(self, path: Path, shown: str) -> VChoice:
        if not _is_dir(path):
            return _err(VChoice("FileError", "NotFound", (VText(shown),)))
        try:
            names = sorted((item.name for item in path.iterdir()), key=lambda name: name)
        except OSError as exc:
            return _err(_file_error(exc, shown))
        return _ok(VList(tuple(VText(name) for name in names)))

    def _open_file(self, path: Path, shown: str) -> VChoice:
        if not _is_file(path):
            return _err(VChoice("FileError", "NotFound", (VText(shown),)))
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            return _err(_file_error(exc, shown))
        except UnicodeDecodeError:
            return _err(VChoice("FileError", "Io", (VText(f"`{shown}` is not valid UTF-8"),)))
        lines = text.splitlines()
        return _ok(VResource("File", shown, lines=lines))

    def _parse_int(self, value: Value, span: Span) -> Value:
        text = _text(value).strip()
        if not text or text in {"+", "-"}:
            return NONE
        body = text[1:] if text[0] in "+-" else text
        if not body or not all(_ascii_digit(char) for char in body):
            return NONE
        significant = body.lstrip("0") or "0"
        limit = self.host.limits.max_int_bits
        if len(significant) > math.ceil(limit * math.log10(2)) + 1:
            self._int_cap(span)
        number = int(text)
        self._fit_int(number, span)
        return _some(VInt(number))

    def _pow(self, base: int, exponent: int, span: Span) -> VInt:
        if exponent < 0:
            self._trap("T6101", "pow exponent must be non-negative", span, blame="caller")
        limit = self.host.limits.max_int_bits
        magnitude = abs(base)
        if magnitude > 1 and (magnitude.bit_length() - 1) * exponent + 1 > limit:
            self._int_cap(span)
        if magnitude > 1 and magnitude.bit_length() * exponent > 64:
            words = math.ceil(magnitude.bit_length() * exponent / 64)
            self.meter.charge_fuel(words * words)
        try:
            result = pow_int(base, exponent, limit)
        except IntCapExceeded:
            self._int_cap(span)
        except ValueError:
            self._trap("T6101", "pow exponent must be non-negative", span, blame="caller")
        self._charge_int(result)
        return VInt(result)

    def _range(self, start: int, end: int, span: Span) -> VList:
        if start >= end:
            self.meter.charge_memory(1)
            return VList(())
        count = end - start
        self.meter.charge_memory(1 + count)
        self._stdlib_fuel(count)
        items = tuple(VInt(start + index) for index in range(count))
        _ = span
        return VList(items)

    def _list_get(self, value: Value, index_value: Value) -> Value:
        items = _list(value).items
        index = self._opt_index(_int(index_value), len(items))
        return NONE if index is None else _some(items[index])

    def _list_at(self, value: Value, index_value: Value, span: Span) -> Value:
        items = _list(value).items
        index = _int(index_value)
        if index < 0 or index >= len(items):
            self._trap(
                "T6011",
                "list index out of range",
                span,
                values={"index": str(index), "length": str(len(items))},
            )
        return items[index]

    def _with_item(self, args: list[Value], span: Span) -> VList:
        items = list(_list(args[0]).items)
        index = self._req_index(_int(args[1]), len(items), span, "T6011")
        items[index] = args[2]
        self.meter.charge_memory(2)
        return VList(tuple(items))

    def _list_map(self, args: list[Value], span: Span) -> VList:
        items = _list(args[0]).items
        mapped = tuple(self.apply(args[1], [(None, item)], span) for item in items)
        self.meter.charge_memory(1 + len(mapped))
        self._stdlib_fuel(len(items))
        return VList(mapped)

    def _list_filter(self, args: list[Value], span: Span) -> VList:
        kept = tuple(
            item
            for item in _list(args[0]).items
            if _as_bool(self.apply(args[1], [(None, item)], span))
        )
        self.meter.charge_memory(1 + len(kept))
        return VList(kept)

    def _list_fold(self, args: list[Value], span: Span) -> Value:
        acc = args[1]
        for item in _list(args[0]).items:
            acc = self.apply(args[2], [(None, acc), (None, item)], span)
        return acc

    def _zip_with(self, args: list[Value], span: Span) -> VList:
        left = _list(args[0]).items
        right = _list(args[1]).items
        count = min(len(left), len(right))
        zipped = tuple(
            self.apply(args[2], [(None, left[i]), (None, right[i])], span) for i in range(count)
        )
        self.meter.charge_memory(1 + len(zipped))
        return VList(zipped)

    def _sort(self, args: list[Value], span: Span) -> VList:
        items = list(_list(args[0]).items)
        if len(args) == 1:

            def compare(left: Value, right: Value) -> int:
                if isinstance(left, (VInt, VInt64, VText)) and type(left) is type(right):
                    if left.value < right.value:  # type: ignore[operator]
                        return -1
                    if left.value > right.value:  # type: ignore[operator]
                        return 1
                    return 0
                self._trap("E3025", "sort needs a comparator for this element type", span)
                return 0
        else:

            def compare(left: Value, right: Value) -> int:
                result = self.apply(args[1], [(None, left), (None, right)], span)
                if isinstance(result, VChoice) and result.case == "Less":
                    return -1
                if isinstance(result, VChoice) and result.case == "Greater":
                    return 1
                return 0

        items.sort(key=lambda item: _SortKey(item, compare))
        self.meter.charge_memory(1 + len(items))
        return VList(tuple(items))

    def _entries(self, items: tuple[tuple[Value, Value], ...] | list[tuple[Value, Value]]) -> VList:
        records = tuple(VRecord("Entry", ("key", "value"), (key, value)) for key, value in items)
        self.meter.charge_memory(1 + 3 * len(records))
        return VList(records)

    def _set_from(self, value: Value) -> VSet:
        items: list[Value] = []
        for item in _list(value).items:
            if not set_has(items, item):
                items.append(item)
        self.meter.charge_memory(1 + len(items))
        return VSet(tuple(items))

    def _numeric(self, ident: str, args: list[Value], span: Span) -> Value:
        if ident == "math.abs":
            value = args[0]
            if isinstance(value, VInt):
                result = abs(value.value)
                self._fit_int(result, span)
                return VInt(result)
            if isinstance(value, VInt64):
                try:
                    return VInt64(neg64(value.value) if value.value < 0 else value.value)
                except Int64Overflow:
                    self._trap("T6001", "Int64 overflow", span)
            if isinstance(value, VFloat):
                return VFloat(abs(value.value))
        if ident == "math.min":
            return args[0] if self._ordered(args[0], args[1], "<=", span) else args[1]
        if ident == "math.max":
            return args[0] if self._ordered(args[0], args[1], ">=", span) else args[1]
        if ident == "math.clamp":
            low = args[1] if self._ordered(args[0], args[1], "<", span) else args[0]
            return args[2] if self._ordered(args[2], low, "<", span) else low
        self._trap("E3027", "builtin numeric function does not accept this type", span)
        return UNIT

    def _transcendental(self, ident: str, args: list[Value], span: Span) -> Value:
        name = ident.split(".", 1)[1]
        functions = {
            "sin": math.sin,
            "cos": math.cos,
            "tan": math.tan,
            "asin": math.asin,
            "acos": math.acos,
            "atan": math.atan,
            "exp": math.exp,
            "log": math.log,
            "log2": math.log2,
            "log10": math.log10,
        }
        if name == "atan2":
            return VFloat(_ieee(name, math.atan2, _float(args[0]), _float(args[1])))
        if name == "float_pow":
            return VFloat(_ieee(name, math.pow, _float(args[0]), _float(args[1])))
        function = functions.get(name)
        if function is None:
            self._trap("E3000", f"internal error: unknown math function `{name}`", span)
        return VFloat(_ieee(name, function, _float(args[0])))

    def _checked64(self, op: object, args: list[Value], span: Span) -> Value:
        _ = span
        try:
            result = op(_i64(args[0]), _i64(args[1]))  # type: ignore[operator]
        except Int64Overflow:
            return NONE
        except DivisionByZero:
            return NONE
        return _some(VInt64(result))

    def _float_to_int(self, value: Value, convert: object, span: Span) -> Value:
        number = _float(value)
        if math.isnan(number) or math.isinf(number):
            return NONE
        result = convert(number)  # type: ignore[operator]
        self._fit_int(int(result), span)
        return _some(VInt(int(result)))

    def _from_hex(self, value: Value) -> Value:
        data = _hex_bytes(_text(value))
        if data is None:
            return NONE
        self.meter.charge_bytes(data)
        return _some(VBytes(data))

    def _of_hex(self, value: Value, span: Span) -> Value:
        text = _text(value)
        if len(text) % 2 != 0:
            self._trap("T6013", "odd number of hex digits", span)
        try:
            data = bytes.fromhex(text)
        except ValueError:
            self._trap("T6013", "hex text is not an even number of hex digits", span)
        self.meter.charge_bytes(data)
        return VBytes(data)

    def _bytes_from_list(self, value: Value) -> Value:
        data = _byte_list(_list(value).items)
        if data is None:
            return NONE
        self.meter.charge_bytes(data)
        return _some(VBytes(data))

    def _bytes_of_list(self, value: Value, span: Span) -> Value:
        data = bytearray()
        for item in _list(value).items:
            number = _int(item)
            if number < 0 or number > 255:
                self._trap("T6013", f"byte value {number} is outside 0..255", span)
            data.append(number)
        raw = bytes(data)
        self.meter.charge_bytes(raw)
        return VBytes(raw)

    def _random_int(self, low: int, high: int, span: Span) -> VInt:
        if low >= high:
            self._trap("T6101", "random range must be non-empty", span, blame="caller")
        span_size = high - low
        self._fit_int(low, span)
        value = low + (self.rng.next_u64() % span_size)
        return VInt(value)

    def _shuffle(self, value: Value) -> VList:
        items = list(_list(value).items)
        for index in range(len(items) - 1, 0, -1):
            swap = self.rng.next_u64() % (index + 1)
            items[index], items[swap] = items[swap], items[index]
        self.meter.charge_memory(1 + len(items))
        return VList(tuple(items))

    def _json_parse(self, text: str) -> VChoice:
        parser = _JsonParser(text)
        try:
            value = parser.parse()
            parser.skip()
            if parser.index != len(text):
                raise ValueError("trailing input")
        except ValueError as exc:
            return _err(VChoice("JsonError", "Invalid", (VInt(parser.index), VText(str(exc)))))
        return _ok(value)

    def _slice_text(self, text: str, start: int, end: int, span: Span, *, trap: bool) -> str:
        count = len(text)
        if not (0 <= start <= end <= count):
            if trap:
                self._trap(
                    "T6010",
                    "text slice is out of range",
                    span,
                    values={"start": str(start), "end": str(end)},
                )
            raise ValueError("slice")
        return text[start:end]

    def _opt_index(self, index: int, length: int) -> int | None:
        if index < 0 or index >= length:
            return None
        return index

    def _req_index(self, index: int, length: int, span: Span, code: str) -> int:
        if index < 0 or index >= length:
            self._trap(
                code,
                "index out of range",
                span,
                values={"index": str(index), "length": str(length)},
            )
        return index

    def _stdlib_fuel(self, amount: int) -> None:
        self.meter.charge_fuel(1 + amount)

    def _write(self, sink: list[str], text: str) -> None:
        written = self.meter.write_output(text)
        sink.append(written)

    def _fit_int(self, number: int, span: Span) -> None:
        if number.bit_length() > self.host.limits.max_int_bits:
            self._int_cap(span)
        self._charge_int(number)

    def _charge_int(self, number: int) -> None:
        self.meter.charge_int_value(number)

    def _precheck_ready(self) -> None:
        return None

    def _snapshot(self) -> dict[str, Value]:
        merged = dict(self.globals)
        for frame in self.stack:
            merged.update(frame)
        return merged

    def _lookup(self, name: str) -> Value | None:
        for frame in reversed(self.stack):
            if name in frame:
                return frame[name]
        return self.globals.get(name)

    def _define(self, name: str, value: Value) -> None:
        if not self.stack:
            self.globals[name] = value
        else:
            self.stack[-1][name] = value

    def _assign(self, name: str, value: Value, span: Span) -> None:
        for frame in reversed(self.stack):
            if name in frame:
                frame[name] = value
                return
        if name in self.globals:
            self.globals[name] = value
            return
        self._trap("E2000", f"unknown name `{name}`", span)

    def _doc_examples(self) -> list[tuple[str, Span]]:
        examples: list[tuple[str, Span]] = []
        for decl in self.module.decls:
            doc = getattr(decl, "doc", None)
            if not isinstance(doc, str):
                continue
            for line in doc.splitlines():
                if line.startswith("Example:"):
                    examples.append((line[len("Example:") :].strip(), decl.span))
        return examples

    def _run_doc_example(self, text: str, span: Span, failures: list[Diagnostic]) -> None:
        if self._consts_failed(failures):
            return
        self._eval_bool_text(text, span, failures)

    def _run_test_with_own_limits(
        self, decl: TestDecl, cases: int, failures: list[Diagnostic]
    ) -> None:
        self._with_own_limits(
            decl.span, failures, lambda: self._run_one_test(decl, cases, failures)
        )

    def _with_own_limits(
        self, span: Span, failures: list[Diagnostic], run: Callable[[], None]
    ) -> None:
        """Run one test or doc example under its own fuel, memory, and output budget.

        Running out fails only that test or example.
        """
        totals = self.meter
        self.meter = Meter(totals.config, wall_deadline=totals.wall_deadline)
        try:
            run()
        except FuelExhausted:
            failures.append(self._diagnostic("T6201", "fuel exhausted", span))
        except MemoryExhausted:
            failures.append(self._diagnostic("T6202", "memory limit exceeded", span))
        except RecursionLimit:
            failures.append(self._diagnostic("T6203", "call depth exceeded", span))
        finally:
            totals.fuel_used += self.meter.fuel_used
            totals.memory_used += self.meter.memory_used
            totals.output_truncated = totals.output_truncated or self.meter.output_truncated
            self.meter = totals

    def _consts_failed(self, failures: list[Diagnostic]) -> bool:
        try:
            self._install_consts()
        except Trap as trapped:
            failures.append(trapped.diagnostic)
            return True
        return False

    def _run_one_test(self, decl: TestDecl, cases: int, failures: list[Diagnostic]) -> None:
        if self._consts_failed(failures):
            return
        if not decl.property_params:
            self._exec_test_body(decl, {}, failures)
            return
        rng = Rng(self.host.seed)
        for index in range(cases):
            sample = {
                param.name: self._generate(param.ty.name, rng, index)
                for param in decl.property_params
            }
            if self._exec_test_body(decl, sample, failures, property_index=index):
                self._shrink(decl, sample, failures)
                return

    def _exec_test_body(
        self,
        decl: TestDecl,
        bindings: dict[str, Value],
        failures: list[Diagnostic],
        property_index: int | None = None,
    ) -> bool:
        self.stack.append(dict(bindings))
        try:
            self.exec_block(decl.body)
            return False
        except Trap as trapped:
            if property_index is not None:
                trapped.diagnostic.values = {
                    **(trapped.diagnostic.values or {}),
                    "seed": str(self.host.seed),
                    **{name: show(value) for name, value in bindings.items()},
                }
            failures.append(trapped.diagnostic)
            return True
        except _Propagate as propagated:
            failures.append(
                self._diagnostic("T6030", f"test propagated {show(propagated.value)}", decl.span)
            )
            return True
        finally:
            self.stack.pop()

    def _shrink(self, decl: TestDecl, sample: dict[str, Value], failures: list[Diagnostic]) -> None:
        if decl.property_params is None:
            return
        changed = True
        current = dict(sample)
        steps = 0
        while changed and steps < 16:
            changed = False
            steps += 1
            for param in decl.property_params:
                value = current[param.name]
                if not isinstance(value, VInt) or value.value == 0:
                    continue
                trial = dict(current)
                trial[param.name] = VInt(value.value // 2)
                before = len(failures)
                self._exec_test_body(decl, trial, failures)
                if len(failures) > before:
                    failures.pop()
                    current[param.name] = trial[param.name]
                    changed = True
        if failures:
            failures[-1].values = {
                **(failures[-1].values or {}),
                "seed": str(self.host.seed),
                **{name: show(value) for name, value in current.items()},
            }

    def _generate(self, type_name: str, rng: Rng, index: int) -> Value:
        specials: list[Value] = [
            VInt(0),
            VInt(1),
            VInt(-1),
            VInt(INT64_MAX),
            VInt(INT64_MIN),
            VBool(False),
            VBool(True),
            VText(""),
            VText("a"),
        ]
        if type_name == "Bool":
            return VBool(index % 2 == 1)
        if type_name == "Text":
            choices = ["", "a", " ", "0"]
            if index < len(choices):
                return VText(choices[index])
            return VText(chr(32 + (rng.next_u64() % 95)))
        if type_name == "Int64":
            if index == 0:
                return VInt64(0)
            if index == 1:
                return VInt64(INT64_MAX)
            if index == 2:
                return VInt64(INT64_MIN)
            return VInt64(int(rng.next_u64() % 201) - 100)
        if index < 5:
            value = specials[index]
            return value if isinstance(value, VInt) else VInt(0)
        return VInt(int(rng.next_u64() % 2001) - 1000)

    def _eval_bool_text(self, text: str, span: Span, failures: list[Diagnostic]) -> None:
        from tersalang.lexer import lex_text
        from tersalang.parser import parse_expression

        source, tokens, diagnostics = lex_text(self.host.filename, text)
        if any(item.severity == "error" for item in diagnostics):
            failures.extend(diagnostics)
            return
        expr = parse_expression(source, tokens, diagnostics)
        if expr is None:
            failures.extend(diagnostics)
            return
        try:
            value = self.eval_expr(expr)
        except Trap as trapped:
            failures.append(trapped.diagnostic)
            return
        if not isinstance(value, VBool) or not value.value:
            failures.append(
                self._diagnostic("T6031", "doc example failed", span, values={"example": text})
            )

    def _diagnostic(
        self,
        code: str,
        message: str,
        span: Span,
        *,
        blame: str | None = None,
        values: dict[str, str] | None = None,
        fix: str | None = None,
        related_span: Span | None = None,
        related_message: str | None = None,
    ) -> Diagnostic:
        from tersalang.diagnostics import Fix

        related: list[Related] = []
        if related_span is not None and related_message is not None:
            related.append(Related(related_message, related_span.file, related_span))
        return Diagnostic(
            code=code,
            message=message,
            file=span.file,
            span=span,
            related=related,
            blame=blame,
            values=values,
            fix=None if fix is None else Fix(fix),
        )

    def _trap(
        self,
        code: str,
        message: str,
        span: Span,
        *,
        blame: str | None = None,
        values: dict[str, str] | None = None,
        related_span: Span | None = None,
        related_message: str | None = None,
    ) -> NoReturn:
        raise Trap(
            self._diagnostic(
                code,
                message,
                span,
                blame=blame,
                values=values,
                related_span=related_span,
                related_message=related_message,
            )
        )

    def _int_cap(self, span: Span) -> NoReturn:
        self._trap(
            "T6204",
            "integer size limit exceeded",
            span,
            values={"max_int_bits": str(self.host.limits.max_int_bits)},
        )

    def _fuel(self, span: Span) -> NoReturn:
        self._trap("T6201", "fuel exhausted", span)


class _SortKey:
    def __init__(self, value: Value, compare: object) -> None:
        self.value = value
        self.compare = compare

    def __lt__(self, other: _SortKey) -> bool:
        return bool(self.compare(self.value, other.value) < 0)  # type: ignore[operator]


class _JsonParser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.index = 0

    def parse(self) -> Value:
        self.skip()
        if self.index >= len(self.text):
            raise ValueError("empty input")
        char = self.text[self.index]
        if char == "n":
            self._word("null")
            return NULL
        if char == "t":
            self._word("true")
            return VChoice("Json", "Bool", (VBool(True),))
        if char == "f":
            self._word("false")
            return VChoice("Json", "Bool", (VBool(False),))
        if char == '"':
            return VChoice("Json", "String", (VText(self._string()),))
        if char == "[":
            return self._array()
        if char == "{":
            return self._object()
        if char == "-" or _ascii_digit(char):
            return VChoice("Json", "Number", (VText(self._number()),))
        raise ValueError("invalid json")

    def skip(self) -> None:
        while self.index < len(self.text) and self.text[self.index] in " \t\r\n":
            self.index += 1

    def _word(self, word: str) -> None:
        if not self.text.startswith(word, self.index):
            raise ValueError("invalid json")
        self.index += len(word)

    def _string(self) -> str:
        self.index += 1
        chars: list[str] = []
        while self.index < len(self.text):
            char = self.text[self.index]
            self.index += 1
            if char == '"':
                return "".join(chars)
            if char == "\\":
                if self.index >= len(self.text):
                    raise ValueError("bad escape")
                escaped = self.text[self.index]
                self.index += 1
                mapping = {
                    '"': '"',
                    "\\": "\\",
                    "/": "/",
                    "b": "\b",
                    "f": "\f",
                    "n": "\n",
                    "r": "\r",
                    "t": "\t",
                }
                if escaped in mapping:
                    chars.append(mapping[escaped])
                elif escaped == "u":
                    hex_digits = self.text[self.index : self.index + 4]
                    if len(hex_digits) < 4:
                        raise ValueError("bad escape")
                    self.index += 4
                    chars.append(chr(int(hex_digits, 16)))
                else:
                    raise ValueError("bad escape")
            else:
                chars.append(char)
        raise ValueError("unterminated string")

    def _number(self) -> str:
        start = self.index
        if self.text[self.index] == "-":
            self.index += 1
        if self.index >= len(self.text) or not _ascii_digit(self.text[self.index]):
            raise ValueError("bad number")
        if self.text[self.index] == "0":
            self.index += 1
        else:
            while self.index < len(self.text) and _ascii_digit(self.text[self.index]):
                self.index += 1
        if self.index < len(self.text) and self.text[self.index] == ".":
            self.index += 1
            if self.index >= len(self.text) or not _ascii_digit(self.text[self.index]):
                raise ValueError("bad number")
            while self.index < len(self.text) and _ascii_digit(self.text[self.index]):
                self.index += 1
        if self.index < len(self.text) and self.text[self.index] in "eE":
            self.index += 1
            if self.index < len(self.text) and self.text[self.index] in "+-":
                self.index += 1
            if self.index >= len(self.text) or not _ascii_digit(self.text[self.index]):
                raise ValueError("bad number")
            while self.index < len(self.text) and _ascii_digit(self.text[self.index]):
                self.index += 1
        return self.text[start : self.index]

    def _array(self) -> VChoice:
        self.index += 1
        items: list[Value] = []
        self.skip()
        if self.index < len(self.text) and self.text[self.index] == "]":
            self.index += 1
            return VChoice("Json", "Array", (VList(()),))
        while True:
            items.append(self.parse())
            self.skip()
            if self.index >= len(self.text):
                raise ValueError("unterminated array")
            if self.text[self.index] == ",":
                self.index += 1
                continue
            if self.text[self.index] == "]":
                self.index += 1
                return VChoice("Json", "Array", (VList(tuple(items)),))
            raise ValueError("expected comma")

    def _object(self) -> VChoice:
        self.index += 1
        entries: list[tuple[Value, Value]] = []
        self.skip()
        if self.index < len(self.text) and self.text[self.index] == "}":
            self.index += 1
            return VChoice("Json", "Object", (VMap(()),))
        while True:
            self.skip()
            if self.index >= len(self.text) or self.text[self.index] != '"':
                raise ValueError("expected key")
            key = self._string()
            self.skip()
            if self.index >= len(self.text) or self.text[self.index] != ":":
                raise ValueError("expected colon")
            self.index += 1
            value = self.parse()
            entries.append((VText(key), value))
            self.skip()
            if self.index >= len(self.text):
                raise ValueError("unterminated object")
            if self.text[self.index] == ",":
                self.index += 1
                continue
            if self.text[self.index] == "}":
                self.index += 1
                return VChoice("Json", "Object", (VMap(tuple(entries)),))
            raise ValueError("expected comma")


def _json_stringify(value: Value) -> str:
    if isinstance(value, VChoice) and value.type_name == "Json":
        if value.case == "Null":
            return "null"
        if value.case == "Bool":
            inner = value.fields[0]
            return "true" if isinstance(inner, VBool) and inner.value else "false"
        if value.case == "Number":
            inner = value.fields[0]
            return inner.value if isinstance(inner, VText) else "0"
        if value.case == "String":
            inner = value.fields[0]
            return _json_string(inner.value if isinstance(inner, VText) else "")
        if value.case == "Array":
            inner = value.fields[0]
            items = inner.items if isinstance(inner, VList) else ()
            return "[" + ",".join(_json_stringify(item) for item in items) + "]"
        if value.case == "Object":
            inner = value.fields[0]
            rows = inner.items if isinstance(inner, VMap) else ()
            parts = [
                _json_string(key.value if isinstance(key, VText) else "")
                + ":"
                + _json_stringify(item)
                for key, item in rows
            ]
            return "{" + ",".join(parts) + "}"
    raise TypeError("not json")


def _json_string(text: str) -> str:
    chars = ['"']
    for char in text:
        if char == '"':
            chars.append('\\"')
        elif char == "\\":
            chars.append("\\\\")
        elif char == "\n":
            chars.append("\\n")
        elif char == "\r":
            chars.append("\\r")
        elif char == "\t":
            chars.append("\\t")
        elif ord(char) < 32:
            chars.append(f"\\u{ord(char):04x}")
        else:
            chars.append(char)
    chars.append('"')
    return "".join(chars)


def _condition_text(text: str, expr: Expr) -> str:
    """The condition as written, on one line."""
    if text:
        return " ".join(text.split())
    return _path_text(expr) or "condition"


def _path_text(expr: Expr) -> str | None:
    if isinstance(expr, NameExpr):
        return expr.name
    if isinstance(expr, FieldExpr):
        recv = _path_text(expr.recv)
        return None if recv is None else f"{recv}.{expr.name}"
    return None


def _is_callable_or_namespace(value: Value) -> bool:
    return isinstance(
        value,
        (VNamespace, VBuiltin, VUserFunc, VForeign, VCtor, VRecordCtor, VIfaceFn, VBound),
    )


def _child_exprs(expr: Expr) -> list[Expr]:
    if isinstance(expr, (LiteralExpr, NameExpr, ResultExpr)):
        return []
    if isinstance(expr, (UnaryExpr, OldExpr, GroupExpr)):
        return [expr.expr]
    if isinstance(expr, BinaryExpr):
        return [expr.left, expr.right]
    if isinstance(expr, CallExpr):
        return [expr.func, *[arg.expr for arg in expr.args]]
    if isinstance(expr, FieldExpr):
        return [expr.recv]
    if isinstance(expr, WithExpr):
        return [expr.recv, *[item.expr for item in expr.fields]]
    if isinstance(expr, ListExpr):
        return list(expr.elements)
    if isinstance(expr, MapExpr):
        found: list[Expr] = []
        for key, value in expr.entries:
            found.extend((key, value))
        return found
    if isinstance(expr, LambdaExpr):
        return [expr.body]
    return []


def _runtime_type(value: Value) -> str:
    if isinstance(value, VInt):
        return "Int"
    if isinstance(value, VInt64):
        return "Int64"
    if isinstance(value, VFloat):
        return "Float"
    if isinstance(value, VBool):
        return "Bool"
    if isinstance(value, VText):
        return "Text"
    if isinstance(value, VBytes):
        return "Bytes"
    if isinstance(value, VList):
        return "List"
    if isinstance(value, VMap):
        return "Map"
    if isinstance(value, VSet):
        return "Set"
    if isinstance(value, VMutableList):
        return "MutableList"
    if isinstance(value, VMutableMap):
        return "MutableMap"
    if isinstance(value, VRecord):
        return value.type_name
    if isinstance(value, VChoice):
        return value.type_name
    if isinstance(value, VResource):
        return "File"
    if isinstance(value, VUnit):
        return "Unit"
    return ""


def _cmp_op(left: object, right: object, op: str) -> bool:
    if op == "<":
        return bool(left < right)  # type: ignore[operator]
    if op == "<=":
        return bool(left <= right)  # type: ignore[operator]
    if op == ">":
        return bool(left > right)  # type: ignore[operator]
    return bool(left >= right)  # type: ignore[operator]


def _cmp_num(left: int, right: int) -> int:
    return (left > right) - (left < right)


_ORDERING_RANK = {"Less": 0, "Equal": 1, "Greater": 2}


def _compare_builtin(left: Value, right: Value) -> int:
    """`compare` for the built-in Comparable types; Text is code-point order."""
    if isinstance(left, VText) and isinstance(right, VText):
        return (left.value > right.value) - (left.value < right.value)
    if isinstance(left, (VInt, VInt64)) and isinstance(right, (VInt, VInt64)):
        return _cmp_num(left.value, right.value)
    if isinstance(left, VBool) and isinstance(right, VBool):
        return _cmp_num(int(left.value), int(right.value))
    if isinstance(left, VChoice) and isinstance(right, VChoice):
        return _cmp_num(_ORDERING_RANK[left.case], _ORDERING_RANK[right.case])
    raise Trap(_bare("E3025", "compare needs two values of the same Comparable type"))


def _int(value: Value) -> int:
    if isinstance(value, VInt):
        return value.value
    raise Trap(_bare("T6030", "expected Int"))


def _i64(value: Value) -> int:
    if isinstance(value, VInt64):
        return value.value
    raise Trap(_bare("T6030", "expected Int64"))


def _float_div(x: float, y: float) -> float:
    """IEEE 754 division. Python raises on a zero divisor; IEEE does not."""
    if y != 0.0:
        return x / y
    if math.isnan(x) or x == 0.0:
        return math.nan
    negative = (math.copysign(1.0, x) < 0) != (math.copysign(1.0, y) < 0)
    return -math.inf if negative else math.inf


def _ieee(name: str, function: object, *args: float) -> float:
    """Call a math function with IEEE 754 results instead of Python exceptions.

    Python's math module raises ValueError on a domain error or pole and
    OverflowError on overflow. IEEE returns NaN, a signed infinity at a pole
    (log(0) is -inf, pow(0, -1) is inf), and a signed infinity on overflow.
    """
    try:
        return float(function(*args))  # type: ignore[operator]
    except OverflowError:
        if name == "float_pow" and _odd_integer_power(args[0], args[1]) and args[0] < 0:
            return -math.inf
        return math.inf
    except ValueError:
        if name in {"log", "log2", "log10"} and args[0] == 0.0:
            return -math.inf
        if name == "float_pow" and args[0] == 0.0 and args[1] < 0:
            if math.copysign(1.0, args[0]) < 0 and _odd_integer_power(args[0], args[1]):
                return -math.inf
            return math.inf
        return math.nan


def _odd_integer_power(_base: float, exponent: float) -> bool:
    return math.isfinite(exponent) and exponent.is_integer() and int(exponent) % 2 == 1


def _float(value: Value) -> float:
    if isinstance(value, VFloat):
        return value.value
    raise Trap(_bare("T6030", "expected Float"))


def _text(value: Value) -> str:
    if isinstance(value, VText):
        return value.value
    raise Trap(_bare("T6030", "expected Text"))


def _list(value: Value) -> VList:
    if isinstance(value, VList):
        return value
    raise Trap(_bare("T6030", "expected List"))


def _map(value: Value) -> VMap:
    if isinstance(value, VMap):
        return value
    raise Trap(_bare("T6030", "expected Map"))


def _set(value: Value) -> VSet:
    if isinstance(value, VSet):
        return value
    raise Trap(_bare("T6030", "expected Set"))


def _mlist(value: Value) -> VMutableList:
    if isinstance(value, VMutableList):
        return value
    raise Trap(_bare("T6030", "expected MutableList"))


def _mmap(value: Value) -> VMutableMap:
    if isinstance(value, VMutableMap):
        return value
    raise Trap(_bare("T6030", "expected MutableMap"))


def _float_bits(value: Value) -> bytes:
    import struct

    if isinstance(value, VFloat):
        return struct.pack(">d", value.value)
    return b""


def _total_order(left: float, right: float) -> int:
    import struct

    def key(number: float) -> tuple[int, int]:
        if math.isnan(number):
            return (2, 0)
        raw = struct.unpack(">q", struct.pack(">d", number))[0]
        if number < 0 or (number == 0 and math.copysign(1.0, number) < 0):
            return (0, -raw)
        return (1, raw)

    left_key = key(left)
    right_key = key(right)
    return (left_key > right_key) - (left_key < right_key)


def _fma(x: float, y: float, z: float) -> float:
    fma_fn = getattr(math, "fma", None)
    if fma_fn is not None:
        # Python 3.13+ raises where IEEE returns NaN or a signed infinity.
        try:
            return float(fma_fn(x, y, z))
        except ValueError:
            return math.nan
        except OverflowError:
            return x * y + z
    import ctypes
    import ctypes.util

    library = ctypes.util.find_library("m")
    if library is None:
        return x * y + z
    libm = ctypes.CDLL(library)
    libm.fma.argtypes = [ctypes.c_double, ctypes.c_double, ctypes.c_double]
    libm.fma.restype = ctypes.c_double
    return float(libm.fma(x, y, z))


def _graphemes(text: str) -> list[str]:
    """Extended grapheme clusters are approximated with combining marks."""
    if not text:
        return []
    parts: list[str] = []
    current = text[0]
    for char in text[1:]:
        if unicodedata.combining(char):
            current += char
        else:
            parts.append(current)
            current = char
    parts.append(current)
    return parts
