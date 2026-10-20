# SPDX-License-Identifier: Apache-2.0
"""Canonical formatter. `format_source` is the Python API behind `tersa fmt`."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from tersalang.ast import (
    Arg,
    BinaryExpr,
    BindPat,
    Block,
    BreakStmt,
    CallExpr,
    ChoiceDecl,
    ConstDecl,
    ContinueStmt,
    ExpectStmt,
    Expr,
    ExprStmt,
    FailStmt,
    FieldExpr,
    FieldInit,
    ForeignDecl,
    ForStmt,
    FunctionDecl,
    FunctionSig,
    GroupExpr,
    IfStmt,
    ImplementsDecl,
    Import,
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
    Param,
    Pattern,
    RecordDecl,
    ResultExpr,
    ReturnStmt,
    SetStmt,
    TestDecl,
    TypeExpr,
    TypeParam,
    UnaryExpr,
    UsingStmt,
    WhileStmt,
    WildPat,
    WithExpr,
)
from tersalang.diagnostics import Diagnostic
from tersalang.lexer import lex_text
from tersalang.parser import parse_module
from tersalang.source import Span

WIDTH = 100
EXACT_FMT_SKIP = "# fmt: skip"
FMT_SKIP_NEAR_MISS = "Format-skip comment is not exactly `# fmt: skip`"
_NEAR_MISS = re.compile(r"^#\s*fmt\s*:\s*skip$", re.IGNORECASE)

# Higher binds tighter. Unary minus shares nothing with binary minus: they are
# different nodes, and both use this scale.
_BIN_PREC = {
    "*": 60,
    "/": 60,
    "div": 60,
    "mod": 60,
    "+": 50,
    "-": 50,
    "==": 40,
    "!=": 40,
    "<": 40,
    "<=": 40,
    ">": 40,
    ">=": 40,
    "and": 30,
    "or": 20,
}
_UNARY_PREC = 70
_NOT_PREC = 35
_WITH_PREC = 80
_POSTFIX_PREC = 90
_NON_ASSOC = frozenset({"==", "!=", "<", "<=", ">", ">="})
# Parent keys for prefix operators, so a prefix `-` never reads as binary `-`.
_PREFIX_KEYS = {"-": "prefix -", "try": "prefix try", "not": "prefix not"}
_UNARY_OPS = frozenset(_PREFIX_KEYS.values())


class FormatError(Exception):
    """The file has parse or lexical errors, so it was left untouched."""

    def __init__(self, diagnostics: list[Diagnostic]) -> None:
        self.diagnostics = diagnostics
        message = diagnostics[0].message if diagnostics else "cannot format this file"
        super().__init__(message)


def format_source(filename: str, text: str) -> str:
    """Return canonically formatted source.

    A file with a `# fmt: skip` line is still parsed. When it parses, the
    original text is returned and the rewrite is skipped. Parse errors raise
    `FormatError`. Warnings, including `W1103`, do not. A near-miss spelling
    is formatted.
    """
    source, tokens, diagnostics = lex_text(filename, text)
    module = parse_module(source, tokens, diagnostics)
    errors = [item for item in diagnostics if item.severity == "error"]
    if module is None or errors:
        raise FormatError(errors)
    if is_fmt_skip(text):
        return text
    return Formatter(source.text, module).render()


def is_fmt_skip(text: str) -> bool:
    """True when a line is exactly `# fmt: skip` after surrounding whitespace."""
    return any(line.strip() == EXACT_FMT_SKIP for line in text.splitlines())


def fmt_skip_warnings(filename: str, text: str) -> list[Diagnostic]:
    """Warn once per full-line near-miss of `# fmt: skip`.

    The exact marker, extra words, and a trailing comment after code are silent.
    """
    found: list[Diagnostic] = []
    offset = 0
    for line_no, raw in enumerate(text.splitlines(keepends=True), start=1):
        if raw.endswith("\r\n"):
            body = raw[:-2]
        elif raw.endswith(("\n", "\r")):
            body = raw[:-1]
        else:
            body = raw
        stripped = body.strip()
        if stripped != EXACT_FMT_SKIP and _NEAR_MISS.fullmatch(stripped):
            lead = len(body) - len(body.lstrip())
            start = offset + lead
            end = start + len(stripped)
            start_col = lead + 1
            found.append(
                Diagnostic(
                    code="W1104",
                    message=FMT_SKIP_NEAR_MISS,
                    file=filename,
                    span=Span(
                        filename,
                        start,
                        end,
                        line_no,
                        start_col,
                        line_no,
                        start_col + len(stripped),
                    ),
                )
            )
        offset += len(raw)
    return found


@dataclass
class Line:
    """One output line, indented `indent` spaces.

    Comments are carried over from source line `anchor`. A `do`, `end`, or
    `else` line takes its anchor from the next source line with that keyword,
    and an `end` line's `text` is what follows `end`.
    """

    indent: int
    text: str
    anchor: int | None = None
    kind: str = "text"  # text, do, end, else, blank


@dataclass
class Comments:
    """The source's comments, keyed by the line number of the code they belong to.

    `leading` is the comment block directly above a line, `detached` holds the
    blocks above it that a blank line separates from it, and `trailing` is a
    comment after code on the line. `do_lines`, `end_lines`, and `else_lines`
    list the lines that start with those keywords, in source order.
    """

    leading: dict[int, list[str]] = field(default_factory=dict)
    detached: dict[int, list[list[str]]] = field(default_factory=dict)
    trailing: dict[int, str] = field(default_factory=dict)
    do_lines: list[int] = field(default_factory=list)
    end_lines: list[int] = field(default_factory=list)
    else_lines: list[int] = field(default_factory=list)
    _do: int = 0
    _end: int = 0
    _else: int = 0

    def pop_do(self) -> int:
        """The source line of the next unused `do`."""
        line = self.do_lines[self._do]
        self._do += 1
        return line

    def pop_end(self) -> int:
        """The source line of the next unused `end`."""
        line = self.end_lines[self._end]
        self._end += 1
        return line

    def pop_else(self) -> int:
        """The source line of the next unused `else`."""
        line = self.else_lines[self._else]
        self._else += 1
        return line


def _scan_comments(text: str) -> Comments:
    comments = Comments()
    groups: list[tuple[list[str], bool]] = []
    current: list[str] = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        code, comment = _split_comment(raw)
        if code.strip() == "" and comment is not None:
            current.append(comment)
            continue
        if code.strip() == "" and comment is None:
            if current:
                groups.append((current, True))
                current = []
            continue
        if current:
            groups.append((current, False))
            current = []
        attached: list[str] = []
        detached: list[list[str]] = []
        for group, closed in groups:
            if closed:
                detached.append(group)
            else:
                attached.extend(group)
        if attached:
            comments.leading[line_no] = attached
        if detached:
            comments.detached[line_no] = detached
        groups = []
        if comment is not None:
            comments.trailing[line_no] = comment
        keyword = _leading_keyword(code)
        if keyword == "do":
            comments.do_lines.append(line_no)
        elif keyword == "end":
            comments.end_lines.append(line_no)
        elif keyword == "else":
            comments.else_lines.append(line_no)
    return comments


def _split_comment(line: str) -> tuple[str, str | None]:
    in_string = False
    index = 0
    while index < len(line):
        char = line[index]
        if in_string:
            if char == "\\":
                index += 2
                continue
            if char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            index += 1
            continue
        if char == "#":
            return line[:index], line[index:].rstrip()
        index += 1
    return line, None


def _leading_keyword(code: str) -> str:
    stripped = code.strip()
    chars: list[str] = []
    for char in stripped:
        if char.isalpha():
            chars.append(char)
            continue
        break
    return "".join(chars)


def _string_lexeme(source: str, start: int) -> str:
    index = source.find('"', start)
    if index < 0:
        return '""'
    chars = ['"']
    cursor = index + 1
    while cursor < len(source):
        char = source[cursor]
        chars.append(char)
        if char == "\\":
            if cursor + 1 < len(source):
                chars.append(source[cursor + 1])
                cursor += 2
                continue
        if char == '"':
            break
        cursor += 1
    return "".join(chars)


def _prec(expr: Expr) -> int | None:
    if isinstance(expr, BinaryExpr):
        return _BIN_PREC[expr.op]
    if isinstance(expr, UnaryExpr):
        return _NOT_PREC if expr.op == "not" else _UNARY_PREC
    if isinstance(expr, WithExpr):
        return _WITH_PREC
    if isinstance(expr, (CallExpr, FieldExpr)):
        return _POSTFIX_PREC
    return None


def _prec_of(op: str) -> int:
    if op == "prefix not":
        return _NOT_PREC
    if op in _UNARY_OPS:
        return _UNARY_PREC
    if op == "with":
        return _WITH_PREC
    if op in {"call", "field"}:
        return _POSTFIX_PREC
    return _BIN_PREC[op]


def _needs_paren(expr: Expr, parent_op: str | None, side: str) -> bool:
    if parent_op is None or isinstance(expr, GroupExpr):
        return False
    if parent_op == "or" and isinstance(expr, BinaryExpr) and expr.op == "and":
        return True
    child = _prec(expr)
    if child is None:
        return False
    parent = _prec_of(parent_op)
    if child < parent:
        return True
    if child > parent:
        return False
    if parent_op in _UNARY_OPS:
        return False
    if parent_op in _NON_ASSOC:
        return True
    return side == "right"


def _suffix(lines: list[Line], text: str) -> None:
    if lines:
        lines[-1].text += text


def _wrap(lines: list[Line]) -> list[Line]:
    if not lines:
        return [Line(0, "()")]
    if lines[0].kind == "text":
        lines[0].text = "(" + lines[0].text
    _suffix(lines, ")")
    return lines


class Formatter:
    """Renders a parsed module as canonical source, keeping the comments of `source`."""

    def __init__(self, source: str, module: Module) -> None:
        self.source = source
        self.module = module
        self.comments = _scan_comments(source)
        self._used: set[int] = set()

    def render(self) -> str:
        """The formatted file: the module line, sorted imports, then the declarations."""
        module = self.module
        lines: list[Line] = [Line(0, "module " + ".".join(module.path), module.span.start_line)]
        imports = sorted(module.imports, key=lambda item: (*item.path, item.alias or ""))
        if imports or module.decls:
            lines.append(Line(0, "", kind="blank"))
        for item in imports:
            lines.append(Line(0, self._import_text(item), item.span.start_line))
        if imports and module.decls:
            lines.append(Line(0, "", kind="blank"))
        for index, decl in enumerate(module.decls):
            if index:
                lines.append(Line(0, "", kind="blank"))
            lines.extend(self._decl(decl, 0))
        return self._emit(lines)

    def _emit(self, lines: list[Line]) -> str:
        out: list[str] = []
        for line in lines:
            if line.kind == "blank":
                if out and out[-1] == "":
                    continue
                out.append("")
                continue
            if line.kind == "do":
                self._emit_text(out, line.indent, self.comments.pop_do(), "do")
                continue
            if line.kind == "end":
                self._emit_text(out, line.indent, self.comments.pop_end(), "end" + line.text)
                continue
            if line.kind == "else":
                self._emit_text(out, line.indent, self.comments.pop_else(), "else")
                continue
            self._emit_text(out, line.indent, line.anchor, line.text)
        while out and out[-1] == "":
            out.pop()
        return "\n".join(out) + "\n"

    def _emit_text(self, out: list[str], indent: int, anchor: int | None, text: str) -> None:
        pad = " " * indent
        trail: str | None = None
        if anchor is not None and anchor not in self._used:
            self._used.add(anchor)
            for group in self.comments.detached.get(anchor, []):
                for comment in group:
                    out.append(pad + comment)
                out.append("")
            for comment in self.comments.leading.get(anchor, []):
                out.append(pad + comment)
            trail = self.comments.trailing.get(anchor)
        rendered = pad + text
        if trail:
            rendered += "  " + trail
        out.append(rendered.rstrip(" "))

    def _import_text(self, item: Import) -> str:
        text = "import " + ".".join(item.path)
        if item.alias:
            text += f" as {item.alias}"
        if item.exposing is not None:
            names = sorted(
                (name for name, _span in item.exposing),
                key=lambda name: (0 if name[:1].isupper() else 1, name),
            )
            text += " exposing " + ", ".join(names)
        return text

    def _decl(self, decl: object, indent: int) -> list[Line]:
        if isinstance(decl, FunctionDecl):
            return self._function(decl, indent)
        if isinstance(decl, RecordDecl):
            return self._record(decl, indent)
        if isinstance(decl, ChoiceDecl):
            return self._choice(decl, indent)
        if isinstance(decl, InterfaceDecl):
            return self._interface(decl, indent)
        if isinstance(decl, ImplementsDecl):
            return self._implements(decl, indent)
        if isinstance(decl, ConstDecl):
            prefix = (
                f"{'public ' if decl.public else ''}let {decl.name}: {self._type_flat(decl.ty)} = "
            )
            return self._place(indent, decl.span.start_line, prefix, decl.expr)
        if isinstance(decl, ForeignDecl):
            return self._foreign(decl, indent)
        if isinstance(decl, TestDecl):
            return self._test(decl, indent)
        raise TypeError(type(decl).__name__)

    def _function(self, decl: FunctionDecl, indent: int) -> list[Line]:
        pub = "public " if decl.public else ""
        lines = self._header(pub, decl.sig, indent, decl.span.start_line)
        lines.extend(self._contracts(decl.sig, indent))
        lines.append(Line(indent, "", kind="do"))
        lines.extend(self._block(decl.body, indent + 2))
        lines.append(Line(indent, "", kind="end"))
        return lines

    def _header(self, pub: str, sig: FunctionSig, indent: int, anchor: int | None) -> list[Line]:
        params = ", ".join(self._param_flat(param) for param in sig.params)
        ret = self._type_flat(sig.ret)
        tp = self._tp_suffix(sig.type_params)
        text = f"{pub}function {sig.name}{tp}({params}) returns {ret}"
        if indent + len(text) <= WIDTH or not sig.params:
            return [Line(indent, text, anchor)]
        lines = [Line(indent, f"{pub}function {sig.name}{tp}(", anchor)]
        for param in sig.params:
            lines.append(Line(indent + 2, self._param_flat(param) + ","))
        lines.append(Line(indent, f") returns {ret}"))
        return lines

    def _contracts(self, sig: FunctionSig, indent: int) -> list[Line]:
        lines: list[Line] = []
        if sig.effects:
            names = ", ".join(name for name, _span in sig.effects)
            anchor = sig.effects[0][1].start_line
            lines.append(Line(indent + 2, f"uses {names}", anchor))
        for contract in sig.contracts:
            prefix = contract.kind + " "
            placed = self._place(indent + 2, contract.span.start_line, prefix, contract.expr)
            lines.extend(placed)
        return lines

    def _record(self, decl: RecordDecl, indent: int) -> list[Line]:
        pub = "public " if decl.public else ""
        lines = self._named_type_header(
            f"{pub}record {decl.name}", decl.type_params, indent, decl.span.start_line
        )
        for field_decl in decl.fields:
            lines.append(
                Line(
                    indent + 2,
                    f"{field_decl.name}: {self._type_flat(field_decl.ty)}",
                    field_decl.span.start_line,
                )
            )
        for invariant in decl.invariants:
            lines.extend(
                self._place(indent + 2, invariant.span.start_line, "invariant ", invariant)
            )
        lines.append(Line(indent, "", kind="end"))
        return lines

    def _choice(self, decl: ChoiceDecl, indent: int) -> list[Line]:
        pub = "public " if decl.public else ""
        lines = self._named_type_header(
            f"{pub}choice {decl.name}", decl.type_params, indent, decl.span.start_line
        )
        for case in decl.cases:
            lines.extend(self._case(case.name, case.params, indent + 2, case.span.start_line))
        lines.append(Line(indent, "", kind="end"))
        return lines

    def _case(self, name: str, params: list[Param], indent: int, anchor: int) -> list[Line]:
        if not params:
            return [Line(indent, f"case {name}", anchor)]
        flat = ", ".join(self._param_flat(param) for param in params)
        text = f"case {name}({flat})"
        if indent + len(text) <= WIDTH:
            return [Line(indent, text, anchor)]
        lines = [Line(indent, f"case {name}(", anchor)]
        for param in params:
            lines.append(Line(indent + 2, self._param_flat(param) + ","))
        lines.append(Line(indent, ")"))
        return lines

    def _interface(self, decl: InterfaceDecl, indent: int) -> list[Line]:
        pub = "public " if decl.public else ""
        lines = self._named_type_header(
            f"{pub}interface {decl.name}", decl.type_params, indent, decl.span.start_line
        )
        for header in decl.headers:
            lines.extend(self._header("", header, indent + 2, header.span.start_line))
            lines.extend(self._contracts(header, indent + 2))
        lines.append(Line(indent, "", kind="end"))
        return lines

    def _implements(self, decl: ImplementsDecl, indent: int) -> list[Line]:
        lines = [
            Line(indent, f"implements {self._type_flat(decl.interface)}", decl.span.start_line)
        ]
        for function in decl.functions:
            lines.extend(self._function(function, indent + 2))
        lines.append(Line(indent, "", kind="end"))
        return lines

    def _foreign(self, decl: ForeignDecl, indent: int) -> list[Line]:
        pub = "public " if decl.public else ""
        literal = _string_lexeme(self.source, decl.span.start)
        lines = self._header("", decl.sig, indent, None)
        if lines and lines[0].kind == "text":
            lines[0].text = f"{pub}foreign {literal} " + lines[0].text
            lines[0].anchor = decl.span.start_line
        lines.extend(self._contracts(decl.sig, indent))
        return lines

    def _test(self, decl: TestDecl, indent: int) -> list[Line]:
        name = _string_lexeme(self.source, decl.span.start)
        if decl.property_params:
            params = ", ".join(self._param_flat(param) for param in decl.property_params)
            header = f"test {name} for all {params}"
        else:
            header = f"test {name}"
        lines = [Line(indent, header, decl.span.start_line)]
        lines.append(Line(indent, "", kind="do"))
        lines.extend(self._block(decl.body, indent + 2))
        lines.append(Line(indent, "", kind="end"))
        return lines

    def _named_type_header(
        self, intro: str, params: list[TypeParam], indent: int, anchor: int
    ) -> list[Line]:
        suffix = self._tp_suffix(params)
        if not params or indent + len(intro) + len(suffix) <= WIDTH:
            return [Line(indent, intro + suffix, anchor)]
        lines = [Line(indent, intro + "[", anchor)]
        for param in params:
            lines.append(Line(indent + 2, self._type_param_flat(param) + ","))
        lines.append(Line(indent, "]"))
        return lines

    def _block(self, block: Block, indent: int) -> list[Line]:
        lines: list[Line] = []
        for stmt in block.stmts:
            lines.extend(self._stmt(stmt, indent))
        return lines

    def _stmt(self, stmt: object, indent: int) -> list[Line]:
        if isinstance(stmt, LetStmt):
            word = "var" if stmt.mutable else "let"
            name = "_" if stmt.discard else stmt.name
            ty = f": {self._type_flat(stmt.ty)}" if stmt.ty is not None else ""
            return self._place(indent, stmt.span.start_line, f"{word} {name}{ty} = ", stmt.expr)
        if isinstance(stmt, SetStmt):
            return self._place(
                indent, stmt.span.start_line, f"set {'.'.join(stmt.place)} = ", stmt.expr
            )
        if isinstance(stmt, ReturnStmt):
            if stmt.expr is None:
                return [Line(indent, "return", stmt.span.start_line)]
            return self._place(indent, stmt.span.start_line, "return ", stmt.expr)
        if isinstance(stmt, FailStmt):
            return self._place(indent, stmt.span.start_line, "fail ", stmt.expr)
        if isinstance(stmt, ExpectStmt):
            return self._place(indent, stmt.span.start_line, "expect ", stmt.expr)
        if isinstance(stmt, BreakStmt):
            return [Line(indent, "break", stmt.span.start_line)]
        if isinstance(stmt, ContinueStmt):
            return [Line(indent, "continue", stmt.span.start_line)]
        if isinstance(stmt, IfStmt):
            return self._if(stmt, indent)
        if isinstance(stmt, MatchStmt):
            return self._match(stmt, indent)
        if isinstance(stmt, WhileStmt):
            lines = self._place(indent, stmt.span.start_line, "while ", stmt.cond)
            lines.append(Line(indent, "", kind="do"))
            lines.extend(self._block(stmt.body, indent + 2))
            lines.append(Line(indent, "", kind="end"))
            return lines
        if isinstance(stmt, ForStmt):
            lines = self._place(indent, stmt.span.start_line, f"for {stmt.name} in ", stmt.expr)
            lines.append(Line(indent, "", kind="do"))
            lines.extend(self._block(stmt.body, indent + 2))
            lines.append(Line(indent, "", kind="end"))
            return lines
        if isinstance(stmt, UsingStmt):
            lines = self._place(indent, stmt.span.start_line, f"using {stmt.name} = ", stmt.expr)
            lines.append(Line(indent, "", kind="do"))
            lines.extend(self._block(stmt.body, indent + 2))
            lines.append(Line(indent, "", kind="end"))
            return lines
        if isinstance(stmt, ExprStmt):
            return self._place(indent, stmt.span.start_line, "", stmt.expr)
        raise TypeError(type(stmt).__name__)

    def _if(self, stmt: IfStmt, indent: int) -> list[Line]:
        lines: list[Line] = []
        for index, arm in enumerate(stmt.arms):
            keyword = "if" if index == 0 else "elseif"
            anchor = stmt.span.start_line if index == 0 else arm.cond.span.start_line
            placed = self._place(indent, anchor, f"{keyword} ", arm.cond)
            _suffix(placed, " then")
            lines.extend(placed)
            lines.extend(self._block(arm.block, indent + 2))
        if stmt.else_block is not None:
            lines.append(Line(indent, "", kind="else"))
            lines.extend(self._block(stmt.else_block, indent + 2))
        lines.append(Line(indent, "", kind="end"))
        return lines

    def _match(self, stmt: MatchStmt, indent: int) -> list[Line]:
        lines = self._place(indent, stmt.span.start_line, "match ", stmt.expr)
        for arm in stmt.arms:
            pattern = self._pattern(arm.pattern)
            if arm.guard is None:
                lines.append(Line(indent + 2, f"case {pattern} then", arm.pattern.span.start_line))
            else:
                placed = self._place(
                    indent + 2, arm.pattern.span.start_line, f"case {pattern} if ", arm.guard
                )
                _suffix(placed, " then")
                lines.extend(placed)
            lines.extend(self._block(arm.block, indent + 4))
        lines.append(Line(indent, "", kind="end"))
        return lines

    def _place(self, indent: int, anchor: int, prefix: str, expr: Expr) -> list[Line]:
        budget = max(WIDTH - indent - len(prefix), 0)
        doc = self._render(expr, indent, budget)
        if doc and doc[0].kind == "text":
            doc[0].text = prefix + doc[0].text
            doc[0].indent = indent
            doc[0].anchor = anchor
        return doc

    def _pattern(self, pattern: Pattern) -> str:
        if isinstance(pattern, WildPat):
            return "_"
        if isinstance(pattern, BindPat):
            return pattern.name
        if isinstance(pattern, LitPat):
            return self._slice(pattern.span)
        head = ".".join([*pattern.path, pattern.name])
        if pattern.fields is None:
            return head
        inner = ", ".join(self._pattern(field) for field in pattern.fields)
        return f"{head}({inner})"

    def _slice(self, span: Span) -> str:
        return self.source[span.start : span.end]

    def _param_flat(self, param: Param) -> str:
        return f"{param.name}: {self._type_flat(param.ty)}"

    def _type_param_flat(self, param: TypeParam) -> str:
        if not param.constraints:
            return param.name
        constraints = " and ".join(self._type_flat(item) for item in param.constraints)
        return f"{param.name}: {constraints}"

    def _tp_suffix(self, params: list[TypeParam]) -> str:
        if not params:
            return ""
        return "[" + ", ".join(self._type_param_flat(param) for param in params) + "]"

    def _type_flat(self, ty: TypeExpr) -> str:
        if ty.kind == "function":
            params = ", ".join(self._type_flat(param) for param in ty.params)
            assert ty.ret is not None
            return f"function({params}) returns {self._type_flat(ty.ret)}"
        prefix = ".".join([*ty.path, ty.name])
        if not ty.args:
            return prefix
        args = ", ".join(self._type_flat(arg) for arg in ty.args)
        return f"{prefix}[{args}]"

    def _render(self, expr: Expr, line_indent: int, budget: int) -> list[Line]:
        flat = self._flat(expr)
        if flat is not None and len(flat) <= budget:
            return [Line(line_indent, flat)]
        return self._broken(expr, line_indent, budget)

    def _render_child(
        self, expr: Expr, line_indent: int, budget: int, parent_op: str, side: str
    ) -> list[Line]:
        if _needs_paren(expr, parent_op, side):
            return _wrap(self._render(expr, line_indent, max(budget - 2, 0)))
        return self._render(expr, line_indent, budget)

    def _flat(self, expr: Expr, parent_op: str | None = None, side: str = "left") -> str | None:
        if _needs_paren(expr, parent_op, side):
            inner = self._flat(expr)
            if inner is None:
                return None
            return f"({inner})"
        return self._flat_node(expr)

    def _flat_node(self, expr: Expr) -> str | None:
        if isinstance(expr, LiteralExpr):
            if expr.kind == "bool":
                return "true" if expr.value else "false"
            return self._slice(expr.span)
        if isinstance(expr, NameExpr):
            return expr.name
        if isinstance(expr, ResultExpr):
            return "result"
        if isinstance(expr, GroupExpr):
            inner = self._flat(expr.expr)
            if inner is None:
                return None
            return f"({inner})"
        if isinstance(expr, UnaryExpr):
            inner = self._flat(expr.expr, _PREFIX_KEYS[expr.op], "right")
            if inner is None:
                return None
            if expr.op == "-":
                return "-" + inner
            return f"{expr.op} {inner}"
        if isinstance(expr, BinaryExpr):
            left = self._flat(expr.left, expr.op, "left")
            right = self._flat(expr.right, expr.op, "right")
            if left is None or right is None:
                return None
            return f"{left} {expr.op} {right}"
        if isinstance(expr, FieldExpr):
            recv = self._flat(expr.recv, "field", "left")
            if recv is None:
                return None
            return f"{recv}.{expr.name}"
        if isinstance(expr, CallExpr):
            callee = self._flat(expr.func, "call", "left")
            if callee is None:
                return None
            args: list[str] = []
            for arg in expr.args:
                flat = self._flat_arg(arg)
                if flat is None:
                    return None
                args.append(flat)
            return f"{callee}({', '.join(args)})"
        if isinstance(expr, ListExpr):
            items: list[str] = []
            for element in expr.elements:
                flat = self._flat(element)
                if flat is None:
                    return None
                items.append(flat)
            return "[" + ", ".join(items) + "]"
        if isinstance(expr, MapExpr):
            items = []
            for key, value in expr.entries:
                left = self._flat(key)
                right = self._flat(value)
                if left is None or right is None:
                    return None
                items.append(f"{left}: {right}")
            return "{" + ", ".join(items) + "}"
        if isinstance(expr, WithExpr):
            recv = self._flat(expr.recv, "with", "left")
            if recv is None:
                return None
            fields: list[str] = []
            for field_init in expr.fields:
                flat = self._flat_field(field_init)
                if flat is None:
                    return None
                fields.append(flat)
            return f"{recv} with ({', '.join(fields)})"
        if isinstance(expr, OldExpr):
            inner = self._flat(expr.expr)
            if inner is None:
                return None
            return f"old({inner})"
        if isinstance(expr, LambdaExpr):
            return None
        raise TypeError(type(expr).__name__)

    def _flat_arg(self, arg: Arg) -> str | None:
        flat = self._flat(arg.expr)
        if flat is None:
            return None
        if arg.name is None:
            return flat
        return f"{arg.name} = {flat}"

    def _flat_field(self, field_init: FieldInit) -> str | None:
        flat = self._flat(field_init.expr)
        if flat is None:
            return None
        return f"{field_init.name} = {flat}"

    def _broken(self, expr: Expr, line_indent: int, budget: int) -> list[Line]:
        if isinstance(expr, LambdaExpr):
            return self._lambda(expr, line_indent)
        if isinstance(expr, CallExpr):
            return self._call(expr, line_indent, budget)
        if isinstance(expr, ListExpr):
            return self._list(expr, line_indent)
        if isinstance(expr, MapExpr):
            return self._map(expr, line_indent)
        if isinstance(expr, WithExpr):
            return self._with(expr, line_indent, budget)
        if isinstance(expr, GroupExpr):
            return _wrap(self._render(expr.expr, line_indent, max(budget - 2, 0)))
        if isinstance(expr, OldExpr):
            inner = self._render(expr.expr, line_indent, max(budget - 4, 0))
            if inner and inner[0].kind == "text":
                inner[0].text = "old(" + inner[0].text
            _suffix(inner, ")")
            return inner
        if isinstance(expr, UnaryExpr):
            prefix = "-" if expr.op == "-" else expr.op + " "
            inner = self._render_child(
                expr.expr, line_indent, max(budget - len(prefix), 0), _PREFIX_KEYS[expr.op], "right"
            )
            if inner and inner[0].kind == "text":
                inner[0].text = prefix + inner[0].text
            return inner
        if isinstance(expr, BinaryExpr):
            return self._binary(expr, line_indent, budget)
        if isinstance(expr, FieldExpr):
            recv = self._render_child(
                expr.recv, line_indent, max(budget - len(expr.name) - 1, 0), "field", "left"
            )
            _suffix(recv, "." + expr.name)
            return recv
        flat = self._flat(expr)
        return [Line(line_indent, flat if flat is not None else self._slice(expr.span))]

    def _binary(self, expr: BinaryExpr, line_indent: int, budget: int) -> list[Line]:
        left = self._render_child(expr.left, line_indent, budget, expr.op, "left")
        op = f" {expr.op} "
        if len(left) == 1 and left[0].kind == "text":
            remain = budget - len(left[0].text) - len(op)
        else:
            last = left[-1]
            remain = WIDTH - last.indent - len(last.text) - len(op)
        right = self._render_child(expr.right, line_indent, max(remain, 0), expr.op, "right")
        if right and right[0].kind == "text":
            left[-1].text += op + right[0].text
            return left + right[1:]
        return left + right

    def _call(self, expr: CallExpr, line_indent: int, budget: int) -> list[Line]:
        callee = self._flat(expr.func, "call", "left")
        if callee is None:
            callee_doc = self._render_child(expr.func, line_indent, budget, "call", "left")
            _suffix(callee_doc, "(")
            return self._call_args(callee_doc, expr.args, line_indent)
        if not expr.args:
            return [Line(line_indent, f"{callee}()")]
        flats = [self._flat_arg(arg) for arg in expr.args]
        hole = next((index for index, item in enumerate(flats) if item is None), None)
        if (
            hole is not None
            and hole == len(flats) - 1
            and all(item is not None for item in flats[:-1])
        ):
            head = callee + "("
            ready = [item for item in flats[:-1] if item is not None]
            if ready:
                head += ", ".join(ready) + ", "
            arg_doc = self._arg_doc(expr.args[hole], line_indent, max(budget - len(head), 0))
            if (
                arg_doc
                and arg_doc[0].kind == "text"
                and len(head) + len(arg_doc[0].text) <= max(budget, len(head))
            ):
                arg_doc[0].text = head + arg_doc[0].text
                arg_doc[0].indent = line_indent
                _suffix(arg_doc, ")")
                return arg_doc
        return self._call_args([Line(line_indent, callee + "(")], expr.args, line_indent)

    def _call_args(self, lines: list[Line], args: list[Arg], line_indent: int) -> list[Line]:
        if not args:
            _suffix(lines, ")")
            return lines
        inner = line_indent + 2
        for arg in args:
            rendered = self._arg_doc(arg, inner, WIDTH - inner)
            _suffix(rendered, ",")
            lines.extend(rendered)
        lines.append(Line(line_indent, ")"))
        return lines

    def _arg_doc(self, arg: Arg, line_indent: int, budget: int) -> list[Line]:
        prefix = "" if arg.name is None else f"{arg.name} = "
        doc = self._render(arg.expr, line_indent, max(budget - len(prefix), 0))
        if doc and doc[0].kind == "text":
            doc[0].text = prefix + doc[0].text
            doc[0].indent = line_indent
        return doc

    def _list(self, expr: ListExpr, line_indent: int) -> list[Line]:
        if not expr.elements:
            return [Line(line_indent, "[]")]
        lines = [Line(line_indent, "[")]
        inner = line_indent + 2
        for element in expr.elements:
            rendered = self._render(element, inner, WIDTH - inner)
            _suffix(rendered, ",")
            lines.extend(rendered)
        lines.append(Line(line_indent, "]"))
        return lines

    def _map(self, expr: MapExpr, line_indent: int) -> list[Line]:
        if not expr.entries:
            return [Line(line_indent, "{}")]
        lines = [Line(line_indent, "{")]
        inner = line_indent + 2
        for key, value in expr.entries:
            left = self._flat(key)
            right = self._flat(value)
            if left is not None and right is not None and len(f"{left}: {right}") <= WIDTH - inner:
                lines.append(Line(inner, f"{left}: {right},"))
                continue
            if left is not None:
                prefix = left + ": "
                rendered = self._render(value, inner, max(WIDTH - inner - len(prefix), 0))
                if rendered and rendered[0].kind == "text":
                    rendered[0].text = prefix + rendered[0].text
                    rendered[0].indent = inner
                _suffix(rendered, ",")
                lines.extend(rendered)
                continue
            key_lines = self._render(key, inner, WIDTH - inner)
            _suffix(key_lines, ":")
            lines.extend(key_lines)
            rendered = self._render(value, inner + 2, WIDTH - (inner + 2))
            _suffix(rendered, ",")
            lines.extend(rendered)
        lines.append(Line(line_indent, "}"))
        return lines

    def _with(self, expr: WithExpr, line_indent: int, budget: int) -> list[Line]:
        recv = self._render_child(expr.recv, line_indent, budget, "with", "left")
        _suffix(recv, " with (")
        inner = line_indent + 2
        for field_init in expr.fields:
            flat = self._flat_field(field_init)
            if flat is not None and len(flat) <= WIDTH - inner:
                recv.append(Line(inner, flat + ","))
                continue
            prefix = f"{field_init.name} = "
            rendered = self._render(field_init.expr, inner, max(WIDTH - inner - len(prefix), 0))
            if rendered and rendered[0].kind == "text":
                rendered[0].text = prefix + rendered[0].text
                rendered[0].indent = inner
            _suffix(rendered, ",")
            recv.extend(rendered)
        recv.append(Line(line_indent, ")"))
        return recv

    def _lambda(self, expr: LambdaExpr, line_indent: int) -> list[Line]:
        params = ", ".join(self._param_flat(param) for param in expr.params)
        ret = self._type_flat(expr.ret)
        header = f"function ({params}) returns {ret}"
        if line_indent + len(header) <= WIDTH or not expr.params:
            lines = [Line(line_indent, header)]
        else:
            lines = [Line(line_indent, "function (")]
            for param in expr.params:
                lines.append(Line(line_indent + 2, self._param_flat(param) + ","))
            lines.append(Line(line_indent, f") returns {ret}"))
        lines.append(Line(line_indent + 2, "", kind="do"))
        body = self._render(expr.body, line_indent + 4, WIDTH - (line_indent + 4))
        lines.extend(body)
        lines.append(Line(line_indent + 2, "", kind="end"))
        return lines
