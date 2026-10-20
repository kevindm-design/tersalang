# SPDX-License-Identifier: Apache-2.0
"""Lexer for Tersalang. Emits `nl` and `named_arg` tokens so the parser stays context-free."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from tersalang.diagnostics import Diagnostic, Fix
from tersalang.source import Source, Span
from tersalang.version import DEFAULT_MAX_INT_BITS

KEYWORDS = frozenset(
    {
        "module",
        "import",
        "as",
        "exposing",
        "public",
        "foreign",
        "function",
        "returns",
        "uses",
        "requires",
        "ensures",
        "invariant",
        "record",
        "choice",
        "case",
        "interface",
        "implements",
        "let",
        "var",
        "test",
        "do",
        "end",
        "if",
        "then",
        "elseif",
        "else",
        "match",
        "while",
        "for",
        "in",
        "break",
        "continue",
        "return",
        "using",
        "set",
        "fail",
        "expect",
        "try",
        "and",
        "or",
        "not",
        "div",
        "mod",
        "with",
        "true",
        "false",
        "result",
        "old",
        "all",
        "parallel",
        "spawn",
        "send",
        "receive",
        "type",
        "alias",
        "async",
        "await",
    }
)

CONTINUATION = frozenset(
    {
        "+",
        "-",
        "*",
        "/",
        "==",
        "!=",
        "<",
        "<=",
        ">",
        ">=",
        "and",
        "or",
        "div",
        "mod",
        "not",
        ",",
        "=",
        ".",
        ":",
        "with",
        "uses",
        "requires",
        "ensures",
    }
)

TWO_CHAR = {
    "==": "==",
    "!=": "!=",
    "<=": "<=",
    ">=": ">=",
    "->": "->",
    "=>": "=>",
    "&&": "&&",
    "||": "||",
}

PUNCT = set("+-*/=<>:,.()[]{}_")

BAD_TOKEN_HINTS = {
    "%": "use `mod`",
    "&&": "use `and`",
    "||": "use `or`",
    "!": "use `not`",
    "->": "use `returns`",
    "=>": "use `then`",
    ";": "use a line break",
    "?": "use `try`",
    "&": "v1 has no bitwise operations",
    "|": "v1 has no bitwise operations",
    "^": "v1 has no bitwise operations",
}


@dataclass
class Token:
    """One token.

    `kind` is a keyword, the punctuation itself, or one of `lower`, `upper`,
    `wildcard`, `named_arg`, `int`, `float`, `text`, `nl`, and `eof`. `value`
    is a literal's decoded value (None for an `int` over the bit cap). `doc`
    joins the `##` lines directly above the token.
    """

    kind: str
    text: str
    span: Span
    value: object = None
    doc: str | None = None


def _ascii_digit(char: str) -> bool:
    return "0" <= char <= "9"


@dataclass
class Lexer:
    """Turns one source into `tokens` and lexical diagnostics (`E00xx`).

    A line break is an `nl` token only after a line that had a token, outside
    brackets, and when the line does not end in a `CONTINUATION` token. Inside
    a lambda body, bracket depth counts from the lambda's parameter `)`, so a
    lambda passed as an argument still gets `nl` between its statements.
    Inside parentheses, `name =` is one `named_arg` token.
    """

    source: Source
    tokens: list[Token]
    diagnostics: list[Diagnostic]
    index: int = 0
    paren_depth: int = 0
    bracket_depth: int = 0
    pending_docs: list[str] | None = None
    line_has_token: bool = False
    line_has_doc: bool = False
    last_kind: str | None = None
    # Bracket depth saved at each lambda's parameter `)`. While a frame is
    # active, newline suppression uses depth relative to that saved value.
    lambda_bases: list[int] = field(default_factory=list)
    pending_lambda_parens: list[int] = field(default_factory=list)
    _arm_lambda_paren: bool = False

    def __post_init__(self) -> None:
        self.pending_docs = []

    @property
    def text(self) -> str:
        """The source text, with invalid UTF-8 already blanked by `lex`."""
        return self.source.text

    def lex(self) -> None:
        """Lex the whole source, ending with `nl` (when the last line had a token) and `eof`.

        A byte-order mark is `E0001`, a non-ASCII character outside text and
        comments `E0002`, a tab `E0003`, and a lone CR `E0004`. Lexing goes on
        after every error.
        """
        raw = self.text
        if raw.startswith("\ufeff"):
            self.error("E0001", "byte-order mark is not allowed at byte offset 0", 0, 1)
            self.index = 1
        self._blank_invalid_utf8()
        raw = self.text
        while self.index < len(raw):
            char = raw[self.index]
            if char in " \t":
                if char == "\t":
                    self.error(
                        "E0003",
                        "tab character outside a text literal or comment",
                        self.index,
                        self.index + 1,
                        fix="use spaces",
                    )
                    self.recover_line()
                    continue
                self.index += 1
                continue
            if char == "\n":
                self.newline(1)
                continue
            if char == "\r":
                if self.index + 1 < len(raw) and raw[self.index + 1] == "\n":
                    self.newline(2)
                    continue
                self.error("E0004", "lone CR is not a line ending", self.index, self.index + 1)
                self.newline(1)
                continue
            if char == "#":
                self.comment()
                continue
            if char == '"':
                self.string()
                continue
            if char == "_" and not self._ident_continue(self.index + 1):
                self.emit("wildcard", "_", self.index, self.index + 1)
                self.index += 1
                continue
            if char.isascii() and (char.isalpha() or char == "_"):
                self.word()
                continue
            if char.isascii() and char.isdigit():
                self.number()
                continue
            if char == "." and self._is_digit(self.index + 1):
                start = self.index
                self.index += 1
                while self.index < len(raw) and (
                    self._is_digit(self.index) or raw[self.index] == "_"
                ):
                    self.index += 1
                self.error(
                    "E0022",
                    "float literals need digits on both sides of the dot",
                    start,
                    self.index,
                    fix="write 0.5",
                )
                continue
            if not char.isascii():
                self.error(
                    "E0002",
                    "non-ASCII character outside a text literal or comment",
                    self.index,
                    self.index + 1,
                )
                self.recover_line()
                continue
            self.symbol()
        if self.line_has_token and self.last_kind != "nl" and not self._suppress_nl():
            self.emit("nl", "\n", len(raw), len(raw), synthetic=True)
        self.emit("eof", "", len(raw), len(raw), synthetic=True)

    def newline(self, width: int) -> None:
        """Consume a line ending `width` characters wide, emitting `nl` unless it is suppressed.

        A line with neither a token nor a doc comment drops the pending doc comments.
        """
        if not self.line_has_token and not self.line_has_doc:
            assert self.pending_docs is not None
            self.pending_docs.clear()
        if self.line_has_token and not self._suppress_nl():
            self.emit("nl", "\n", self.index, self.index, synthetic=True)
        self.index += width
        self.line_has_token = False
        self.line_has_doc = False

    def _suppress_nl(self) -> bool:
        return self._nl_bracket_depth() > 0 or self.last_kind in CONTINUATION

    def _nl_bracket_depth(self) -> int:
        if self.lambda_bases:
            return self.bracket_depth - self.lambda_bases[-1]
        return self.bracket_depth

    def _blank_invalid_utf8(self) -> None:
        """Any invalid UTF-8 byte is E0001. The rest of that line is skipped."""
        raw = self.text
        if not any("\ud800" <= char <= "\udfff" for char in raw):
            return
        chars = list(raw)
        index = 0
        while index < len(chars):
            if "\ud800" <= chars[index] <= "\udfff":
                offset = _utf8_offset(chars, index)
                self.error(
                    "E0001",
                    f"invalid UTF-8 byte sequence at byte offset {offset}",
                    index,
                    index + 1,
                )
                while index < len(chars) and chars[index] not in "\n\r":
                    chars[index] = " "
                    index += 1
                continue
            index += 1
        self.source = Source(self.source.filename, "".join(chars))

    def comment(self) -> None:
        """Consume a comment to the end of the line.

        A `##` comment is kept as a doc line for the next token. A plain comment
        on a line with no token drops the pending doc lines.
        """
        raw = self.text
        is_doc = self.index + 1 < len(raw) and raw[self.index + 1] == "#"
        self.index += 2 if is_doc else 1
        body_start = self.index
        if is_doc and self.index < len(raw) and raw[self.index] == " ":
            body_start += 1
        while self.index < len(raw) and raw[self.index] not in "\n\r":
            self.index += 1
        if is_doc:
            assert self.pending_docs is not None
            self.pending_docs.append(raw[body_start : self.index])
            self.line_has_doc = True
        elif not self.line_has_token:
            assert self.pending_docs is not None
            self.pending_docs.clear()

    def word(self) -> None:
        """Lex a keyword, an `upper` or `lower` name, or a `named_arg`.

        A name over 64 characters is `E0012`. A lower name that starts with `_`,
        contains `__`, or ends with `_` is `E0010`; an upper name with `_` is
        `E0011`. The name is still emitted.
        """
        raw = self.text
        start = self.index
        self.index += 1
        while self.index < len(raw) and self._ident_continue(self.index):
            self.index += 1
        text = raw[start : self.index]
        if not text[0].isascii() or not (text[0].isalpha() or text[0] == "_"):
            return
        if len(text) > 64:
            self.error(
                "E0012", f"name `{text[:16]}...` is longer than 64 characters", start, self.index
            )
        if text[0] == "_" or (text[0].islower() and ("__" in text or text.endswith("_"))):
            self.error(
                "E0010",
                f"lower name `{text}` must not contain `__` or end with `_`",
                start,
                self.index,
            )
            self.emit("lower", text, start, self.index)
            return
        if text[0].isupper():
            if "_" in text or not all(char.isascii() and (char.isalnum()) for char in text):
                self.error(
                    "E0011",
                    f"Upper name `{text}` cannot contain `_`",
                    start,
                    self.index,
                    fix=f"write {text.replace('_', '')}",
                )
            self.emit("upper", text, start, self.index)
            return
        if text in KEYWORDS:
            if text == "function" and self._looks_like_lambda():
                self._arm_lambda_paren = True
            if text == "end" and self.lambda_bases:
                self.lambda_bases.pop()
            self.emit(text, text, start, self.index)
            return
        if self.paren_depth > 0 and self._named_arg_equals():
            eq = self._skip_spaces(self.index)
            self.emit("named_arg", text, start, eq + 1)
            self.index = eq + 1
            return
        self.emit("lower", text, start, self.index)

    def _named_arg_equals(self) -> bool:
        eq = self._skip_spaces(self.index)
        return eq < len(self.text) and self.text[eq] == "=" and not self.text.startswith("==", eq)

    def _skip_spaces(self, pos: int) -> int:
        raw = self.text
        while pos < len(raw) and raw[pos] == " ":
            pos += 1
        return pos

    def number(self) -> None:
        """Lex a decimal `int` or `float`; `0x` and `0b` literals go to `_radix`.

        A leading zero or a misplaced `_` is `E0021`, a malformed float `E0022`,
        and an integer over `DEFAULT_MAX_INT_BITS` bits `E0020`.
        """
        raw = self.text
        start = self.index
        if raw.startswith("0x", self.index):
            self._radix(start, 2, 16, "hexadecimal")
            return
        if raw.startswith("0b", self.index):
            self._radix(start, 2, 2, "binary")
            return
        self.index += 1
        if raw[start] == "0" and self._is_digit(self.index):
            while self.index < len(raw) and (self._is_digit(self.index) or raw[self.index] == "_"):
                self.index += 1
            self.error(
                "E0021",
                "leading zeros are not allowed",
                start,
                self.index,
                fix="write the number without the leading zero",
            )
            return
        self._digits(underscore=True)
        saw_dot = False
        if self.index < len(raw) and raw[self.index] == ".":
            if self._is_digit(self.index + 1):
                saw_dot = True
                self.index += 1
                self._digits(underscore=True)
            else:
                end = self.index + 1
                self.error(
                    "E0022",
                    "float literals need digits on both sides of the dot",
                    start,
                    end,
                    fix="write a digit after the dot, such as 5.0",
                )
                self.index = end
                return
        saw_exp = False
        if self.index < len(raw) and raw[self.index] in "eE":
            # The grammar spells the exponent marker as lowercase "e".
            if raw[self.index] == "E":
                self.error(
                    "E0022",
                    "float exponent marker must be lowercase `e`",
                    self.index,
                    self.index + 1,
                )
            saw_exp = True
            self.index += 1
            if self.index < len(raw) and raw[self.index] in "+-":
                self.index += 1
            exp_start = self.index
            if not self._is_digit(self.index):
                self.error("E0022", "float exponent needs digits", start, self.index)
                return
            while self._is_digit(self.index):
                self.index += 1
            if exp_start == self.index:
                self.error("E0022", "float exponent needs digits", start, self.index)
                return
        lexeme = raw[start : self.index]
        if saw_dot or saw_exp:
            if (
                "__" in lexeme
                or lexeme.endswith("_")
                or "._" in lexeme
                or "_." in lexeme
                or "_e" in lexeme
            ):
                self.error(
                    "E0021",
                    "underscores in a numeric literal must sit between digits",
                    start,
                    self.index,
                )
                return
            try:
                value = float(lexeme.replace("_", ""))
            except ValueError:
                self.error("E0022", "malformed float literal", start, self.index)
                return
            self.emit("float", lexeme, start, self.index, value=value)
            return
        self._emit_int(lexeme, start, self.index, base=10)

    def _radix(self, start: int, prefix: int, base: int, label: str) -> None:
        raw = self.text
        self.index = start + prefix
        pred = "" if base == 16 else "01"
        while self.index < len(raw):
            char = raw[self.index]
            if char == "_":
                self.index += 1
                continue
            if base == 16 and char in "0123456789abcdefABCDEF":
                self.index += 1
                continue
            if base == 2 and char in "01":
                self.index += 1
                continue
            break
        lexeme = raw[start : self.index]
        digits = lexeme[prefix:].replace("_", "")
        if not digits or any(
            char not in ("0123456789abcdefABCDEF" if base == 16 else pred) for char in digits
        ):
            self.error(
                "E0025", f"malformed {label} literal", start, max(self.index, start + prefix)
            )
            return
        if "__" in lexeme or lexeme.endswith("_") or f"{lexeme[prefix]}".startswith("_"):
            self.error(
                "E0021",
                "underscores in a numeric literal must sit between digits",
                start,
                self.index,
            )
            return
        self._emit_int(digits, start, self.index, base=base, lexeme=lexeme)

    def _digits(self, *, underscore: bool) -> None:
        raw = self.text
        while self.index < len(raw):
            char = raw[self.index]
            if _ascii_digit(char) or (underscore and char == "_"):
                self.index += 1
                continue
            break

    def _emit_int(
        self, digits: str, start: int, end: int, *, base: int, lexeme: str | None = None
    ) -> None:
        shown = lexeme if lexeme is not None else digits
        cleaned = digits.replace("_", "")
        if "__" in shown or shown.endswith("_"):
            self.error(
                "E0021", "underscores in a numeric literal must sit between digits", start, end
            )
            return
        significant = cleaned.lstrip("0") or "0"
        if base == 10:
            limit_digits = math.ceil(DEFAULT_MAX_INT_BITS * math.log10(2)) + 1
            if len(significant) > limit_digits:
                self.error(
                    "E0020",
                    f"integer literal needs more than {DEFAULT_MAX_INT_BITS} bits",
                    start,
                    end,
                )
                self.emit("int", shown, start, end, value=None)
                return
        elif len(significant) * (4 if base == 16 else 1) > DEFAULT_MAX_INT_BITS + 8:
            self.error(
                "E0020",
                f"integer literal needs more than {DEFAULT_MAX_INT_BITS} bits",
                start,
                end,
            )
            self.emit("int", shown, start, end, value=None)
            return
        value = int(cleaned, base)
        if value.bit_length() > DEFAULT_MAX_INT_BITS:
            self.error(
                "E0020",
                f"integer literal needs more than {DEFAULT_MAX_INT_BITS} bits",
                start,
                end,
            )
            self.emit("int", shown, start, end, value=None)
            return
        self.emit("int", shown, start, end, value=value)

    def string(self) -> None:
        """Lex a text literal; `value` holds the text with its escapes decoded.

        A raw line break is `E0023`, a bad unicode escape `E0024`, a missing
        closing quote `E0026`, and an unknown escape `E0027`. A literal with an
        escape error emits no token.
        """
        raw = self.text
        start = self.index
        self.index += 1
        chars: list[str] = []
        ok = True
        while self.index < len(raw):
            char = raw[self.index]
            if char == '"':
                self.index += 1
                if ok:
                    self.emit(
                        "text", raw[start : self.index], start, self.index, value="".join(chars)
                    )
                return
            if char == "\n" or char == "\r":
                self.error("E0023", "raw newline inside a text literal", start, self.index)
                return
            if char == "\\":
                escape_start = self.index
                self.index += 1
                if self.index >= len(raw):
                    break
                esc = raw[self.index]
                mapping = {
                    "n": "\n",
                    "t": "\t",
                    "r": "\r",
                    "\\": "\\",
                    '"': '"',
                    "{": "{",
                    "}": "}",
                }
                if esc in mapping:
                    chars.append(mapping[esc])
                    self.index += 1
                    continue
                if esc == "u":
                    point, good = self._unicode_escape(escape_start)
                    if good and point is not None:
                        chars.append(chr(point))
                    else:
                        ok = False
                    continue
                self.error("E0027", f"unknown text escape `\\{esc}`", escape_start, self.index + 1)
                self.index += 1
                ok = False
                continue
            chars.append(char)
            self.index += 1
        self.error("E0026", "unterminated text literal", start, self.index)

    def _unicode_escape(self, escape_start: int) -> tuple[int | None, bool]:
        raw = self.text
        # caller has consumed '\', current char is 'u'
        self.index += 1
        if self.index >= len(raw) or raw[self.index] != "{":
            self.error("E0024", "unicode escape must look like \\u{...}", escape_start, self.index)
            return None, False
        self.index += 1
        hex_start = self.index
        while self.index < len(raw) and raw[self.index] in "0123456789abcdefABCDEF":
            self.index += 1
        hex_digits = raw[hex_start : self.index]
        if self.index >= len(raw) or raw[self.index] != "}":
            self.error("E0024", "unicode escape is missing `}`", escape_start, self.index)
            return None, False
        self.index += 1
        if not hex_digits or len(hex_digits) > 6:
            self.error("E0024", "unicode escape needs 1 to 6 hex digits", escape_start, self.index)
            return None, False
        value = int(hex_digits, 16)
        if value > 0x10FFFF or 0xD800 <= value <= 0xDFFF:
            self.error("E0024", "unicode escape is not a scalar value", escape_start, self.index)
            return None, False
        return value, True

    def symbol(self) -> None:
        """Lex an operator or punctuation token and track bracket depth.

        `->`, `=>`, `&&`, `||`, and the other `BAD_TOKEN_HINTS` characters are
        `E0030` with a hint, and the rest of the line is skipped.
        """
        raw = self.text
        start = self.index
        two = raw[start : start + 2]
        if two in TWO_CHAR:
            self.index += 2
            if two in {"->", "=>", "&&", "||"}:
                self._bad(two, start, self.index)
                return
            self.emit(two, two, start, self.index)
            return
        char = raw[start]
        self.index += 1
        if char in BAD_TOKEN_HINTS:
            self._bad(char, start, self.index)
            return
        if char in PUNCT:
            if char in "([{":
                self.bracket_depth += 1
                if char == "(":
                    self.paren_depth += 1
                    if self._arm_lambda_paren:
                        self.pending_lambda_parens.append(self.paren_depth)
                        self._arm_lambda_paren = False
            elif char in ")]}":
                closing_lambda = (
                    char == ")"
                    and bool(self.pending_lambda_parens)
                    and self.paren_depth == self.pending_lambda_parens[-1]
                )
                if closing_lambda:
                    self.pending_lambda_parens.pop()
                if self.bracket_depth > 0:
                    self.bracket_depth -= 1
                if char == ")" and self.paren_depth > 0:
                    self.paren_depth -= 1
                if closing_lambda:
                    self.lambda_bases.append(self.bracket_depth)
            self.emit(char, char, start, self.index)
            return
        self._bad(char, start, self.index)

    def _bad(self, text: str, start: int, end: int) -> None:
        hint = BAD_TOKEN_HINTS.get(text, "this character is not used in Tersalang")
        self.error("E0030", f"`{text}` is not a Tersalang token", start, end, fix=hint)
        self.recover_line()

    def recover_line(self) -> None:
        """Skip to the end of the current line, leaving the line ending to `lex`."""
        raw = self.text
        while self.index < len(raw) and raw[self.index] not in "\n\r":
            self.index += 1

    def emit(
        self,
        kind: str,
        text: str,
        start: int,
        end: int,
        value: object = None,
        *,
        synthetic: bool = False,
    ) -> None:
        """Append a token. A real token takes the pending doc lines and marks the line."""
        span = self.source.span(start, end)
        doc = None
        if not synthetic and kind != "nl":
            assert self.pending_docs is not None
            if self.pending_docs:
                doc = "\n".join(self.pending_docs)
                self.pending_docs.clear()
            self.line_has_token = True
        token = Token(kind, text, span, value, doc)
        self.tokens.append(token)
        if kind != "eof":
            self.last_kind = kind

    def error(
        self,
        code: str,
        message: str,
        start: int,
        end: int,
        *,
        fix: str | None = None,
    ) -> None:
        """Record a lexical diagnostic; an empty range is widened to one character."""
        span = self.source.span(start, max(end, start + 1) if end == start else end)
        self.diagnostics.append(
            Diagnostic(
                code=code,
                message=message,
                file=self.source.filename,
                span=span,
                fix=None if fix is None else Fix(fix),
            )
        )

    def _ident_continue(self, pos: int) -> bool:
        if pos >= len(self.text):
            return False
        char = self.text[pos]
        return char.isascii() and (char.isalnum() or char == "_")

    def _is_digit(self, pos: int) -> bool:
        return pos < len(self.text) and _ascii_digit(self.text[pos])

    def _looks_like_lambda(self) -> bool:
        """`function (` in expression position whose header is followed by `do`.

        A function type sits after `returns` or `:`. Lookahead still requires
        `do` after the return type, so `returns function (Int) returns Int`
        followed by a function's own `do` does not open a frame.
        """
        if self.last_kind in {"returns", ":"}:
            return False
        raw = self.text
        pos = self._skip_gap(self.index)
        if pos >= len(raw) or raw[pos] != "(":
            return False
        close = self._match_bracket(pos, "(", ")")
        if close is None:
            return False
        pos = self._skip_gap(close + 1)
        if not self._at_word(pos, "returns"):
            return False
        skipped = self._skip_type(pos + len("returns"))
        if skipped is None:
            return False
        return self._at_word(self._skip_gap(skipped), "do")

    def _skip_gap(self, pos: int) -> int:
        raw = self.text
        while pos < len(raw):
            char = raw[pos]
            if char in " \t\r\n":
                pos += 1
                continue
            if char == "#":
                while pos < len(raw) and raw[pos] not in "\n\r":
                    pos += 1
                continue
            break
        return pos

    def _at_word(self, pos: int, word: str) -> bool:
        raw = self.text
        if not raw.startswith(word, pos):
            return False
        end = pos + len(word)
        if end < len(raw) and raw[end].isascii() and (raw[end].isalnum() or raw[end] == "_"):
            return False
        return True

    def _is_ident_start(self, pos: int) -> bool:
        if pos >= len(self.text):
            return False
        char = self.text[pos]
        return char.isascii() and (char.isalpha() or char == "_")

    def _skip_ident(self, pos: int) -> int:
        raw = self.text
        if not self._is_ident_start(pos):
            return pos
        pos += 1
        while pos < len(raw) and raw[pos].isascii() and (raw[pos].isalnum() or raw[pos] == "_"):
            pos += 1
        return pos

    def _match_bracket(self, pos: int, open_char: str, close_char: str) -> int | None:
        raw = self.text
        depth = 0
        index = pos
        while index < len(raw):
            char = raw[index]
            if char == "#":
                while index < len(raw) and raw[index] not in "\n\r":
                    index += 1
                continue
            if char == '"':
                index += 1
                while index < len(raw) and raw[index] not in '"\n\r':
                    if raw[index] == "\\":
                        index += 2
                        continue
                    index += 1
                if index < len(raw) and raw[index] == '"':
                    index += 1
                continue
            if char == open_char:
                depth += 1
            elif char == close_char:
                depth -= 1
                if depth == 0:
                    return index
            index += 1
        return None

    def _skip_type(self, pos: int) -> int | None:
        raw = self.text
        pos = self._skip_gap(pos)
        if pos >= len(raw):
            return None
        if self._at_word(pos, "function"):
            pos = self._skip_gap(pos + len("function"))
            if pos >= len(raw) or raw[pos] != "(":
                return None
            close = self._match_bracket(pos, "(", ")")
            if close is None:
                return None
            pos = self._skip_gap(close + 1)
            if not self._at_word(pos, "returns"):
                return None
            return self._skip_type(pos + len("returns"))
        if not self._is_ident_start(pos):
            return None
        pos = self._skip_ident(pos)
        while True:
            nxt = self._skip_gap(pos)
            if nxt < len(raw) and raw[nxt] == ".":
                name = self._skip_gap(nxt + 1)
                if not self._is_ident_start(name):
                    return None
                pos = self._skip_ident(name)
                continue
            if nxt < len(raw) and raw[nxt] == "[":
                close = self._match_bracket(nxt, "[", "]")
                if close is None:
                    return None
                pos = close + 1
                continue
            return pos


def _utf8_offset(chars: list[str], index: int) -> int:
    """The UTF-8 byte offset of `chars[index]`; each lone surrogate stands for one raw byte."""
    total = 0
    for char in chars[:index]:
        code = ord(char)
        if 0xD800 <= code <= 0xDFFF:
            total += 1
        else:
            total += len(char.encode("utf-8"))
    return total


def lex_source(source: Source) -> tuple[list[Token], list[Diagnostic]]:
    """The tokens of `source` and its lexical diagnostics."""
    lexer = Lexer(source, [], [])
    lexer.lex()
    return lexer.tokens, lexer.diagnostics


def lex_text(filename: str, text: str) -> tuple[Source, list[Token], list[Diagnostic]]:
    """Lex `text` as `filename`; the `Source` is returned for `parse_module`."""
    source = Source(filename, text)
    tokens, diagnostics = lex_source(source)
    return source, tokens, diagnostics
