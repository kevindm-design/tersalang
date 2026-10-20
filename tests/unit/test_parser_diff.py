# SPDX-License-Identifier: Apache-2.0
"""The hand parser and the Lark grammar agree on the conformance corpus.

Lark is not the lexical oracle. Files with a lexical error are skipped.
Every other file is rebuilt from hand-lexer tokens (comments dropped, suppressed
newlines omitted). A `do` that starts on a later source line still gets a newline
in that text, because own-line `do` is a source-line rule and parentheses emit
no `NL` token.
"""

from __future__ import annotations

from pathlib import Path

from lark import Lark, Token, Tree
from lark.exceptions import UnexpectedInput

from tersalang.ast import (
    BreakStmt,
    ChoiceDecl,
    ConstDecl,
    ContinueStmt,
    ExpectStmt,
    ExprStmt,
    FailStmt,
    ForeignDecl,
    ForStmt,
    FunctionDecl,
    IfStmt,
    ImplementsDecl,
    InterfaceDecl,
    LetStmt,
    MatchStmt,
    Module,
    RecordDecl,
    ReturnStmt,
    SetStmt,
    UsingStmt,
    WhileStmt,
)
from tersalang.lexer import Token as LexerToken
from tersalang.lexer import lex_text
from tersalang.parser import parse_module
from tersalang.source import decode_source_bytes

ROOT = Path(__file__).resolve().parents[2]
GRAMMAR = (ROOT / "spec" / "tersa.lark").read_text(encoding="utf-8")
PROGRAMS = sorted((ROOT / "conformance").rglob("*.tersa")) + sorted(
    (ROOT / "examples").glob("*.tersa")
)


def _reconstruct(text: str, tokens: list[LexerToken]) -> str:
    parts: list[str] = []
    previous_end: int | None = None
    saw_nl = False
    for token in tokens:
        if token.kind == "eof":
            continue
        if token.kind == "nl":
            parts.append("\n")
            saw_nl = True
            continue
        if (
            token.kind == "do"
            and not saw_nl
            and previous_end is not None
            and token.span.start_line > previous_end
        ):
            parts.append("\n")
        parts.append(text[token.span.start : token.span.end])
        parts.append(" ")
        previous_end = token.span.end_line
        saw_nl = False
    return "".join(parts)


def _syntax_ok(module: Module | None, codes: list[str]) -> bool:
    if module is None:
        return False
    return not any(code.startswith("E1") for code in codes)


def _block_ast(stmts: list[object]) -> tuple[object, ...]:
    return tuple(_stmt_ast(stmt) for stmt in stmts)


def _stmt_ast(stmt: object) -> object:
    if isinstance(stmt, LetStmt):
        return ("var" if stmt.mutable else "let",)
    if isinstance(stmt, SetStmt):
        return ("set",)
    if isinstance(stmt, ReturnStmt):
        return ("return",)
    if isinstance(stmt, FailStmt):
        return ("fail",)
    if isinstance(stmt, ExpectStmt):
        return ("expect",)
    if isinstance(stmt, BreakStmt):
        return ("break",)
    if isinstance(stmt, ContinueStmt):
        return ("continue",)
    if isinstance(stmt, ExprStmt):
        return ("expr",)
    if isinstance(stmt, IfStmt):
        arms = tuple(_block_ast(arm.block.stmts) for arm in stmt.arms)
        else_block = _block_ast(stmt.else_block.stmts) if stmt.else_block is not None else None
        return ("if", arms, else_block)
    if isinstance(stmt, MatchStmt):
        return ("match", tuple(_block_ast(arm.block.stmts) for arm in stmt.arms))
    if isinstance(stmt, WhileStmt):
        return ("while", _block_ast(stmt.body.stmts))
    if isinstance(stmt, ForStmt):
        return ("for", _block_ast(stmt.body.stmts))
    if isinstance(stmt, UsingStmt):
        return ("using", _block_ast(stmt.body.stmts))
    raise AssertionError(type(stmt).__name__)


def _decl_ast(decl: object) -> object:
    from tersalang.ast import TestDecl

    if isinstance(decl, FunctionDecl):
        return ("function", decl.sig.name, _block_ast(decl.body.stmts))
    if isinstance(decl, RecordDecl):
        return ("record", decl.name, tuple(field.name for field in decl.fields))
    if isinstance(decl, ChoiceDecl):
        return ("choice", decl.name, tuple(case.name for case in decl.cases))
    if isinstance(decl, InterfaceDecl):
        return ("interface", decl.name, tuple(header.name for header in decl.headers))
    if isinstance(decl, ImplementsDecl):
        functions = tuple(
            ("function", item.sig.name, _block_ast(item.body.stmts)) for item in decl.functions
        )
        return ("implements", decl.interface.name, functions)
    if isinstance(decl, ConstDecl):
        return ("const", decl.name)
    if isinstance(decl, ForeignDecl):
        return ("foreign", decl.sig.name)
    if isinstance(decl, TestDecl):
        return ("test", decl.name, _block_ast(decl.body.stmts))
    raise AssertionError(type(decl).__name__)


def _outline_ast(module: Module) -> object:
    imports = tuple(
        (
            tuple(item.path),
            item.alias,
            None if item.exposing is None else tuple(name for name, _span in item.exposing),
        )
        for item in module.imports
    )
    return (tuple(module.path), imports, tuple(_decl_ast(decl) for decl in module.decls))


def _trees(node: Tree, name: str) -> list[Tree]:
    return [child for child in node.children if isinstance(child, Tree) and child.data == name]


def _token(node: Tree, kind: str) -> str | None:
    for child in node.children:
        if isinstance(child, Token) and child.type == kind:
            return str(child)
    return None


def _lowers(node: Tree) -> tuple[str, ...]:
    return tuple(
        str(child) for child in node.children if isinstance(child, Token) and child.type == "LOWER"
    )


def _text_value(raw: str) -> str:
    body = raw[1:-1]
    pieces: list[str] = []
    index = 0
    mapping = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "{": "{", "}": "}"}
    while index < len(body):
        if body[index] == "\\" and index + 1 < len(body) and body[index + 1] in mapping:
            pieces.append(mapping[body[index + 1]])
            index += 2
            continue
        pieces.append(body[index])
        index += 1
    return "".join(pieces)


def _block_lark(node: Tree) -> tuple[object, ...]:
    return tuple(_stmt_lark(child) for child in node.children if isinstance(child, Tree))


def _stmt_lark(node: Tree) -> object:
    kind = str(node.data)
    simple = {
        "let_stmt": "let",
        "var_stmt": "var",
        "set_stmt": "set",
        "return_stmt": "return",
        "fail_stmt": "fail",
        "expect_stmt": "expect",
        "break_stmt": "break",
        "continue_stmt": "continue",
        "expr_stmt": "expr",
    }
    if kind in simple:
        return (simple[kind],)
    if kind == "if_stmt":
        arms: list[object] = []
        else_block = None
        seen_then = False
        for child in node.children:
            if not isinstance(child, Tree):
                continue
            if child.data == "block" and not seen_then:
                arms.append(_block_lark(child))
                seen_then = True
            elif child.data == "elseif_arm":
                arms.append(_block_lark(_trees(child, "block")[0]))
            elif child.data == "else_arm":
                else_block = _block_lark(_trees(child, "block")[0])
        return ("if", tuple(arms), else_block)
    if kind == "match_stmt":
        return (
            "match",
            tuple(_block_lark(_trees(arm, "block")[0]) for arm in _trees(node, "match_arm")),
        )
    if kind in {"while_stmt", "for_stmt", "using_stmt"}:
        return (kind.removesuffix("_stmt"), _block_lark(_trees(node, "block")[0]))
    raise AssertionError(kind)


def _function_lark(node: Tree) -> object:
    header = _trees(node, "header")[0]
    name = _token(header, "LOWER")
    return ("function", name, _block_lark(_trees(node, "block")[0]))


def _decl_lark(top: Tree) -> object:
    node = next(child for child in top.children if isinstance(child, Tree))
    kind = str(node.data)
    if kind == "function_decl":
        return _function_lark(node)
    if kind == "record_decl":
        fields = tuple(_token(field, "LOWER") for field in _trees(node, "record_field"))
        return ("record", _token(node, "UPPER"), fields)
    if kind == "choice_decl":
        cases = tuple(_token(case, "UPPER") for case in _trees(node, "choice_case"))
        return ("choice", _token(node, "UPPER"), cases)
    if kind == "interface_decl":
        names = tuple(_token(header, "LOWER") for header in _trees(node, "header"))
        return ("interface", _token(node, "UPPER"), names)
    if kind == "implements_decl":
        functions = tuple(_function_lark(item) for item in _trees(node, "function_decl"))
        return ("implements", _token(node, "UPPER"), functions)
    if kind == "const_decl":
        return ("const", _token(node, "LOWER"))
    if kind == "foreign_decl":
        return ("foreign", _token(_trees(node, "header")[0], "LOWER"))
    if kind == "test_decl":
        raw = _token(node, "TEXT")
        assert raw is not None
        return ("test", _text_value(raw), _block_lark(_trees(node, "block")[0]))
    raise AssertionError(kind)


def _import_lark(node: Tree) -> object:
    path = _lowers(_trees(node, "module_path")[0])
    alias = None
    names: list[str] = []
    for child in node.children:
        if isinstance(child, Token) and child.type == "LOWER":
            alias = str(child)
        elif isinstance(child, Tree) and child.data == "name":
            token = next(item for item in child.children if isinstance(item, Token))
            names.append(str(token))
    exposing = tuple(names) if names else None
    return (path, alias, exposing)


def _outline_lark(tree: Tree) -> object:
    module = _trees(tree, "module_decl")[0]
    path = _lowers(_trees(module, "module_path")[0])
    imports = []
    decls = []
    for child in tree.children:
        if not isinstance(child, Tree):
            continue
        if child.data == "import_decl":
            imports.append(_import_lark(child))
        elif child.data == "top_decl":
            decls.append(_decl_lark(child))
    return (path, tuple(imports), tuple(decls))


def test_hand_parser_and_lark_agree_on_the_corpus() -> None:
    parser = Lark(GRAMMAR, parser="lalr", start="file")
    failures: list[str] = []
    compared = 0
    for path in PROGRAMS:
        raw = path.read_bytes()
        text = decode_source_bytes(raw)
        if text.startswith("\ufeff"):
            text = text.removeprefix("\ufeff")
        source, tokens, diagnostics = lex_text(path.name, text)
        codes = [item.code for item in diagnostics if item.severity == "error"]
        if any(code.startswith("E0") for code in codes):
            continue
        module = parse_module(source, tokens, diagnostics)
        codes = [item.code for item in diagnostics if item.severity == "error"]
        hand_ok = _syntax_ok(module, codes)
        rendered = _reconstruct(text, tokens)
        try:
            tree = parser.parse(rendered)
            lark_ok = True
        except UnexpectedInput as exc:
            tree = None
            lark_ok = False
            detail = str(exc).splitlines()[0]
        else:
            detail = ""
        compared += 1
        relative = path.relative_to(ROOT).as_posix()
        if hand_ok != lark_ok:
            failures.append(f"{relative}: hand={hand_ok} lark={lark_ok} {detail}")
            continue
        if hand_ok and lark_ok and module is not None and isinstance(tree, Tree):
            hand_outline = _outline_ast(module)
            lark_outline = _outline_lark(tree)
            if hand_outline != lark_outline:
                failures.append(f"{relative}:\n  hand={hand_outline!r}\n  lark={lark_outline!r}")
    assert compared > 0
    assert failures == []
