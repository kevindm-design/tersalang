# SPDX-License-Identifier: Apache-2.0
"""Abstract syntax tree.

Nodes are mutable: the checker records interface dispatch in `NameExpr.resolved`, and harness
namespacing renames hidden declarations in place.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tersalang.source import Span


@dataclass
class Node:
    """Base of every node that carries a source span."""

    span: Span


@dataclass
class TypeExpr(Node):
    """A type: `mod.Name[ARG, ...]` (kind `"named"`) or `function(TYPE, ...) returns TYPE`."""

    kind: str  # "named" or "function"
    path: list[str] = field(default_factory=list)
    name: str = ""
    args: list[TypeExpr] = field(default_factory=list)
    params: list[TypeExpr] = field(default_factory=list)
    ret: TypeExpr | None = None


@dataclass
class Param(Node):
    """`NAME: TYPE`, as a function, lambda, or property-test parameter or a record or case field."""

    name: str
    ty: TypeExpr


@dataclass
class TypeParam(Node):
    """One entry of a type parameter list, `NAME[: CONSTRAINT and ...]`, as in `[T: Comparable]`."""

    name: str
    constraints: list[TypeExpr]


@dataclass
class Contract(Node):
    """`requires EXPR` or `ensures EXPR` in a function header; `kind` is the keyword."""

    kind: str
    expr: Expr
    # The condition's source text, quoted when the contract fails (§9.3).
    text: str = field(default="", compare=False, repr=False)


@dataclass
class Import(Node):
    """`import a.b [as ALIAS] [exposing NAME, ...]`; `exposing` is None without that clause."""

    path: list[str]
    alias: str | None
    exposing: list[tuple[str, Span]] | None


@dataclass
class FunctionSig(Node):
    """A function header, shared by function, interface, and foreign declarations.

    `function NAME[TYPE_PARAMS](PARAMS) returns TYPE`, then optional `uses EFFECT, ...` and
    `requires`/`ensures` lines. `doc` is the `##` doc comment above the header.
    """

    name: str
    type_params: list[TypeParam]
    params: list[Param]
    ret: TypeExpr
    effects: list[tuple[str, Span]]
    contracts: list[Contract]
    doc: str | None = None


@dataclass
class FunctionDecl(Node):
    """`[public] function ...`: a header followed by its `do ... end` body."""

    public: bool
    sig: FunctionSig
    body: Block
    doc: str | None = None


@dataclass
class RecordDecl(Node):
    """`[public] record NAME[TYPE_PARAMS]` with its fields and `invariant EXPR` lines.

    `invariant_texts` holds the source text of each invariant, quoted when it fails.
    """

    public: bool
    name: str
    type_params: list[TypeParam]
    fields: list[Param]
    invariants: list[Expr]
    doc: str | None = None
    invariant_texts: list[str] = field(default_factory=list, compare=False, repr=False)


@dataclass
class ChoiceCase(Node):
    """`case NAME[(PARAMS)]` inside a choice declaration."""

    name: str
    params: list[Param]


@dataclass
class ChoiceDecl(Node):
    """`[public] choice NAME[TYPE_PARAMS]` with its `case` lines, then `end`."""

    public: bool
    name: str
    type_params: list[TypeParam]
    cases: list[ChoiceCase]
    doc: str | None = None


@dataclass
class InterfaceDecl(Node):
    """`[public] interface NAME[TYPE_PARAMS]` with bodiless function headers, then `end`."""

    public: bool
    name: str
    type_params: list[TypeParam]
    headers: list[FunctionSig]
    doc: str | None = None


@dataclass
class ImplementsDecl(Node):
    """`implements INTERFACE[TYPE]` with the functions that implement it, then `end`."""

    interface: TypeExpr
    functions: list[FunctionDecl]


@dataclass
class ConstDecl(Node):
    """A module constant: `[public] let NAME: TYPE = EXPR` at the top level."""

    public: bool
    name: str
    ty: TypeExpr
    expr: Expr
    doc: str | None = None


@dataclass
class ForeignDecl(Node):
    """`[public] foreign "TARGET" function ...`: a header bound to a host function, no body."""

    public: bool
    target: str
    sig: FunctionSig
    doc: str | None = None


@dataclass
class TestDecl(Node):
    """`test "NAME" do ... end`, or a property test `test "NAME" for all PARAMS do ... end`.

    `property_params` is None for a plain test.
    """

    name: str
    property_params: list[Param] | None
    body: Block


Decl = (
    FunctionDecl
    | RecordDecl
    | ChoiceDecl
    | InterfaceDecl
    | ImplementsDecl
    | ConstDecl
    | ForeignDecl
    | TestDecl
)


@dataclass
class Module(Node):
    """A whole file: `module a.b`, then its imports and declarations."""

    path: list[str]
    imports: list[Import]
    decls: list[Decl]


@dataclass
class Block(Node):
    """A statement sequence: a `do ... end` body or one branch of an `if` or `match`."""

    stmts: list[Stmt]


@dataclass
class LetStmt(Node):
    """`let NAME[: TYPE] = EXPR`, or `var` with `mutable` set.

    `let _ = EXPR` sets `discard` and uses `_` as the name.
    """

    name: str
    ty: TypeExpr | None
    expr: Expr
    mutable: bool
    discard: bool = False


@dataclass
class SetStmt(Node):
    """`set NAME[.FIELD...] = EXPR`; `place` is the variable name followed by the field path."""

    place: list[str]
    expr: Expr


@dataclass
class ReturnStmt(Node):
    """`return [EXPR]`; `expr` is None for a bare `return`."""

    expr: Expr | None


@dataclass
class FailStmt(Node):
    """`fail EXPR`, which stops the program with a trap carrying the message."""

    expr: Expr


@dataclass
class ExpectStmt(Node):
    """`expect EXPR` inside a test."""

    expr: Expr


@dataclass
class BreakStmt(Node):
    """`break`."""


@dataclass
class ContinueStmt(Node):
    """`continue`."""


@dataclass
class IfArm:
    """One `if COND then` or `elseif COND then` branch. It has no span of its own."""

    cond: Expr
    block: Block


@dataclass
class IfStmt(Node):
    """`if COND then ... [elseif COND then ...] [else ...] end`.

    `else_block` is None without `else`.
    """

    arms: list[IfArm]
    else_block: Block | None


@dataclass
class MatchArm:
    """`case PATTERN [if GUARD] then ...` inside a `match`. It has no span of its own."""

    pattern: Pattern
    guard: Expr | None
    block: Block


@dataclass
class MatchStmt(Node):
    """`match EXPR`, then its `case` arms, then `end`."""

    expr: Expr
    arms: list[MatchArm]


@dataclass
class WhileStmt(Node):
    """`while COND do ... end`."""

    cond: Expr
    body: Block


@dataclass
class ForStmt(Node):
    """`for NAME in EXPR do ... end`."""

    name: str
    expr: Expr
    body: Block


@dataclass
class UsingStmt(Node):
    """`using NAME = EXPR do ... end`; the resource is closed when the block exits."""

    name: str
    expr: Expr
    body: Block


@dataclass
class ExprStmt(Node):
    """An expression used as a statement, usually a call."""

    expr: Expr


Stmt = (
    LetStmt
    | SetStmt
    | ReturnStmt
    | FailStmt
    | ExpectStmt
    | BreakStmt
    | ContinueStmt
    | IfStmt
    | MatchStmt
    | WhileStmt
    | ForStmt
    | UsingStmt
    | ExprStmt
)


@dataclass
class LiteralExpr(Node):
    """An int, float, text, or `true`/`false` literal.

    `kind` is `"int"`, `"float"`, `"text"`, or `"bool"`, and `value` is the decoded value.
    """

    kind: str
    value: object


@dataclass
class NameExpr(Node):
    """A bare lower or upper name, such as `total` or `Some`."""

    name: str
    # Set by the checker when the name is an interface function: (interface,
    # implementing type or None for runtime dispatch, dispatch argument index).
    resolved: tuple[str, str | None, int | None] | None = field(
        default=None, compare=False, repr=False
    )


@dataclass
class UnaryExpr(Node):
    """`not EXPR`, `-EXPR`, or `try EXPR`; `op` is the operator text."""

    op: str
    expr: Expr


@dataclass
class BinaryExpr(Node):
    """`LEFT OP RIGHT` for arithmetic, comparison, `and`, and `or`; `op` is the operator text."""

    op: str
    left: Expr
    right: Expr


@dataclass
class Arg(Node):
    """One call argument, `EXPR` or `NAME = EXPR`; `name` is None when it is positional."""

    name: str | None
    expr: Expr


@dataclass
class CallExpr(Node):
    """`FUNC(ARG, ...)`, including method calls such as `xs.length()`."""

    func: Expr
    args: list[Arg]


@dataclass
class FieldExpr(Node):
    """`RECV.NAME`: a field, method, or member access such as `Float.nan`."""

    recv: Expr
    name: str


@dataclass
class FieldInit(Node):
    """`NAME = EXPR` inside a `with (...)` update."""

    name: str
    expr: Expr


@dataclass
class WithExpr(Node):
    """`RECV with (NAME = EXPR, ...)`: a copy of a record with some fields replaced."""

    recv: Expr
    fields: list[FieldInit]


@dataclass
class LambdaExpr(Node):
    """`function(PARAMS) returns TYPE do EXPR end`; the body is a single expression."""

    params: list[Param]
    ret: TypeExpr
    body: Expr


@dataclass
class ListExpr(Node):
    """`[EXPR, ...]`."""

    elements: list[Expr]


@dataclass
class MapExpr(Node):
    """`{KEY: VALUE, ...}`, as `(key, value)` pairs in source order."""

    entries: list[tuple[Expr, Expr]]


@dataclass
class GroupExpr(Node):
    """`(EXPR)`, kept so the formatter and the `and`/`or` mixing warning see the parentheses."""

    expr: Expr


@dataclass
class ResultExpr(Node):
    """`result`: the function's return value, inside an `ensures` contract."""


@dataclass
class OldExpr(Node):
    """`old(EXPR)`: the value of `EXPR` at function entry, inside an `ensures` contract."""

    expr: Expr


Expr = (
    LiteralExpr
    | NameExpr
    | UnaryExpr
    | BinaryExpr
    | CallExpr
    | FieldExpr
    | WithExpr
    | LambdaExpr
    | ListExpr
    | MapExpr
    | GroupExpr
    | ResultExpr
    | OldExpr
)


@dataclass
class WildPat(Node):
    """The `_` pattern."""


@dataclass
class BindPat(Node):
    """A lower name pattern, which binds the matched value."""

    name: str


@dataclass
class LitPat(Node):
    """A literal pattern; numbers may have a leading `-`. Fields are as in `LiteralExpr`."""

    kind: str
    value: object


@dataclass
class CtorPat(Node):
    """A case pattern, `[mod.]CASE[(PATTERN, ...)]`.

    `fields` is None when the pattern has no parentheses.
    """

    path: list[str]
    name: str
    fields: list[Pattern] | None


Pattern = WildPat | BindPat | LitPat | CtorPat
