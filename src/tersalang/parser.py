# SPDX-License-Identifier: Apache-2.0
"""Hand-written recursive-descent parser. The grammar is spec/tersa.ebnf."""

from __future__ import annotations

from tersalang.ast import (
    Arg,
    BinaryExpr,
    BindPat,
    Block,
    BreakStmt,
    CallExpr,
    ChoiceCase,
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
    FieldInit,
    ForeignDecl,
    ForStmt,
    FunctionDecl,
    FunctionSig,
    GroupExpr,
    IfArm,
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
    MatchArm,
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
from tersalang.diagnostics import Diagnostic, Fix
from tersalang.lexer import KEYWORDS, Token
from tersalang.source import Source, Span, merge_spans

STOP_BLOCK = frozenset({"end", "elseif", "else", "case", "eof"})


class Parser:
    """Builds the AST from the lexer's tokens and appends syntax diagnostics.

    Most errors are `E1000`. A declaration that fails to parse is skipped and
    parsing continues with the next one.
    """

    def __init__(self, source: Source, tokens: list[Token], diagnostics: list[Diagnostic]) -> None:
        self.source = source
        self.tokens = tokens
        self.diagnostics = diagnostics
        self.pos = 0

    def parse_module(self) -> Module | None:
        """The whole file; None only when the `module` header is missing or malformed."""
        self._skip_nl()
        if not self._at("module"):
            self._error("E1000", "a file must start with `module`", self._peek().span)
            return None
        start = self._peek().span
        self._advance()
        path = self._module_path()
        if path is None:
            return None
        self._expect("nl", "expected a line break after the module name")
        imports: list[Import] = []
        decls: list[object] = []
        while not self._at("eof"):
            if self._at("nl"):
                self._advance()
                continue
            if self._at("import"):
                imported = self._import()
                if imported is None and not self._at("eof"):
                    self._advance()
                elif imported is not None:
                    imports.append(imported)
                continue
            decl = self._top_decl()
            if decl is None:
                if not self._at("eof"):
                    self._advance()
                continue
            decls.append(decl)
        end = self._peek().span
        return Module(merge_spans(start, end), path, imports, decls)  # type: ignore[arg-type]

    def parse_expression_only(self) -> Expr | None:
        """A single expression that must be the whole input, such as a doc `Example:` line."""
        self._skip_nl()
        if self._at("eof"):
            self._error("E1000", "expected an expression", self._peek().span)
            return None
        expr = self._expression()
        self._skip_nl()
        if not self._at("eof"):
            self._error("E1000", "unexpected tokens after the expression", self._peek().span)
        return expr

    def _top_decl(self) -> object | None:
        public = False
        doc = self._peek().doc
        start = self._peek().span
        if self._at("public"):
            public = True
            self._advance()
            doc = doc or self._peek().doc
        if self._at("function"):
            sig = self._header(doc)
            if sig is None:
                return None
            body = self._do_block()
            if body is None:
                return None
            self._expect("nl", "expected a line break after `end`")
            return FunctionDecl(merge_spans(start, body.span), public, sig, body, doc)
        if self._at("record"):
            return self._record(public, doc, start)
        if self._at("choice"):
            return self._choice(public, doc, start)
        if self._at("interface"):
            return self._interface(public, doc, start)
        if self._at("let"):
            return self._const(public, doc, start)
        if self._at("foreign"):
            return self._foreign(public, doc, start)
        if public:
            self._error("E1000", "`public` cannot mark this declaration", start)
            return None
        if self._at("implements"):
            return self._implements(start)
        if self._at("test"):
            return self._test(start)
        self._error("E1000", "expected a declaration", self._peek().span)
        self._sync_decl()
        return None

    def _import(self) -> Import | None:
        start = self._peek().span
        self._advance()
        path = self._module_path()
        if path is None:
            return None
        alias = None
        if self._at("as"):
            self._advance()
            name = self._expect("lower", "expected a lower name after `as`")
            if name is None:
                return None
            alias = name.text
        exposing = None
        if self._at("exposing"):
            self._advance()
            exposing = []
            item = self._name_token()
            if item is None:
                return None
            exposing.append((item.text, item.span))
            while self._at(","):
                self._advance()
                item = self._name_token()
                if item is None:
                    return None
                exposing.append((item.text, item.span))
        end = self._peek().span
        self._expect("nl", "expected a line break after the import")
        return Import(merge_spans(start, end), path, alias, exposing)

    def _header(self, doc: str | None) -> FunctionSig | None:
        start = self._peek().span
        self._expect("function", "expected `function`")
        name_tok = self._expect("lower", "expected a function name")
        if name_tok is None:
            return None
        type_params = self._type_params()
        self._expect("(", "expected `(`")
        params = self._params()
        self._expect(")", "expected `)`")
        self._expect("returns", "expected `returns`")
        ret = self._type()
        if ret is None:
            return None
        if not self._break_or_do("expected a line break after the return type"):
            return None
        effects: list[tuple[str, Span]] = []
        if self._at("uses"):
            self._advance()
            effect = self._expect("upper", "expected an effect name")
            if effect is None:
                return None
            effects.append((effect.text, effect.span))
            while self._at(","):
                self._advance()
                effect = self._expect("upper", "expected an effect name")
                if effect is None:
                    return None
                effects.append((effect.text, effect.span))
            if not self._break_or_do("expected a line break after `uses`"):
                return None
        contracts: list[Contract] = []
        while self._at("requires") or self._at("ensures"):
            kind = self._advance().text
            expr = self._expression()
            if expr is None:
                return None
            contracts.append(Contract(expr.span, kind, expr, self.source.slice(expr.span)))
            if not self._break_or_do("expected a line break after the contract"):
                return None
        return FunctionSig(
            merge_spans(start, ret.span),
            name_tok.text,
            type_params,
            params,
            ret,
            effects,
            contracts,
            doc,
        )

    def _record(self, public: bool, doc: str | None, start: Span) -> RecordDecl | None:
        self._advance()
        name = self._expect("upper", "expected a record name")
        if name is None:
            return None
        type_params = self._type_params()
        self._expect("nl", "expected a line break after the record name")
        fields: list[Param] = []
        while self._at("lower") or self._keyword_before(":"):
            field_name = (
                self._advance()
                if self._at("lower")
                else self._keyword_as_name("expected a field name")
            )
            if field_name is None:
                return None
            self._expect(":", "expected `:`")
            ty = self._type()
            if ty is None:
                return None
            fields.append(Param(merge_spans(field_name.span, ty.span), field_name.text, ty))
            self._expect("nl", "expected a line break after the field")
        invariants: list[Expr] = []
        while self._at("invariant"):
            self._advance()
            expr = self._expression()
            if expr is None:
                return None
            invariants.append(expr)
            self._expect("nl", "expected a line break after the invariant")
        end = self._expect("end", "expected `end`")
        if end is None:
            return None
        self._expect("nl", "expected a line break after `end`")
        return RecordDecl(
            merge_spans(start, end.span),
            public,
            name.text,
            type_params,
            fields,
            invariants,
            doc,
            [self.source.slice(item.span) for item in invariants],
        )

    def _choice(self, public: bool, doc: str | None, start: Span) -> ChoiceDecl | None:
        self._advance()
        name = self._expect("upper", "expected a choice name")
        if name is None:
            return None
        type_params = self._type_params()
        self._expect("nl", "expected a line break after the choice name")
        cases: list[ChoiceCase] = []
        while self._at("case"):
            case_start = self._advance().span
            case_name = self._expect("upper", "expected a case name")
            if case_name is None:
                return None
            params: list[Param] = []
            end_span = case_name.span
            if self._at("("):
                self._advance()
                params = self._params()
                closing = self._expect(")", "expected `)`")
                if closing is None:
                    return None
                end_span = closing.span
            cases.append(ChoiceCase(merge_spans(case_start, end_span), case_name.text, params))
            self._expect("nl", "expected a line break after the case")
        end = self._expect("end", "expected `end`")
        if end is None:
            return None
        self._expect("nl", "expected a line break after `end`")
        return ChoiceDecl(merge_spans(start, end.span), public, name.text, type_params, cases, doc)

    def _interface(self, public: bool, doc: str | None, start: Span) -> InterfaceDecl | None:
        self._advance()
        name = self._expect("upper", "expected an interface name")
        if name is None:
            return None
        type_params = self._type_params()
        self._expect("nl", "expected a line break after the interface name")
        headers: list[FunctionSig] = []
        while self._at("function"):
            header = self._header(self._peek().doc)
            if header is None:
                return None
            headers.append(header)
        end = self._expect("end", "expected `end`")
        if end is None:
            return None
        self._expect("nl", "expected a line break after `end`")
        return InterfaceDecl(
            merge_spans(start, end.span), public, name.text, type_params, headers, doc
        )

    def _implements(self, start: Span) -> ImplementsDecl | None:
        self._advance()
        iface = self._type()
        if iface is None:
            return None
        if iface.kind != "named" or iface.path or not iface.args:
            self._error(
                "E1000",
                "expected an interface name and its type arguments, as in "
                "`implements Comparable[Rect]`",
                iface.span,
            )
        self._expect("nl", "expected a line break after the implements header")
        functions: list[FunctionDecl] = []
        while self._at("function") or (self._at("public") and self._lookahead_is("function")):
            public = False
            doc = self._peek().doc
            fn_start = self._peek().span
            if self._at("public"):
                public = True
                self._advance()
            sig = self._header(doc)
            if sig is None:
                return None
            body = self._do_block()
            if body is None:
                return None
            self._expect("nl", "expected a line break after `end`")
            functions.append(FunctionDecl(merge_spans(fn_start, body.span), public, sig, body, doc))
        end = self._expect("end", "expected `end`")
        if end is None:
            return None
        self._expect("nl", "expected a line break after `end`")
        return ImplementsDecl(merge_spans(start, end.span), iface, functions)

    def _const(self, public: bool, doc: str | None, start: Span) -> ConstDecl | None:
        self._advance()
        name = self._expect("lower", "expected a constant name")
        if name is None:
            return None
        self._expect(":", "module constants need a type")
        ty = self._type()
        if ty is None:
            return None
        self._expect("=", "expected `=`")
        expr = self._expression()
        if expr is None:
            return None
        self._expect("nl", "expected a line break after the constant")
        return ConstDecl(merge_spans(start, expr.span), public, name.text, ty, expr, doc)

    def _foreign(self, public: bool, doc: str | None, start: Span) -> ForeignDecl | None:
        self._advance()
        target = self._expect("text", "expected a foreign target string")
        if target is None:
            return None
        sig = self._header(doc)
        if sig is None:
            return None
        return ForeignDecl(merge_spans(start, sig.span), public, str(target.value), sig, doc)

    def _test(self, start: Span) -> TestDecl | None:
        self._advance()
        name = self._expect("text", "expected a test name")
        if name is None:
            return None
        property_params = None
        if self._at("for"):
            self._advance()
            self._expect("all", "expected `all`")
            property_params = self._params()
        body = self._do_block()
        if body is None:
            return None
        self._expect("nl", "expected a line break after `end`")
        return TestDecl(merge_spans(start, body.span), str(name.value), property_params, body)

    def _do_block(self) -> Block | None:
        found = self._expect_do()
        if found is None:
            return None
        return self._block()

    def _block(self) -> Block:
        start = self._peek().span
        stmts: list[object] = []
        while not self._at_any(STOP_BLOCK):
            if self._at("nl"):
                self._advance()
                continue
            stmt = self._statement()
            if stmt is None:
                if self._at_any(STOP_BLOCK):
                    break
                if not self._at("eof"):
                    self._advance()
                continue
            stmts.append(stmt)
            if self._at("nl"):
                self._advance()
            else:
                self._error("E1000", "expected a line break after the statement", self._peek().span)
                break
        end_tok = self._expect("end", "expected `end`")
        end_span = end_tok.span if end_tok is not None else self._peek().span
        return Block(merge_spans(start, end_span), stmts)  # type: ignore[arg-type]

    def _statement(self) -> object | None:
        token = self._peek()
        if token.kind in {"let", "var"}:
            return self._let(token.kind == "var")
        if token.kind == "set":
            return self._set()
        if token.kind == "return":
            start = self._advance().span
            if self._at("nl") or self._at_any(STOP_BLOCK):
                return ReturnStmt(start, None)
            expr = self._expression()
            if expr is None:
                return None
            return ReturnStmt(merge_spans(start, expr.span), expr)
        if token.kind == "fail":
            start = self._advance().span
            expr = self._expression()
            if expr is None:
                return None
            return FailStmt(merge_spans(start, expr.span), expr)
        if token.kind == "expect":
            start = self._advance().span
            expr = self._expression()
            if expr is None:
                return None
            return ExpectStmt(merge_spans(start, expr.span), expr)
        if token.kind == "break":
            tok = self._advance()
            return BreakStmt(tok.span)
        if token.kind == "continue":
            tok = self._advance()
            return ContinueStmt(tok.span)
        if token.kind == "if":
            return self._if()
        if token.kind == "match":
            return self._match()
        if token.kind == "while":
            return self._while()
        if token.kind == "for":
            return self._for()
        if token.kind == "using":
            return self._using()
        expr = self._expression()
        if expr is None:
            return None
        return ExprStmt(expr.span, expr)

    def _let(self, mutable: bool) -> LetStmt | None:
        start = self._advance().span
        discard = False
        if self._at("wildcard"):
            self._advance()
            discard = True
            name = "_"
        else:
            name_tok = self._expect("lower", "expected a lower name")
            if name_tok is None:
                return None
            name = name_tok.text
        ty = None
        if self._at(":"):
            self._advance()
            ty = self._type()
            if ty is None:
                return None
        self._expect("=", "expected `=`")
        expr = self._expression()
        if expr is None:
            return None
        return LetStmt(merge_spans(start, expr.span), name, ty, expr, mutable, discard)

    def _set(self) -> SetStmt | None:
        start = self._advance().span
        root = self._expect("lower", "expected a name")
        if root is None:
            return None
        place = [root.text]
        while self._at("."):
            self._advance()
            field = self._expect("lower", "expected a field name")
            if field is None:
                return None
            place.append(field.text)
        self._expect("=", "expected `=`")
        expr = self._expression()
        if expr is None:
            return None
        return SetStmt(merge_spans(start, expr.span), place, expr)

    def _if(self) -> IfStmt | None:
        start = self._advance().span
        arms: list[IfArm] = []
        cond = self._expression()
        if cond is None:
            return None
        self._expect("then", "expected `then`")
        block = self._block_until()
        arms.append(IfArm(cond, block))
        while self._at("elseif"):
            self._advance()
            cond = self._expression()
            if cond is None:
                return None
            self._expect("then", "expected `then`")
            block = self._block_until()
            arms.append(IfArm(cond, block))
        else_block = None
        if self._at("else"):
            self._advance()
            else_block = self._block_until()
        end = self._expect("end", "expected `end`")
        end_span = end.span if end is not None else self._peek().span
        return IfStmt(merge_spans(start, end_span), arms, else_block)

    def _match(self) -> MatchStmt | None:
        start = self._advance().span
        expr = self._expression()
        if expr is None:
            return None
        self._expect("nl", "expected a line break after `match`")
        arms: list[MatchArm] = []
        while self._at("case"):
            self._advance()
            pattern = self._pattern()
            if pattern is None:
                return None
            guard = None
            if self._at("if"):
                self._advance()
                guard = self._expression()
                if guard is None:
                    return None
            self._expect("then", "expected `then`")
            block = self._block_until()
            arms.append(MatchArm(pattern, guard, block))
        end = self._expect("end", "expected `end`")
        end_span = end.span if end is not None else self._peek().span
        return MatchStmt(merge_spans(start, end_span), expr, arms)

    def _while(self) -> WhileStmt | None:
        start = self._advance().span
        cond = self._expression()
        if cond is None:
            return None
        body = self._do_block()
        if body is None:
            return None
        return WhileStmt(merge_spans(start, body.span), cond, body)

    def _for(self) -> ForStmt | None:
        start = self._advance().span
        name = self._expect("lower", "expected a loop variable")
        if name is None:
            return None
        self._expect("in", "expected `in`")
        expr = self._expression()
        if expr is None:
            return None
        body = self._do_block()
        if body is None:
            return None
        return ForStmt(merge_spans(start, body.span), name.text, expr, body)

    def _using(self) -> UsingStmt | None:
        start = self._advance().span
        name = self._expect("lower", "expected a resource name")
        if name is None:
            return None
        self._expect("=", "expected `=`")
        expr = self._expression()
        if expr is None:
            return None
        body = self._do_block()
        if body is None:
            return None
        return UsingStmt(merge_spans(start, body.span), name.text, expr, body)

    def _block_until(self) -> Block:
        """Parse a block whose closing `end` belongs to the enclosing statement."""
        start = self._peek().span
        stmts: list[object] = []
        while not self._at_any(STOP_BLOCK):
            if self._at("nl"):
                self._advance()
                continue
            stmt = self._statement()
            if stmt is None:
                if self._at_any(STOP_BLOCK) or self._at("eof"):
                    break
                self._advance()
                continue
            stmts.append(stmt)
            if self._at("nl"):
                self._advance()
            else:
                self._error("E1000", "expected a line break after the statement", self._peek().span)
                break
        end_span = self._peek().span
        if stmts:
            end_span = stmts[-1].span  # type: ignore[attr-defined]
        return Block(merge_spans(start, end_span) if stmts else start, stmts)  # type: ignore[arg-type]

    def _expression(self) -> Expr | None:
        if self._at("function") and self._lookahead_is("("):
            return self._lambda()
        return self._or()

    def _lambda(self) -> LambdaExpr | None:
        start = self._advance().span
        self._expect("(", "expected `(`")
        params = self._params()
        self._expect(")", "expected `)`")
        self._expect("returns", "expected `returns`")
        ret = self._type()
        if ret is None:
            return None
        if self._expect_do() is None:
            return None
        self._skip_nl()
        body = self._expression()
        if body is None:
            return None
        self._skip_nl()
        end = self._expect("end", "expected `end`")
        end_span = end.span if end is not None else body.span
        return LambdaExpr(merge_spans(start, end_span), params, ret, body)

    def _or(self) -> Expr | None:
        left = self._and()
        if left is None:
            return None
        while self._at("or"):
            op = self._advance()
            right = self._and()
            if right is None:
                return None
            if _mixes_and(left) or _mixes_and(right):
                self.diagnostics.append(
                    Diagnostic(
                        code="W1103",
                        message="`and` and `or` are mixed without parentheses",
                        file=self.source.filename,
                        span=merge_spans(left.span, right.span),
                        fix=Fix(
                            "the formatter will add parentheses; write them yourself to show the grouping"
                        ),
                    )
                )
            left = BinaryExpr(merge_spans(left.span, right.span), op.text, left, right)
        return left

    def _and(self) -> Expr | None:
        left = self._not()
        if left is None:
            return None
        while self._at("and"):
            op = self._advance()
            right = self._not()
            if right is None:
                return None
            left = BinaryExpr(merge_spans(left.span, right.span), op.text, left, right)
        return left

    def _not(self) -> Expr | None:
        if self._at("not"):
            op = self._advance()
            expr = self._not()
            if expr is None:
                return None
            return UnaryExpr(merge_spans(op.span, expr.span), "not", expr)
        return self._comparison()

    def _comparison(self) -> Expr | None:
        left = self._additive()
        if left is None:
            return None
        if self._at_any({"==", "!=", "<", "<=", ">", ">="}):
            op = self._advance()
            right = self._additive()
            if right is None:
                return None
            if self._at_any({"==", "!=", "<", "<=", ">", ">="}):
                self._error(
                    "E1102",
                    "chained comparison",
                    self._peek().span,
                    fix="use `and`, for example `a < b and b < c`",
                )
                while self._at_any({"==", "!=", "<", "<=", ">", ">="}):
                    self._advance()
                    skipped = self._additive()
                    if skipped is None:
                        break
            return BinaryExpr(merge_spans(left.span, right.span), op.text, left, right)
        return left

    def _additive(self) -> Expr | None:
        left = self._multiplicative()
        if left is None:
            return None
        while self._at("+") or self._at("-"):
            op = self._advance()
            right = self._multiplicative()
            if right is None:
                return None
            left = BinaryExpr(merge_spans(left.span, right.span), op.text, left, right)
        return left

    def _multiplicative(self) -> Expr | None:
        left = self._prefix()
        if left is None:
            return None
        while self._at_any({"*", "/", "div", "mod"}):
            op = self._advance()
            right = self._prefix()
            if right is None:
                return None
            left = BinaryExpr(merge_spans(left.span, right.span), op.text, left, right)
        return left

    def _prefix(self) -> Expr | None:
        if self._at("-") or self._at("try"):
            op = self._advance()
            expr = self._prefix()
            if expr is None:
                return None
            return UnaryExpr(merge_spans(op.span, expr.span), op.text, expr)
        return self._update()

    def _update(self) -> Expr | None:
        expr = self._postfix()
        if expr is None:
            return None
        if self._at("with"):
            self._advance()
            self._expect("(", "expected `(`")
            fields: list[FieldInit] = []
            if not self._at(")"):
                while True:
                    field = self._field_init()
                    if field is None:
                        return None
                    fields.append(field)
                    if self._at(","):
                        self._advance()
                        if self._at(")"):
                            break
                        continue
                    break
            close = self._expect(")", "expected `)`")
            end_span = close.span if close is not None else expr.span
            expr = WithExpr(merge_spans(expr.span, end_span), expr, fields)
            if self._at("with"):
                self._error(
                    "E1101",
                    "only one `with` is allowed in an expression",
                    self._peek().span,
                    fix="put every field in one `with`",
                )
        return expr

    def _field_init(self) -> FieldInit | None:
        if self._at("named_arg"):
            token = self._advance()
            expr = self._expression()
            if expr is None:
                return None
            return FieldInit(merge_spans(token.span, expr.span), token.text, expr)
        name = self._expect("lower", "expected a field name")
        if name is None:
            return None
        self._expect("=", "expected `=`")
        expr = self._expression()
        if expr is None:
            return None
        return FieldInit(merge_spans(name.span, expr.span), name.text, expr)

    def _postfix(self) -> Expr | None:
        expr = self._primary()
        if expr is None:
            return None
        while self._at("(") or self._at("."):
            if self._at("."):
                dot = self._advance()
                name = self._name_token()
                if name is None:
                    return None
                _ = dot
                expr = FieldExpr(merge_spans(expr.span, name.span), expr, name.text)
                continue
            self._advance()
            args: list[Arg] = []
            if not self._at(")"):
                while True:
                    arg_name = None
                    arg_span = self._peek().span
                    if self._at("named_arg"):
                        named = self._advance()
                        arg_name = named.text
                        arg_span = named.span
                    value = self._expression()
                    if value is None:
                        return None
                    args.append(Arg(merge_spans(arg_span, value.span), arg_name, value))
                    if self._at(","):
                        self._advance()
                        if self._at(")"):
                            break
                        continue
                    break
            close = self._expect(")", "expected `)`")
            end_span = close.span if close is not None else expr.span
            expr = CallExpr(merge_spans(expr.span, end_span), expr, args)
        return expr

    def _primary(self) -> Expr | None:
        token = self._peek()
        if token.kind == "int":
            self._advance()
            return LiteralExpr(token.span, "int", token.value)
        if token.kind == "float":
            self._advance()
            return LiteralExpr(token.span, "float", token.value)
        if token.kind == "text":
            self._advance()
            return LiteralExpr(token.span, "text", token.value)
        if token.kind in {"true", "false"}:
            self._advance()
            return LiteralExpr(token.span, "bool", token.kind == "true")
        if token.kind == "lower":
            self._advance()
            return NameExpr(token.span, token.text)
        if token.kind == "upper":
            self._advance()
            return NameExpr(token.span, token.text)
        if token.kind == "result":
            self._advance()
            return ResultExpr(token.span)
        if token.kind == "old":
            start = self._advance().span
            self._expect("(", "expected `(`")
            expr = self._expression()
            if expr is None:
                return None
            close = self._expect(")", "expected `)`")
            end_span = close.span if close is not None else expr.span
            return OldExpr(merge_spans(start, end_span), expr)
        if token.kind == "(":
            start = self._advance().span
            expr = self._expression()
            if expr is None:
                return None
            close = self._expect(")", "expected `)`")
            end_span = close.span if close is not None else expr.span
            return GroupExpr(merge_spans(start, end_span), expr)
        if token.kind == "[":
            return self._list()
        if token.kind == "{":
            return self._map()
        self._error(
            "E1000", f"expected an expression, found `{token.text or token.kind}`", token.span
        )
        return None

    def _list(self) -> ListExpr | None:
        start = self._advance().span
        elements: list[Expr] = []
        if not self._at("]"):
            while True:
                expr = self._expression()
                if expr is None:
                    return None
                elements.append(expr)
                if self._at(","):
                    self._advance()
                    if self._at("]"):
                        break
                    continue
                break
        close = self._expect("]", "expected `]`")
        end_span = close.span if close is not None else start
        return ListExpr(merge_spans(start, end_span), elements)

    def _map(self) -> MapExpr | None:
        start = self._advance().span
        entries: list[tuple[Expr, Expr]] = []
        if not self._at("}"):
            while True:
                key = self._expression()
                if key is None:
                    return None
                self._expect(":", "expected `:`")
                value = self._expression()
                if value is None:
                    return None
                entries.append((key, value))
                if self._at(","):
                    self._advance()
                    if self._at("}"):
                        break
                    continue
                break
        close = self._expect("}", "expected `}`")
        end_span = close.span if close is not None else start
        return MapExpr(merge_spans(start, end_span), entries)

    def _pattern(self) -> Pattern | None:
        token = self._peek()
        if token.kind == "wildcard":
            self._advance()
            return WildPat(token.span)
        if token.kind == "lower":
            if self._lookahead_is("."):
                return self._ctor_pattern()
            self._advance()
            return BindPat(token.span, token.text)
        if token.kind in {"int", "float", "text", "true", "false"}:
            self._advance()
            if token.kind in {"true", "false"}:
                return LitPat(token.span, "bool", token.kind == "true")
            kind = {"int": "int", "float": "float", "text": "text"}[token.kind]
            return LitPat(token.span, kind, token.value)
        if token.kind == "-":
            start = self._advance().span
            number = self._peek()
            if number.kind not in {"int", "float"}:
                self._error("E1000", "expected a number after `-`", number.span)
                return None
            self._advance()
            if number.kind == "int":
                raw = number.value
                value = None if not isinstance(raw, int) else -raw
                return LitPat(merge_spans(start, number.span), "int", value)
            assert isinstance(number.value, float)
            return LitPat(merge_spans(start, number.span), "float", -number.value)
        if token.kind == "upper":
            return self._ctor_pattern()
        self._error("E1000", "expected a pattern", token.span)
        return None

    def _ctor_pattern(self) -> Pattern | None:
        parts: list[str] = []
        start = self._peek().span
        if self._at("lower"):
            while self._at("lower"):
                parts.append(self._advance().text)
                if self._at("."):
                    self._advance()
                    continue
                self._error("E1000", "expected a case name", self._peek().span)
                return None
        name_tok = self._expect("upper", "expected a case name")
        if name_tok is None:
            return None
        fields: list[Pattern] | None = None
        end_span = name_tok.span
        if self._at("("):
            self._advance()
            fields = []
            if not self._at(")"):
                while True:
                    field = self._pattern()
                    if field is None:
                        return None
                    fields.append(field)
                    if self._at(","):
                        self._advance()
                        if self._at(")"):
                            break
                        continue
                    break
            close = self._expect(")", "expected `)`")
            if close is not None:
                end_span = close.span
        return CtorPat(merge_spans(start, end_span), parts, name_tok.text, fields)

    def _type(self) -> TypeExpr | None:
        if self._at("function"):
            start = self._advance().span
            self._expect("(", "expected `(`")
            params: list[TypeExpr] = []
            if not self._at(")"):
                while True:
                    param = self._type()
                    if param is None:
                        return None
                    params.append(param)
                    if self._at(","):
                        self._advance()
                        continue
                    break
            self._expect(")", "expected `)`")
            self._expect("returns", "expected `returns`")
            ret = self._type()
            if ret is None:
                return None
            return TypeExpr(merge_spans(start, ret.span), "function", [], "", [], params, ret)
        path: list[str] = []
        start = self._peek().span
        if self._at("lower"):
            while self._at("lower"):
                path.append(self._advance().text)
                if not self._at("."):
                    self._error("E1000", "expected `.` in a module path", self._peek().span)
                    return None
                self._advance()
        name = self._expect("upper", "expected a type name")
        if name is None:
            return None
        args: list[TypeExpr] = []
        end_span = name.span
        if self._at("["):
            self._advance()
            while True:
                arg = self._type()
                if arg is None:
                    return None
                args.append(arg)
                end_span = arg.span
                if self._at(","):
                    self._advance()
                    continue
                break
            close = self._expect("]", "expected `]`")
            if close is not None:
                end_span = close.span
        return TypeExpr(merge_spans(start, end_span), "named", path, name.text, args)

    def _type_params(self) -> list[TypeParam]:
        if not self._at("["):
            return []
        self._advance()
        params: list[TypeParam] = []
        while True:
            name = self._expect("upper", "expected a type parameter")
            if name is None:
                return params
            constraints: list[TypeExpr] = []
            if self._at(":"):
                self._advance()
                constraint = self._constraint()
                if constraint is not None:
                    constraints.append(constraint)
                while self._at("and"):
                    self._advance()
                    constraint = self._constraint()
                    if constraint is not None:
                        constraints.append(constraint)
            params.append(TypeParam(name.span, name.text, constraints))
            if self._at(","):
                self._advance()
                continue
            break
        self._expect("]", "expected `]`")
        return params

    def _constraint(self) -> TypeExpr | None:
        name = self._expect("upper", "expected a constraint")
        if name is None:
            return None
        args: list[TypeExpr] = []
        end_span = name.span
        if self._at("["):
            self._advance()
            while True:
                arg = self._type()
                if arg is None:
                    return None
                args.append(arg)
                end_span = arg.span
                if self._at(","):
                    self._advance()
                    continue
                break
            close = self._expect("]", "expected `]`")
            if close is not None:
                end_span = close.span
        return TypeExpr(merge_spans(name.span, end_span), "named", [], name.text, args)

    def _params(self) -> list[Param]:
        params: list[Param] = []
        if self._at(")") or self._at("do") or self._at("nl") or self._at("]"):
            return params
        if not self._at("lower") and not self._keyword_before(":"):
            return params
        while self._at("lower") or self._keyword_before(":"):
            name = (
                self._advance()
                if self._at("lower")
                else self._keyword_as_name("expected a parameter name")
            )
            if name is None:
                return params
            self._expect(":", "expected `:`")
            ty = self._type()
            if ty is None:
                return params
            params.append(Param(merge_spans(name.span, ty.span), name.text, ty))
            if self._at(","):
                self._advance()
                continue
            break
        return params

    def _module_path(self) -> list[str] | None:
        name = self._expect("lower", "expected a module name")
        if name is None:
            return None
        path = [name.text]
        while self._at("."):
            self._advance()
            name = self._expect("lower", "expected a module name")
            if name is None:
                return None
            path.append(name.text)
        return path

    def _name_token(self) -> Token | None:
        if self._at("lower") or self._at("upper"):
            return self._advance()
        if self._at_keyword():
            return self._keyword_as_name("expected a name")
        self._error("E1000", "expected a name", self._peek().span)
        return None

    def _keyword_before(self, kind: str) -> bool:
        return self._at_keyword() and self._lookahead_is(kind)

    def _lookahead_is(self, kind: str) -> bool:
        nxt = self.pos + 1
        return nxt < len(self.tokens) and self.tokens[nxt].kind == kind

    def _at(self, kind: str) -> bool:
        return self._peek().kind == kind

    def _at_any(self, kinds: frozenset[str] | set[str]) -> bool:
        return self._peek().kind in kinds

    def _peek(self) -> Token:
        return self.tokens[self.pos]

    def _advance(self) -> Token:
        token = self._peek()
        if token.kind != "eof" and self.pos + 1 < len(self.tokens):
            self.pos += 1
        return token

    def _expect(self, kind: str, message: str) -> Token | None:
        if self._at(kind):
            return self._advance()
        if kind in {"lower", "upper"} and self._at_keyword():
            return self._keyword_as_name(message)
        self._error("E1000", message, self._peek().span)
        return None

    def _at_keyword(self) -> bool:
        return self._peek().kind in KEYWORDS

    def _keyword_as_name(self, message: str) -> Token | None:
        """Report a reserved keyword in a name position (still `E1000`).

        The lexer never turns a keyword into a name token, so this is the
        layer that rejects it. When the next token shows the keyword was meant
        as a name, it is consumed so one mistake gives one diagnostic.
        """
        token = self._peek()
        self._error(
            "E1000",
            f"{message}, found the keyword `{token.text}` (keywords are reserved and cannot be names)",
            token.span,
        )
        if self._lookahead_is("=") or self._lookahead_is(":") or self._lookahead_is("("):
            return self._advance()
        return None

    def _break_or_do(self, message: str) -> bool:
        """A line break is required here. `do` on this same line is still `E1000`."""
        if self._at("do"):
            self._error("E1000", "expected `do` on its own line", self._peek().span)
            return False
        return self._expect("nl", message) is not None

    def _expect_do(self) -> Token | None:
        """`do` is the only token on its line. A trailing comment is allowed.

        The lambda-frame lexer emits `nl` from a lambda's parameter `)` through
        its `end`, including when that lambda sits inside parentheses.
        """
        self._skip_nl()
        if not self._at("do"):
            self._error("E1000", "expected `do` on its own line", self._peek().span)
            return None
        token = self._peek()
        previous = self._previous_code_token()
        if previous is not None and previous.span.end_line == token.span.start_line:
            self._error("E1000", "expected `do` on its own line", token.span)
        do_token = self._advance()
        nxt = self._peek()
        if nxt.kind not in {"nl", "eof"} and nxt.span.start_line == do_token.span.start_line:
            self._error("E1000", "expected `do` on its own line", do_token.span)
        return do_token

    def _previous_code_token(self) -> Token | None:
        index = self.pos - 1
        while index >= 0 and self.tokens[index].kind in {"nl", "eof"}:
            index -= 1
        if index < 0:
            return None
        return self.tokens[index]

    def _skip_nl(self) -> None:
        while self._at("nl"):
            self._advance()

    def _error(self, code: str, message: str, span: Span, *, fix: str | None = None) -> None:
        self.diagnostics.append(
            Diagnostic(
                code=code,
                message=message,
                file=self.source.filename,
                span=span,
                fix=None if fix is None else Fix(fix),
            )
        )

    def _sync_decl(self) -> None:
        while not self._at("eof") and not self._at("nl"):
            self._advance()


def _mixes_and(expr: Expr) -> bool:
    if isinstance(expr, GroupExpr):
        return False
    if isinstance(expr, BinaryExpr) and expr.op == "and":
        return True
    return False


def parse_module(
    source: Source, tokens: list[Token], diagnostics: list[Diagnostic]
) -> Module | None:
    """Parse a token stream into a module; see `Parser.parse_module`."""
    return Parser(source, tokens, diagnostics).parse_module()


def parse_expression(
    source: Source, tokens: list[Token], diagnostics: list[Diagnostic]
) -> Expr | None:
    """Parse a token stream that holds one expression and nothing else."""
    return Parser(source, tokens, diagnostics).parse_expression_only()
