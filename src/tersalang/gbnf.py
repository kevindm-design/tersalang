# SPDX-License-Identifier: Apache-2.0
"""Generate a GBNF grammar from spec/tersa.lark and recognize source with it.

The Lark file is the single source. `generate_gbnf` prints the committed
`spec/tersa.gbnf`. The recognizer reads that text back, so a stale file fails
the same way a hand-edited one would. A string is accepted when any derivation
consumes it, which is how llama.cpp keeps its grammar stacks.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from tersalang.lexer import CONTINUATION

HEADER_FULL = """\
# Generated from spec/tersa.lark by `tersa grammar --format gbnf`. Do not edit.
# Profile: full
#
# Standard llama.cpp GBNF: literals, character classes, sequences, ordered
# choice, ? * +, and {m,n}. No negative lookahead.
#
# `lower` is [a-z][a-z0-9_]* minus the reserved words, spelled out as a trie
# of rules. Every statement and declaration ends in `nl`: the end of a line,
# then any blank or comment lines. Each token's gap follows the hand lexer:
# `sgap` stays on the line, `gap` may break it (inside brackets and after a
# continuation token such as `+`, `,`, `=`, or `and`), and `sgap1`/`gap1`
# are non-empty, for a word after a word. Rules are copied per context:
# `-b` inside brackets, `-w` after a word, `-c` after a continuation, `-n`
# after an NL; `-e`/`-t` end at a line break or a token, `-some` is never
# empty, and `-loopN` rules repeat an arm. Float literals include an
# exponent with no dot (`1e10`). Text literals include the lexer's escapes.
#
# Caps, shared with `decoding` so a model cannot loop in a comment: a
# comment is at most 500 characters from its `#`. At most 100 full-line
# comments open the file, before its first token, and at most 30 sit
# between two lines of code. Blank lines are not capped here. A name is at
# most 64 characters (E0012), and a lower name has no `__` and no trailing
# `_` (E0010). See docs/gbnf.md.
"""

HEADER_DECODING = """\
# Generated from spec/tersa.lark by `tersa grammar --format gbnf`. Do not edit.
# Profile: decoding
#
# Standard llama.cpp GBNF. Same productions and layout rules as `full`, with
# stricter separators. A gap is empty or one space, plus one line break
# where `full` allows one. `nl` is that line break, so `do`, `uses`,
# `requires`, `ensures`, and a second statement need their own line.
#
# A line break is LF, an optional `  #` trailing comment, at most 30
# full-line comments with at most one blank line before each and one after
# the last, and an indent of pairs of spaces. That is what `tersa fmt`
# writes: no blank line opens the file and no two blank lines sit in a row.
# A comment is at most 500 characters from its `#`, and at most 100 `#`
# lines open the file. Tabs, CR, and a run of spaces between tokens are out.
# Keywords are reserved, and names follow E0010 and E0012, as in `full`.
#
# Not expressed here: operator, comma, and bracket spacing; which allowed
# line breaks the formatter uses; indentation depth; import order; the W1103
# parentheses; and the 100-column limit for code. Those stay with `tersa fmt`
# and the parser. See docs/gbnf.md.
"""


# Caps that keep a model from looping in comments, in both profiles. A
# comment is at most COMMENT_CHARS + 1 characters from its `#`. At most
# HEADER_LINES full-line comments open the file, before its first token, and
# at most COMMENT_LINES sit between two lines of code. `tersa fmt` keeps
# comments as written, so no finite cap accepts every formatted file; these
# are far above the corpus (87 characters, 7 lines) and leave room for a long
# license header. A model that keeps writing comments after its last
# declaration must stop or write code after COMMENT_LINES of them. Names
# follow the lexer: at most NAME_CHARS characters (E0012), and a lower name
# has no `__` and no trailing `_` (E0010).
COMMENT_CHARS = 499
HEADER_LINES = 100
COMMENT_LINES = 30
NAME_CHARS = 64


def repo_root() -> Path:
    """The nearest directory above this file that holds `spec/tersa.lark`."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "spec" / "tersa.lark").is_file():
            return parent
    raise FileNotFoundError("spec/tersa.lark")


def grammar_text(name: str) -> str:
    """The text of `spec/<name>`, such as `tersa.lark` or `tersa.ebnf`.

    A wheel carries copies in `tersalang/grammar/` (see `pyproject.toml`); a
    source checkout or editable install has only `spec/`.
    """
    bundled = resources.files("tersalang").joinpath("grammar", name)
    if bundled.is_file():
        return bundled.read_text(encoding="utf-8")
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "spec" / name
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    raise FileNotFoundError(f"spec/{name}")


def lark_source() -> str:
    """The text of `spec/tersa.lark`."""
    return grammar_text("tersa.lark")


def generate_gbnf(profile: str = "full") -> str:
    """Return the GBNF document for `profile`.

    Both profiles are standard llama.cpp GBNF. `decoding` keeps the same
    syntax and tightens the separator to the formatter's line breaks.
    """
    if profile not in {"full", "decoding"}:
        raise ValueError(f"unknown grammar profile {profile}")
    grammar = _convert(_parse_lark(lark_source()), profile)
    header = HEADER_DECODING if profile == "decoding" else HEADER_FULL
    lines = [header.rstrip(), ""]
    for name, node in grammar:
        lines.append(f"{name} ::= {_emit(node)}")
    lines.append("")
    return "\n".join(lines)


def cap_cases() -> list[tuple[str, str, bool]]:
    """Programs on each side of the comment caps, with the verdict both profiles give.

    Every program is `tersa fmt` output, so the decoding profile is held to
    the same verdict as `full`. The unit tests and `scripts/check_gbnf_llama.py`
    both run these, so llama.cpp is checked on the caps too.
    """

    def between(run: str) -> str:
        return f"module m\n\nlet x: Int = 1\n\n{run}let y: Int = 2\n"

    def body(lines: int) -> str:
        comments = "  # c\n" * lines
        return f"module m\n\nfunction main() returns Int\ndo\n{comments}  return 1\nend\n"

    header = "# h\n" * HEADER_LINES
    width = COMMENT_CHARS + 1
    return [
        (f"{HEADER_LINES}-line header", header + "module m\n", True),
        (f"{HEADER_LINES + 1}-line header", "# h\n" + header + "module m\n", False),
        (
            f"{HEADER_LINES}-line header with blank lines",
            "# h\n\n" * HEADER_LINES + "module m\n",
            True,
        ),
        (f"{COMMENT_LINES} comment lines after code", between("# c\n" * COMMENT_LINES), True),
        (
            f"{COMMENT_LINES + 1} comment lines after code",
            between("# c\n" * (COMMENT_LINES + 1)),
            False,
        ),
        (
            f"{COMMENT_LINES} spaced comment lines after code",
            between("# c\n\n" * COMMENT_LINES),
            True,
        ),
        (f"{COMMENT_LINES} comment lines in a body", body(COMMENT_LINES), True),
        (f"{COMMENT_LINES + 1} comment lines in a body", body(COMMENT_LINES + 1), False),
        (
            f"{HEADER_LINES}-line header then {COMMENT_LINES} lines after code",
            header + between("# c\n" * COMMENT_LINES),
            True,
        ),
        (f"{width}-character comment", between("#" + "w" * (width - 1) + "\n"), True),
        (f"{width + 1}-character comment", between("#" + "w" * width + "\n"), False),
    ]


def gbnf_accepts(grammar_text: str, source: str) -> bool:
    """True when some derivation of the grammar's `root` consumes all of `source`."""
    grammar = _parse_gbnf(grammar_text)
    return _Recognizer(grammar).accepts(source)


def llama_gbnf_accepts(grammar_text: str, source: str) -> bool:
    """Accept `source` only if `grammar_text` is stock llama.cpp GBNF.

    `( !rule )` is rejected before the recognizer runs. This is the check the
    unit tests use; `scripts/check_gbnf_llama.py` runs llama.cpp's own matcher.
    """
    if "(!" in grammar_text:
        raise ValueError("stock llama.cpp GBNF has no lookahead")
    return gbnf_accepts(grammar_text, source)


def gbnf_failure(grammar_text: str, source: str) -> str:
    """Empty when the grammar accepts `source`, else where the recognizer got furthest.

    The message gives the line and the character offset from the start of the
    file, then the next 40 characters.
    """
    grammar = _parse_gbnf(grammar_text)
    recognizer = _Recognizer(grammar)
    if recognizer.accepts(source):
        return ""
    line = source.count("\n", 0, recognizer.far) + 1
    return (
        f"stopped at {line}:{recognizer.far} near {source[recognizer.far : recognizer.far + 40]!r}"
    )


# --- Lark subset ---------------------------------------------------------------------


@dataclass
class _Seq:
    items: list[object]


@dataclass
class _Choice:
    options: list[object]


@dataclass
class _Atom:
    node: object
    suffix: str  # "", "?", "*", "+"


@dataclass
class _Name:
    text: str


@dataclass
class _Str:
    text: str


def _parse_lark(text: str) -> list[tuple[str, str, object]]:
    stripped = _strip_lark_comments(text)
    lines = stripped.splitlines()
    blocks: list[tuple[str, str]] = []
    name = ""
    body: list[str] = []
    for line in lines:
        if not line.strip() or line.startswith("%"):
            continue
        match = re.match(
            r"^[?]?(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?:\.\d+)?:[ \t]*(?P<body>.*)$", line
        )
        if match and not line.startswith((" ", "\t")):
            if name:
                blocks.append((name, " ".join(body)))
            name = match.group("name")
            body = [match.group("body")]
        else:
            body.append(line.strip())
    if name:
        blocks.append((name, " ".join(body)))
    parsed: list[tuple[str, str, object]] = []
    for rule_name, rule_body in blocks:
        if rule_body.startswith("/"):
            parsed.append((rule_name, "regex", rule_body))
        else:
            parsed.append((rule_name, "syntax", _LarkParser(rule_body).parse()))
    return parsed


def _strip_lark_comments(text: str) -> str:
    chars: list[str] = []
    index = 0
    while index < len(text):
        if text[index] == '"':
            end = index + 1
            while end < len(text) and text[end] != '"':
                if text[end] == "\\":
                    end += 2
                    continue
                end += 1
            chars.append(text[index : end + 1])
            index = end + 1
            continue
        if text.startswith("//", index):
            while index < len(text) and text[index] not in "\n":
                index += 1
            continue
        chars.append(text[index])
        index += 1
    return "".join(chars)


class _LarkParser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.index = 0

    def parse(self) -> object:
        node = self._choice()
        self._skip()
        if self.index < len(self.text):
            raise ValueError(f"unparsed lark syntax: {self.text[self.index :]!r}")
        return node

    def _choice(self) -> object:
        options = [self._seq()]
        while self._eat("|"):
            options.append(self._seq())
        if len(options) == 1:
            return options[0]
        return _Choice(options)

    def _seq(self) -> object:
        items: list[object] = []
        while True:
            self._skip()
            if self.index >= len(self.text) or self.text[self.index] in ")|]":
                break
            items.append(self._atom())
        if len(items) == 1:
            return items[0]
        return _Seq(items)

    def _atom(self) -> object:
        self._skip()
        if self._eat("("):
            node: object = self._choice()
            if not self._eat(")"):
                raise ValueError("unclosed group in lark grammar")
        elif self._eat("["):
            node = _Atom(self._choice(), "?")
            if not self._eat("]"):
                raise ValueError("unclosed optional in lark grammar")
        elif self.text[self.index] == '"':
            node = _Str(self._string())
        else:
            match = re.match(r"[A-Za-z_][A-Za-z0-9_]*", self.text[self.index :])
            if match is None:
                raise ValueError(f"bad lark token {self.text[self.index :]!r}")
            node = _Name(match.group(0))
            self.index += len(match.group(0))
        self._skip()
        if self.index < len(self.text) and self.text[self.index] in "?*+":
            node = _Atom(node, self.text[self.index])
            self.index += 1
        return node

    def _string(self) -> str:
        self.index += 1
        chars: list[str] = []
        while self.index < len(self.text) and self.text[self.index] != '"':
            if self.text[self.index] == "\\":
                chars.append(self.text[self.index + 1])
                self.index += 2
                continue
            chars.append(self.text[self.index])
            self.index += 1
        self.index += 1
        return "".join(chars)

    def _eat(self, token: str) -> bool:
        self._skip()
        if self.text.startswith(token, self.index):
            self.index += len(token)
            return True
        return False

    def _skip(self) -> None:
        while self.index < len(self.text) and self.text[self.index] in " \t":
            self.index += 1


# --- Convert to recognizer nodes -----------------------------------------------------


@dataclass(frozen=True)
class GLit:
    """A literal string."""

    text: str


@dataclass(frozen=True)
class GClass:
    """One character from a class. Each part is a character or a range such as `a-z`."""

    negated: bool
    parts: tuple[str, ...]


@dataclass(frozen=True)
class GRef:
    """A reference to the rule `name`."""

    name: str


@dataclass(frozen=True)
class GSeq:
    """Items matched one after another."""

    items: tuple[GNode, ...]


@dataclass(frozen=True)
class GChoice:
    """Alternatives. The recognizer keeps every option that matches, not just the first."""

    options: tuple[GNode, ...]


@dataclass(frozen=True)
class GRep:
    """`item` repeated; `kind` is `?`, `*`, `+`, or a bounded `{m,n}`."""

    item: GNode
    kind: str


@dataclass(frozen=True)
class GNot:
    """Negative lookahead `( !item )`: an empty match where `item` does not match.

    Stock llama.cpp has no lookahead. The generator never emits one, and
    `llama_gbnf_accepts` refuses a grammar that has one.
    """

    item: GNode


@dataclass(frozen=True)
class GTok:
    """A token before layout. `_Layout` replaces it with its gap and the token.

    `first_word` and `last_word` say whether the token starts or ends with a
    name character, and `cont` whether the hand lexer drops a newline after it.
    """

    node: GNode
    first_word: bool
    last_word: bool
    cont: bool


GNode = GLit | GClass | GRef | GSeq | GChoice | GRep | GNot | GTok


def _convert(rules: list[tuple[str, str, object]], profile: str) -> list[tuple[str, GNode]]:
    decoding = profile == "decoding"
    rules = _left_factor(rules)
    if not decoding:
        rules = _with_open_end(rules)
    syntax = {name: body for name, kind, body in rules if kind == "syntax"}
    tokens = frozenset(
        name for name, kind, _body in rules if kind == "regex" and name not in {"NL", "NAMED_ARG"}
    )
    lexical = _gaps(decoding)
    if decoding:
        # `break` is the formatter's line break: LF, the comment and blank
        # lines after it, and the next line's indent.
        lexical.extend(
            [
                (
                    "hash-rest",
                    GSeq((GLit("#"), GRep(GClass(True, ("\n",)), f"{{0,{COMMENT_CHARS}}}"))),
                ),
                ("indent", GRep(GLit("  "), "*")),
                ("trail", GSeq((GLit("  "), GRef("hash-rest")))),
                ("comment-line", GSeq((GRef("indent"), GRef("hash-rest"), GLit("\n")))),
                ("break", _decoding_break()),
                ("nl", GRef("break")),
                # `tersa fmt` drops leading blank lines and keeps at most one in a row.
                (
                    "banner",
                    GRep(
                        GSeq((GRef("hash-rest"), GLit("\n"), GRep(GLit("\n"), "?"))),
                        f"{{0,{HEADER_LINES}}}",
                    ),
                ),
            ]
        )
    else:
        # The lexer's NL token: the end of a line that has a token, then any
        # blank or comment-only lines, which make no token of their own.
        space = GRep(GClass(False, (" ", "\t")), "*")
        end = GSeq((GRep(GLit("\r"), "?"), GLit("\n")))
        lexical.extend(
            [
                ("comment", _comment_text()),
                ("eol", GSeq((space, GRep(GRef("comment"), "?"), end))),
                ("empty-line", GSeq((space, end))),
                ("comment-only", GSeq((space, GRef("comment"), end))),
                (
                    "banner",
                    _comment_run(GRep(GRef("empty-line"), "*"), GRef("comment-only"), HEADER_LINES),
                ),
                ("lines", _comment_run(GRep(GRef("empty-line"), "*"), GRef("comment-only"))),
                ("nl", GSeq((GRef("eol"), GRef("lines")))),
            ]
        )
    convert = _Converter(syntax, tokens)
    converted: dict[str, GNode] = {}
    terminals: dict[str, list[tuple[str, GNode]]] = {}
    order: list[str] = []
    for name, kind, body in rules:
        if name in {"start", "NL", "NAMED_ARG"}:
            # `nl` is defined above. NAMED_ARG's lookahead is replaced by the
            # `arg` choice below; an unused rule would still be parsed.
            continue
        gname = _gname(name)
        order.append(gname)
        if name == "arg":
            named = GSeq(
                (convert.token(GRef("lower")), convert.token(GLit("=")), GRef("expression"))
            )
            converted[gname] = GChoice((named, GRef("expression")))
        elif kind == "regex" and name == "LOWER":
            terminals[gname] = _lower_rules(reserved_words(str(body)))
        elif kind == "regex":
            terminals[gname] = [(gname, _regex_terminal(name, str(body)))]
        else:
            node = convert.node(body)
            if node is None:
                raise ValueError(f"rule {name} matches only newlines")
            converted[gname] = node
    start = next(body for name, _kind, body in rules if name == "start")
    root_body = convert.node(start)
    if root_body is None:
        raise ValueError("start rule is empty")
    layout = _Layout(converted)
    laid_out = layout.root(root_body)
    if decoding:
        # A formatted file may open with `#` lines. The last declaration's
        # `nl` consumes the final newline.
        root = GSeq((GRef("banner"), laid_out))
    else:
        # Blank and comment lines may open the file, up to HEADER_LINES
        # comments. It may end in spaces or a comment with no line break.
        root = GSeq((GRef("banner"), laid_out, GRef("sgap"), GRep(GRef("comment"), "?")))
    out: list[tuple[str, GNode]] = [("root", root), *lexical]
    for gname in order:
        out.extend(terminals.get(gname, ()))
        out.extend(layout.variants(gname))
    return _drop_unreferenced(out)


def _with_open_end(rules: list[tuple[str, str, object]]) -> list[tuple[str, str, object]]:
    """Let the full profile's file end without its last line break.

    The hand lexer accepts a missing final newline, but every declaration
    ends in `NL`, and GBNF cannot see the end of the input. `R_open` is `R`
    with its last `NL` optional. Only `start` uses the open rules, so `nl`
    stays required everywhere else.
    """
    syntax = {name: body for name, kind, body in rules if kind == "syntax"}
    opened: dict[str, object] = {}

    def nullable(node: object, seen: frozenset[str] = frozenset()) -> bool:
        if isinstance(node, _Atom):
            return node.suffix in {"?", "*"} or nullable(node.node, seen)
        if isinstance(node, _Seq):
            return all(nullable(item, seen) for item in node.items)
        if isinstance(node, _Choice):
            return any(nullable(item, seen) for item in node.options)
        if isinstance(node, _Name) and node.text in syntax and node.text not in seen:
            return nullable(syntax[node.text], seen | {node.text})
        return isinstance(node, _Str) and node.text == ""

    def ends_in_nl(node: object, seen: frozenset[str] = frozenset()) -> bool:
        if isinstance(node, _Name):
            if node.text == "NL":
                return True
            if node.text in syntax and node.text not in seen:
                return ends_in_nl(syntax[node.text], seen | {node.text})
            return False
        if isinstance(node, _Atom):
            return ends_in_nl(node.node, seen)
        if isinstance(node, _Choice):
            return any(ends_in_nl(item, seen) for item in node.options)
        if isinstance(node, _Seq) and node.items:
            last = node.items[-1]
            return ends_in_nl(last, seen) or (
                nullable(last) and ends_in_nl(_Seq(node.items[:-1]), seen)
            )
        return False

    def open_end(node: object) -> object:
        if not ends_in_nl(node):
            return node
        if isinstance(node, _Name):
            if node.text == "NL":
                return _Atom(node, "?")
            name = f"{node.text}_open"
            if name not in opened:
                opened[name] = node
                opened[name] = open_end(syntax[node.text])
            return _Name(name)
        if isinstance(node, _Choice):
            return _Choice([open_end(option) for option in node.options])
        if isinstance(node, _Atom):
            if node.suffix == "?":
                return _Atom(open_end(node.node), "?")
            # The last repetition is the open one.
            return _Seq([_Atom(node.node, "*"), open_end(node.node)])
        if isinstance(node, _Seq):
            head, last = node.items[:-1], node.items[-1]
            if isinstance(last, _Atom) and last.suffix == "*":
                last = _Atom(last.node, "+")
            with_last = _Seq([*head, open_end(last)])
            if not nullable(node.items[-1]) or not head:
                return with_last
            return _Choice([with_last, open_end(_Seq(list(head)))])
        return node

    rewritten = [
        (name, kind, open_end(body) if name == "start" else body) for name, kind, body in rules
    ]
    return rewritten + [(name, "syntax", body) for name, body in opened.items()]


def _left_factor(rules: list[tuple[str, str, object]]) -> list[tuple[str, str, object]]:
    """Rewrite the Lark oracle's tree-shaping alternatives without repeats.

    `a | a_tail` with `a_tail: a OP a (OP a)*` becomes `a (OP a)*`,
    `a | a_tail` with `a_tail: a X+` becomes `a X*`, and `a | a REST` becomes
    `a REST?`. The language is the same. llama.cpp keeps a stack for every
    alternative that still matches, so the unfactored form doubles the
    stacks at each precedence level of every expression.
    """
    syntax = {name: body for name, kind, body in rules if kind == "syntax"}
    factored: list[tuple[str, str, object]] = []
    for name, kind, body in rules:
        if kind == "syntax" and isinstance(body, _Choice) and len(body.options) == 2:
            body = _factor_pair(body.options[0], body.options[1], syntax) or body
        factored.append((name, kind, body))
    return factored


def _factor_pair(first: object, second: object, syntax: dict[str, object]) -> object | None:
    for base, other in ((first, second), (second, first)):
        if not isinstance(base, _Name):
            continue
        if isinstance(other, _Seq) and other.items and _same_symbol(other.items[0], base):
            rest = other.items[1:]
            return _Seq([base, _Atom(rest[0] if len(rest) == 1 else _Seq(rest), "?")])
        if not isinstance(other, _Name):
            continue
        tail = syntax.get(other.text)
        if not isinstance(tail, _Seq) or not tail.items or not _same_symbol(tail.items[0], base):
            continue
        items = tail.items
        if len(items) == 2 and isinstance(items[1], _Atom) and items[1].suffix == "+":
            return _Seq([base, _Atom(items[1].node, "*")])
        last = items[-1]
        if (
            len(items) >= 4
            and _same_symbol(items[-2], base)
            and isinstance(last, _Atom)
            and last.suffix == "*"
            and isinstance(last.node, _Seq)
            and len(last.node.items) == len(items) - 2
            and all(_same_symbol(a, b) for a, b in zip(last.node.items, items[1:-1], strict=True))
        ):
            return _Seq([base, last])
    return None


def _drop_unreferenced(rules: list[tuple[str, GNode]]) -> list[tuple[str, GNode]]:
    table = dict(rules)
    seen = {"root"}
    pending = ["root"]
    while pending:
        for ref in _refs(table[pending.pop()]):
            if ref not in seen:
                seen.add(ref)
                pending.append(ref)
    return [(name, node) for name, node in rules if name in seen]


def _refs(node: GNode) -> list[str]:
    if isinstance(node, GRef):
        return [node.name]
    if isinstance(node, GSeq):
        return [ref for item in node.items for ref in _refs(item)]
    if isinstance(node, GChoice):
        return [ref for item in node.options for ref in _refs(item)]
    if isinstance(node, (GRep, GNot)):
        return _refs(node.item)
    return []


def _decoding_break() -> GNode:
    # At most one blank line in a row, as `tersa fmt` writes them.
    return GSeq(
        (
            GRep(GRef("trail"), "?"),
            GLit("\n"),
            GRep(GSeq((GRep(GLit("\n"), "?"), GRef("comment-line"))), f"{{0,{COMMENT_LINES}}}"),
            GRep(GLit("\n"), "?"),
            GRef("indent"),
        )
    )


def _comment_run(filler: GNode, comment: GNode, limit: int = COMMENT_LINES) -> GNode:
    """`filler`, then at most `limit` comments, each followed by `filler`."""
    return GSeq((filler, GRep(GSeq((comment, filler)), f"{{0,{limit}}}")))


def _gaps(decoding: bool) -> list[tuple[str, GNode]]:
    """The four separators `_Layout` puts in front of a token.

    `gap` may break the line: the hand lexer drops a newline inside brackets
    and after a continuation token. `sgap` stays on the line, because any
    other newline is an NL token. `gap1` and `sgap1` are the same without
    the empty match, for a word after a word.
    """
    if decoding:
        # One space or one line break and its indent. Not two spaces, not a
        # tab. Comment and blank lines belong to `nl`, so a gap cannot add a
        # second run of them after a statement.
        loose = (GLit(" "), GSeq((GLit("\n"), GRef("indent"))))
        return [
            ("gap", GChoice((*loose, GLit("")))),
            ("gap1", GChoice(loose)),
            ("sgap", GChoice((GLit(" "), GLit("")))),
            ("sgap1", GLit(" ")),
        ]
    # A comment runs to its line break; otherwise `# a function` would end
    # before the keyword. A gap holds at most COMMENT_LINES comments.
    newline = GChoice((GLit("\r\n"), GLit("\n")))
    space = GClass(False, (" ", "\t"))
    breaks = GRep(GSeq((newline, GRep(space, "*"))), "*")
    return [
        ("gap-c", GSeq((GRef("comment"), newline, GRep(space, "*")))),
        ("gap-b", breaks),
        ("gap", GSeq((GRep(space, "*"), _comment_run(GRef("gap-b"), GRef("gap-c"))))),
        (
            "gap1",
            GChoice(
                (
                    GSeq((GRep(space, "+"), _comment_run(GRef("gap-b"), GRef("gap-c")))),
                    GSeq((newline, GRep(space, "*"), _comment_run(GRef("gap-b"), GRef("gap-c")))),
                    GSeq(
                        (
                            GRef("gap-c"),
                            _comment_run(GRef("gap-b"), GRef("gap-c"), COMMENT_LINES - 1),
                        )
                    ),
                )
            ),
        ),
        ("sgap", GRep(space, "*")),
        ("sgap1", GRep(space, "+")),
    ]


def _comment_text() -> GNode:
    return GSeq((GLit("#"), GRep(GClass(True, ("\n", "\r")), f"{{0,{COMMENT_CHARS}}}")))


def reserved_words(lower_regex: str) -> tuple[str, ...]:
    """The keywords in the negative lookahead of Lark's `LOWER` pattern."""
    match = re.search(r"\(\?!\(\?:([a-z|]+)\)\\b\)", lower_regex)
    if match is None:
        return ()
    return tuple(sorted(set(match.group(1).split("|"))))


_WORD_START = "abcdefghijklmnopqrstuvwxyz"
_WORD_REST = _WORD_START + "0123456789_"


def _lower_rules(words: tuple[str, ...]) -> list[tuple[str, GNode]]:
    """`lower` without lookahead: a trie over the reserved words.

    `lower-PREFIX` matches the rest of a name that starts with PREFIX. It
    may stop when PREFIX is not a keyword, step to the next trie node on a
    keyword's next letter, or take any other name character and then a
    `name-N` tail. Each name has exactly one derivation, so llama.cpp keeps
    one stack per name.

    The lexer's name rules are encoded too: a name has at most NAME_CHARS
    characters (E0012), and an `_` is always followed by a letter or digit,
    so there is no `__` and no trailing `_` (E0010). `name-N` is a tail of at
    most N more characters after a letter or digit.
    """
    alnum = GClass(False, ("a-z", "0-9"))
    prefixes = sorted({word[:index] for word in words for index in range(len(word))})
    nodes = set(prefixes)
    rules: list[tuple[str, GNode]] = []
    used: set[int] = set()

    def tail(budget: int) -> GNode:
        used.add(max(budget, 0))
        return GRef(f"name-{max(budget, 0)}")

    def after(char_class: GClass, budget: int) -> GNode:
        """One character of `char_class`, then a tail, within `budget` characters."""
        return GSeq((char_class, tail(budget - 1)))

    def underscore(budget: int) -> GNode:
        return GSeq((GLit("_"), alnum, tail(budget - 2)))

    for prefix in prefixes:
        budget = NAME_CHARS - len(prefix)
        children = sorted(
            {
                word[len(prefix)]
                for word in words
                if word.startswith(prefix) and len(word) > len(prefix)
            }
        )
        options: list[GNode] = []
        for char in children:
            step = prefix + char
            if step in nodes:
                options.append(GSeq((GLit(char), GRef(_lower_name(step)))))
            else:
                # `step` is a keyword and no other keyword extends it.
                rest = budget - 1
                more = [after(alnum, rest)]
                if rest >= 2:
                    more.append(underscore(rest))
                options.append(
                    GSeq((GLit(char), GChoice(tuple(more)) if len(more) > 1 else more[0]))
                )
        alphabet = _WORD_REST if prefix else _WORD_START
        others = [c for c in alphabet if c not in children and c != "_"]
        options.append(after(_char_class(others), budget))
        if prefix and "_" not in children and budget >= 2:
            options.append(underscore(budget))
        if prefix and prefix not in words:
            options.append(GLit(""))
        rules.append(
            (_lower_name(prefix), options[0] if len(options) == 1 else GChoice(tuple(options)))
        )
    if not prefixes:
        rules.append(("lower", after(GClass(False, ("a-z",)), NAME_CHARS)))
    for budget in range(max(used, default=0), -1, -1):
        options = []
        if budget >= 1:
            options.append(GSeq((alnum, GRef(f"name-{budget - 1}"))))
        if budget >= 2:
            options.append(GSeq((GLit("_"), alnum, GRef(f"name-{budget - 2}"))))
        options.append(GLit(""))
        rules.append(
            (f"name-{budget}", options[0] if len(options) == 1 else GChoice(tuple(options)))
        )
    return rules


def _lower_name(prefix: str) -> str:
    return f"lower-{prefix}" if prefix else "lower"


def _char_class(chars: Iterable[str]) -> GClass:
    """A class of the given characters, with runs written as ranges."""
    ordered = sorted(set(chars))
    parts: list[str] = []
    index = 0
    while index < len(ordered):
        end = index
        while end + 1 < len(ordered) and ord(ordered[end + 1]) == ord(ordered[end]) + 1:
            end += 1
        if end - index >= 2:
            parts.append(f"{ordered[index]}-{ordered[end]}")
        else:
            parts.extend(ordered[index : end + 1])
        index = end + 1
    return GClass(False, tuple(parts))


def _regex_terminal(name: str, body: str) -> GNode:
    pattern = body.strip()
    if pattern.startswith("/") and pattern.endswith("/"):
        pattern = pattern[1:-1]
    if name == "UPPER":
        return GSeq(
            (
                GClass(False, ("A-Z",)),
                GRep(GClass(False, ("A-Z", "a-z", "0-9")), f"{{0,{NAME_CHARS - 1}}}"),
            )
        )
    if name == "INT":
        return GChoice(
            (
                GSeq(
                    (
                        GLit("0x"),
                        GClass(False, ("0-9", "a-f", "A-F")),
                        GRep(GClass(False, ("0-9", "a-f", "A-F", "_")), "*"),
                    )
                ),
                GSeq(
                    (
                        GLit("0b"),
                        GClass(False, ("0-1",)),
                        GRep(GClass(False, ("0-1", "_")), "*"),
                    )
                ),
                GSeq((GClass(False, ("0-9",)), GRep(GClass(False, ("0-9", "_")), "*"))),
            )
        )
    if name == "FLOAT":
        digits = GSeq((GClass(False, ("0-9",)), GRep(GClass(False, ("0-9", "_")), "*")))
        exponent = GSeq(
            (
                GLit("e"),
                GRep(GChoice((GLit("+"), GLit("-"))), "?"),
                GClass(False, ("0-9",)),
                GRep(GClass(False, ("0-9",)), "*"),
            )
        )
        # A dot form and a bare exponent (`1e10`). The dotted form is first
        # so `1.0` is not split into an integer and a leftover.
        return GChoice(
            (
                GSeq((digits, GLit("."), digits, GRep(exponent, "?"))),
                GSeq((digits, exponent)),
            )
        )
    if name == "TEXT":
        return _text_literal()
    if name == "NL":
        return GRef("nl")
    raise ValueError(f"cannot translate terminal {name}: {pattern}")


def _text_literal() -> GNode:
    # Lexer escapes: \" \\ \n \t \r \{ \} and \u{1 to 6 hex digits}.
    # A raw newline or CR ends the literal. Unknown escapes are a lexer
    # error; this rule does not have to accept them.
    simple = GChoice(tuple(GLit(char) for char in ('"', "\\", "n", "t", "r", "{", "}")))
    hexdigit = GClass(False, ("0-9", "a-f", "A-F"))
    unicode_escape = GSeq(
        (
            GLit("u"),
            GLit("{"),
            hexdigit,
            GRep(hexdigit, "?"),
            GRep(hexdigit, "?"),
            GRep(hexdigit, "?"),
            GRep(hexdigit, "?"),
            GRep(hexdigit, "?"),
            GLit("}"),
        )
    )
    escape = GSeq((GLit("\\"), GChoice((simple, unicode_escape))))
    char = GChoice((escape, GClass(True, ('"', "\\", "\n", "\r"))))
    return GSeq((GLit('"'), GRep(char, "*"), GLit('"')))


class _Converter:
    """Lark syntax to GBNF nodes, with each token wrapped in a `GTok`.

    Layout comes later, so a token's gap depends on the token before it.

    `NL` is a required line break in both profiles. Without it two names
    could sit side by side, so `end` would also read as the statements `e`
    and `nd`, and llama.cpp's stacks grow with every way to split a word.
    """

    def __init__(self, syntax: dict[str, object], tokens: frozenset[str]) -> None:
        self.syntax = syntax
        self.tokens = tokens

    def token(self, node: GNode) -> GNode:
        if isinstance(node, GLit):
            text = node.text
            return GTok(node, _word_char(text[0]), _word_char(text[-1]), text in CONTINUATION)
        word = not (isinstance(node, GRef) and node.name == "text")
        return GTok(node, word, word, False)

    def node(self, node: object) -> GNode | None:
        if isinstance(node, _Choice):
            converted = [self.node(option) for option in _reorder_choice(node, self.syntax)]
            options = _float_before_int([option for option in converted if option is not None])
            if not options:
                return None
            choice = options[0] if len(options) == 1 else GChoice(tuple(options))
            return _repeat(choice, "?") if len(options) < len(converted) else choice
        if isinstance(node, _Seq):
            items: list[GNode] = []
            for part in node.items:
                item = self.node(part)
                if isinstance(item, GSeq):
                    items.extend(item.items)
                elif item is not None:
                    items.append(item)
            if not items:
                return None
            return items[0] if len(items) == 1 else GSeq(tuple(items))
        if isinstance(node, _Atom):
            inner = self.node(node.node)
            if inner is None or node.suffix == "":
                return inner
            return _repeat(inner, node.suffix)
        if isinstance(node, _Name):
            if node.text == "NL":
                return GRef("nl")
            ref = GRef(_gname(node.text))
            return self.token(ref) if node.text in self.tokens else ref
        if isinstance(node, _Str):
            return self.token(GLit(node.text))
        raise TypeError(type(node).__name__)


def _word_char(char: str) -> bool:
    return char.isascii() and (char.isalnum() or char == "_")


# (ends in a name character, is a continuation token, just had an NL).
# A file starts in LINE_START, and so does every line after an NL.
State = tuple[bool, bool, bool]
LINE_START: State = (False, False, True)
_OPEN = frozenset({"(", "[", "{"})
_CLOSE = frozenset({")", "]", "}"})


def _merge(states: Iterable[State]) -> State:
    """The strictest of several states: a word or an NL if any is, a continuation if all are."""
    listed = list(states)
    return (
        any(state[0] for state in listed),
        all(state[1] for state in listed),
        any(state[2] for state in listed),
    )


class _Layout:
    """Put the hand lexer's layout rules into the grammar.

    GBNF has no lexer, so each token's gap depends on what came before it:

    - after a name character, a word needs a non-empty gap (`sgap1` or
      `gap1`), so `functions` is never `function s`;
    - outside brackets a gap stays on the line (`sgap`), because the lexer
      turns that newline into NL. Inside brackets and after a continuation
      token it may break the line (`gap`). A lambda body is outside again;
    - NL never follows NL. Blank and comment lines make no token, so the
      Lark rules that match a bare NL (`NL*`, `statement? NL`) only apply
      after a token such as `then`. One `nl` holds every blank line, which
      is what lets the decoding profile cap them.

    A rule is copied once per context it is used in: `-b` inside brackets,
    `-w` after a word, `-c` after a continuation, `-n` after an NL. When a
    rule can end either way, the next gap assumes the strictest case. So
    `f(x)and y` needs a space before `and`, and `x and(y)` is fine.
    """

    def __init__(self, rules: dict[str, GNode]) -> None:
        self.rules = dict(rules)
        self.first_word: dict[str, bool] = dict.fromkeys(rules, False)
        self.first_nl: dict[str, bool] = dict.fromkeys(rules, False)
        self.nullable: dict[str, bool] = dict.fromkeys(rules, False)
        self.last: dict[str, frozenset[State]] = dict.fromkeys(rules, frozenset())
        self.names: dict[tuple[str, bool, State, str], str] = {}
        self.bodies: dict[str, GNode] = {}
        self.queue: list[tuple[str, bool, State, str]] = []
        self.loops: dict[tuple[GNode, bool, State], dict[State, GNode | None]] = {}
        self.helpers: dict[str, list[str]] = {}
        self.owner = "root"
        changed = True
        while changed:
            changed = False
            for name, node in rules.items():
                found = (*self._first(node), self._last(node)[0])
                if found != (
                    self.first_word[name],
                    self.first_nl[name],
                    self.nullable[name],
                    self.last[name],
                ):
                    (
                        self.first_word[name],
                        self.first_nl[name],
                        self.nullable[name],
                        self.last[name],
                    ) = found
                    changed = True
        # A rule that can be empty gets a copy that cannot, `R-some`. A
        # reference to R is then `R-some?`, so the empty case keeps the state
        # before it instead of merging with the state R ends in.
        for name in [name for name in rules if self.nullable[name]]:
            some = self._nonempty(rules[name])
            if some is None:
                raise ValueError(f"rule {name} matches only the empty string")
            self.rules[f"{name}-some"] = some
            self.first_word[f"{name}-some"], self.first_nl[f"{name}-some"], _ = self._first(some)
            self.nullable[f"{name}-some"] = False
            self.last[f"{name}-some"] = self.last[name]

    def root(self, node: GNode) -> GNode:
        laid = self._single(node, False, LINE_START)
        while self.queue:
            key = self.queue.pop(0)
            name, bracket, state, end = key
            self.owner = self.names[key]
            body: GNode | None = None
            if end:
                split = self._split_rule(name, bracket, state)
                body = _alt(
                    [laid for out, laid in split.items() if (out == LINE_START) == (end == "e")]
                )
            elif (
                single := self._single(
                    self.rules[name], bracket, state, lambda_rule=name == "lambda"
                )
            ) is not None:
                body = single[1]
            if body is None:
                raise ValueError(f"rule {name} matches nothing after {state}")
            self.bodies[self.owner] = body
        if laid is None or laid[1] is None:
            raise ValueError("start rule is empty")
        return laid[1]

    def variants(self, name: str) -> list[tuple[str, GNode]]:
        keys = sorted(key for key in self.names if key[0] in {name, f"{name}-some"})
        return [rule for key in keys for rule in self.with_helpers(self.names[key])]

    def with_helpers(self, label: str) -> list[tuple[str, GNode]]:
        rules = [(label, self.bodies[label])] if label in self.bodies else []
        return rules + [(helper, self.bodies[helper]) for helper in self.helpers.get(label, [])]

    def _nonempty(self, node: GNode) -> GNode | None:
        """`node` without its empty match. None when that is all it matches."""
        if isinstance(node, GRef):
            return GRef(f"{node.name}-some") if self.nullable.get(node.name) else node
        if isinstance(node, GSeq):
            options: list[GNode | None] = []
            for index, item in enumerate(node.items):
                head = self._nonempty(item)
                if head is not None:
                    options.append(_cat(head, *node.items[index + 1 :]))
                if not self._first(item)[2]:
                    break
            return _alt(options) if options else None
        if isinstance(node, GChoice):
            kept: list[GNode | None] = [
                found for option in node.options if (found := self._nonempty(option)) is not None
            ]
            return _alt(kept) if kept else None
        if isinstance(node, GRep):
            head = self._nonempty(node.item)
            if head is None:
                return None
            if node.kind == "?":
                return head
            if node.kind in {"*", "+"}:
                return _cat(head, _repeat(node.item, "*"))
            raise ValueError(f"cannot drop the empty match of {node.kind}")
        if isinstance(node, GLit) and node.text == "":
            return None
        return node

    def _first(self, node: GNode) -> tuple[bool, bool, bool]:
        """Can `node` start with a name character, with an NL, and can it be empty."""
        if isinstance(node, GTok):
            return node.first_word, False, False
        if isinstance(node, GRef):
            if node.name in self.rules:
                return (
                    self.first_word[node.name],
                    self.first_nl[node.name],
                    self.nullable[node.name],
                )
            return False, node.name == "nl", False
        if isinstance(node, GSeq):
            word = newline = False
            for item in node.items:
                item_word, item_nl, item_nullable = self._first(item)
                word, newline = word or item_word, newline or item_nl
                if not item_nullable:
                    return word, newline, False
            return word, newline, True
        if isinstance(node, GChoice):
            found = [self._first(option) for option in node.options]
            return tuple(any(parts) for parts in zip(*found, strict=True))  # type: ignore[return-value]
        if isinstance(node, GRep):
            word, newline, nullable = self._first(node.item)
            return word, newline, nullable or node.kind != "+"
        return False, False, isinstance(node, GLit) and node.text == ""

    def _last(self, node: GNode) -> tuple[frozenset[State], bool]:
        """The states `node` can end in, and whether it can be empty."""
        if isinstance(node, GTok):
            return frozenset({(node.last_word, node.cont, False)}), False
        if isinstance(node, GRef):
            if node.name in self.rules:
                return self.last[node.name], self.nullable[node.name]
            return frozenset({LINE_START}), False
        if isinstance(node, GSeq):
            states: set[State] = set()
            for item in reversed(node.items):
                item_states, item_nullable = self._last(item)
                states |= item_states
                if not item_nullable:
                    return frozenset(states), False
            return frozenset(states), True
        if isinstance(node, GChoice):
            found = [self._last(option) for option in node.options]
            return frozenset().union(*(states for states, _ in found)), any(
                empty for _, empty in found
            )
        if isinstance(node, GRep):
            rep_states, nullable = self._last(node.item)
            return rep_states, nullable or node.kind != "+"
        return frozenset(), isinstance(node, GLit) and node.text == ""

    def _variant(self, name: str, bracket: bool, state: State, end: str = "") -> str:
        context = (
            state[0] and self.first_word[name],
            state[1] and not bracket,
            state[2] and self.first_nl[name],
        )
        key = (name, bracket, context, end)
        if key not in self.names:
            flags = ("b", "w", "c", "n")
            suffix = (
                "".join(flag for flag, on in zip(flags, (bracket, *context), strict=True) if on)
                + end
            )
            label = f"{_gname(name)}-{suffix}" if suffix else _gname(name)
            if suffix and label in self.rules:
                raise ValueError(f"rule {label} clashes with a layout copy of {name}")
            self.names[key] = label
            self.queue.append(key)
        return self.names[key]

    def _single(
        self, node: GNode, bracket: bool, state: State, lambda_rule: bool = False
    ) -> tuple[State, GNode | None] | None:
        """Lay out `node` as one alternative. None when nothing fits after `state`."""
        if isinstance(node, GSeq):
            shared, pending = self._seq(node.items, bracket, state, lambda_rule)
            if not pending:
                return None
            return _merge(pending), _cat(*shared, self._rejoin(list(pending.values())))
        if isinstance(node, GChoice):
            found = [
                laid for option in node.options if (laid := self._single(option, bracket, state))
            ]
            if not found:
                return None
            return _merge(out for out, _ in found), _alt([laid for _, laid in found])
        split = self._split(node, bracket, state)
        if not split:
            return None
        return _merge(split), self._rejoin(list(split.values()))

    def _split(self, node: GNode, bracket: bool, state: State) -> dict[State, GNode | None]:
        """Lay out `node` after `state`, grouped by the state it ends in.

        A None value is an empty match; an empty dict means nothing fits.
        """
        if isinstance(node, GTok):
            loose = bracket or state[1]
            gap = ("gap" if loose else "sgap") + ("1" if state[0] and node.first_word else "")
            return {(node.last_word, node.cont, False): GSeq((GRef(gap), node.node))}
        if isinstance(node, GRef):
            if node.name == "nl":
                return {} if state[2] else {LINE_START: node}
            if node.name not in self.rules:
                return {state: node}
            body = self.rules[node.name]
            if (
                isinstance(body, GChoice)
                and len(self.last[node.name]) > 1
                and all(isinstance(option, GTok) for option in body.options)
            ):
                # `mul-op`: `*` and `div` need different gaps after them.
                return self._split(body, bracket, state)
            if self.nullable[node.name]:
                some = self._split(GRef(f"{node.name}-some"), bracket, state)
                return (
                    {**some, state: _alt([some[state], None])}
                    if state in some
                    else {**some, state: None}
                )
            last = self.last[node.name]
            if LINE_START in last and len(last) > 1:
                # `else` after an arm: the arm ends at NL or right after `then`.
                return {
                    LINE_START: GRef(self._variant(node.name, bracket, state, "e")),
                    _merge(last - {LINE_START}): GRef(
                        self._variant(node.name, bracket, state, "t")
                    ),
                }
            return {_merge(last): GRef(self._variant(node.name, bracket, state))}
        if isinstance(node, GSeq):
            shared, pending = self._seq(node.items, bracket, state)
            return {out: _cat(*shared, laid) for out, laid in pending.items()}
        if isinstance(node, GChoice):
            grouped: dict[State, list[GNode | None]] = {}
            for option in node.options:
                for out, laid in self._split(option, bracket, state).items():
                    grouped.setdefault(out, []).append(laid)
            return {out: _alt(options) for out, options in grouped.items()}
        if isinstance(node, GRep) and node.kind == "?":
            grouped = {state: [None]}
            for out, laid in self._split(node.item, bracket, state).items():
                grouped.setdefault(out, []).append(laid)
            return {out: _alt(options) for out, options in grouped.items()}
        if isinstance(node, GRep):
            return self._repeat(node, bracket, state)
        return {state: None if isinstance(node, GLit) and node.text == "" else node}

    def _rejoin(self, options: list[GNode | None]) -> GNode | None:
        """Undo a split nobody needed: `R-e | R-t` is `R`, with one shared prefix."""
        keys = {label: key for key, label in self.names.items()}
        heads: list[tuple[GNode, ...]] = []
        tails: list[tuple[str, bool, State, str]] = []
        for option in options:
            items = option.items if isinstance(option, GSeq) else (option,)
            last = items[-1] if items else None
            key = keys.get(last.name) if isinstance(last, GRef) else None
            if key is None or not key[3]:
                return _alt(options)
            heads.append(items[:-1])
            tails.append(key)
        if len(tails) != 2 or any(head != heads[0] for head in heads):
            return _alt(options)
        if {key[3] for key in tails} != {"e", "t"} or len({key[:3] for key in tails}) != 1:
            return _alt(options)
        name, bracket, context, _end = tails[0]
        return _cat(*heads[0], GRef(self._variant(name, bracket, context)))

    def _split_rule(self, name: str, bracket: bool, state: State) -> dict[State, GNode | None]:
        context = (
            state[0] and self.first_word[name],
            state[1] and not bracket,
            state[2] and self.first_nl[name],
        )
        return self._split(self.rules[name], bracket, context)

    def _repeat(self, node: GRep, bracket: bool, state: State) -> dict[State, GNode | None]:
        """A loop whose passes start where the one before ended.

        When every pass lays out the same, this is `x*`. Otherwise it is a
        chain of helper rules, one per start and end state, so the block
        after `then` may open with a bare NL and the next arm still sees
        whether the last one ended at a line break.
        """
        key = (node, bracket, state)
        if key in self.loops:
            return self.loops[key]
        table: dict[State, dict[State, GNode]] = {}
        frontier = [state]
        while frontier:
            start = frontier.pop()
            if start in table:
                continue
            table[start] = {
                out: laid
                for out, laid in self._split(node.item, bracket, start).items()
                if laid is not None
            }
            frontier.extend(out for out in table[start] if out not in table)
        passes = list(table.values())
        result: dict[State, GNode | None]
        if len(passes[0]) <= 1 and all(found == passes[0] for found in passes):
            result = {}
            for out, body in passes[0].items():
                result[out] = _repeat(body, "+")
        else:
            ends: dict[State, set[State]] = {start: set(found) for start, found in table.items()}
            changed = True
            while changed:
                changed = False
                for start, found in table.items():
                    grown = ends[start].union(*(ends[out] for out in found))
                    if grown != ends[start]:
                        ends[start], changed = grown, True
            labels = {
                (start, end): f"{self.owner}-loop{len(self.helpers.get(self.owner, [])) + index}"
                for index, (start, end) in enumerate(
                    (start, end) for start in table for end in sorted(ends[start])
                )
            }
            self.helpers.setdefault(self.owner, []).extend(labels.values())
            for (start, end), label in labels.items():
                options: list[GNode | None] = []
                for out, laid in table[start].items():
                    if out == end:
                        options.append(laid)
                    if end in ends[out]:
                        options.append(_cat(laid, GRef(labels[(out, end)])))
                helper_body = _alt(options)
                assert helper_body is not None
                self.bodies[label] = helper_body
            result = {end: GRef(labels[(state, end)]) for end in ends[state]}
        if node.kind != "+":
            result[state] = _alt([result.get(state), None]) if state in result else None
            if state in result and isinstance(result[state], GRep) and len(passes[0]) == 1:
                result[state] = _repeat(next(iter(passes[0].values())), "*")
        self.loops[key] = result
        return result

    def _seq(
        self, items: tuple[GNode, ...], bracket: bool, state: State, lambda_rule: bool = False
    ) -> tuple[list[GNode | None], dict[State, GNode | None]]:
        """Lay out a sequence, keeping one branch per end state only while it matters."""
        shared: list[GNode | None] = []
        pending: dict[State, GNode | None] = {state: None}
        depth = 0
        past_params = False
        for item in items:
            text = item.node.text if isinstance(item, GTok) and isinstance(item.node, GLit) else ""
            inside = depth > 0 or (bracket and not past_params)
            laid = {
                start: found for start in pending if (found := self._split(item, inside, start))
            }
            if not laid:
                return shared, {}
            first = next(iter(laid.values()))
            if len(laid) == len(pending) and all(found == first for found in laid.values()):
                shared.append(self._rejoin(list(pending.values())))
                pending = dict(first)
            else:
                grouped: dict[State, list[GNode | None]] = {}
                for start, after_start in laid.items():
                    for out, after in after_start.items():
                        grouped.setdefault(out, []).append(_cat(pending[start], after))
                pending = {out: _alt(options) for out, options in grouped.items()}
            if text in _OPEN:
                depth += 1
            elif text in _CLOSE:
                depth -= 1
                # The lexer counts a lambda's body from its parameter `)`.
                past_params = past_params or (lambda_rule and depth == 0)
        if depth:
            raise ValueError("unbalanced brackets in a grammar sequence")
        return shared, pending


def _cat(*parts: GNode | None) -> GNode | None:
    items: list[GNode] = []
    for part in parts:
        if isinstance(part, GSeq):
            items.extend(part.items)
        elif part is not None:
            items.append(part)
    if not items:
        return None
    return items[0] if len(items) == 1 else GSeq(tuple(items))


def _alt(options: list[GNode | None]) -> GNode | None:
    kept: list[GNode] = []
    empty = False
    for option in options:
        if option is None:
            empty = True
            continue
        for part in option.options if isinstance(option, GChoice) else (option,):
            if part not in kept:
                kept.append(part)
    if not kept:
        return None
    choice = kept[0] if len(kept) == 1 else GChoice(tuple(kept))
    return _repeat(choice, "?") if empty else choice


def _repeat(node: GNode, kind: str) -> GNode:
    """Repeat `node` without nesting repeats.

    `(x?)*` would let llama.cpp repeat an empty match. Equal suffixes stay; any
    mixed pair (`x?*`, `x*?`, `x+?`, ...) is `x*`.
    """
    if isinstance(node, GRep):
        return node if node.kind == kind else GRep(node.item, "*")
    return GRep(node, kind)


def _reorder_choice(node: _Choice, syntax: dict[str, object]) -> list[object]:
    """PEG must try the longer alternative first when another one is its prefix."""
    snapshot = list(node.options)

    def rank(option: object) -> int:
        return sum(
            1
            for other in snapshot
            if other is not option and _is_prefix_alt(option, other, syntax, 0)
        )

    options = sorted(snapshot, key=rank, reverse=True)
    ctor = next(
        (index for index, option in enumerate(options) if _lark_name(option) == "ctor_pattern"),
        None,
    )
    lower = next(
        (index for index, option in enumerate(options) if _lark_name(option) == "LOWER"), None
    )
    if ctor is not None and lower is not None and ctor > lower:
        chosen = options.pop(ctor)
        lower = next(index for index, option in enumerate(options) if _lark_name(option) == "LOWER")
        options.insert(lower, chosen)
    return options


def _lark_name(node: object) -> str:
    if isinstance(node, _Name):
        return node.text
    return ""


def _is_prefix_alt(longer: object, shorter: object, syntax: dict[str, object], depth: int) -> bool:
    if depth > 6:
        return False
    expanded = longer
    if isinstance(longer, _Name) and longer.text in syntax:
        expanded = syntax[longer.text]
    items = list(expanded.items) if isinstance(expanded, _Seq) else [expanded]
    if not items:
        return False
    first = items[0]
    if isinstance(first, _Atom) and first.suffix == "?":
        if _same_symbol(first.node, shorter) or _is_prefix_alt(
            first.node, shorter, syntax, depth + 1
        ):
            return True
        rest = items[1:]
        if not rest:
            return False
        nxt: object = rest[0] if len(rest) == 1 else _Seq(rest)
        return _is_prefix_alt(nxt, shorter, syntax, depth + 1)
    if _same_symbol(first, shorter):
        return True
    if isinstance(first, _Name) and first.text in syntax:
        return _is_prefix_alt(first, shorter, syntax, depth + 1)
    return False


def _same_symbol(left: object, right: object) -> bool:
    if isinstance(left, _Name) and isinstance(right, _Name):
        return left.text == right.text
    if isinstance(left, _Str) and isinstance(right, _Str):
        return left.text == right.text
    return False


def _contains_ref(node: GNode, name: str) -> bool:
    if isinstance(node, GRef):
        return node.name == name
    if isinstance(node, GSeq):
        return any(_contains_ref(item, name) for item in node.items)
    if isinstance(node, GChoice):
        return any(_contains_ref(item, name) for item in node.options)
    if isinstance(node, GRep):
        return _contains_ref(node.item, name)
    if isinstance(node, (GNot, GTok)):
        return _contains_ref(node.item if isinstance(node, GNot) else node.node, name)
    return False


def _float_before_int(options: list[GNode]) -> list[GNode]:
    """Lark gives FLOAT priority over INT. PEG must try the longer token first."""
    floats = [
        item for item in options if _contains_ref(item, "float") and not _contains_ref(item, "int")
    ]
    ints = [
        item for item in options if _contains_ref(item, "int") and not _contains_ref(item, "float")
    ]
    if not floats or not ints:
        return options
    rest = [item for item in options if item not in floats and item not in ints]
    return floats + ints + rest


def _gname(name: str) -> str:
    return name.replace("_", "-").lower()


# --- Emit and parse GBNF -------------------------------------------------------------


def _emit(node: object) -> str:
    if isinstance(node, GLit):
        return _quote(node.text)
    if isinstance(node, GClass):
        body = "".join(_escape_class(part) for part in node.parts)
        return f"[^{body}]" if node.negated else f"[{body}]"
    if isinstance(node, GRef):
        return node.name
    if isinstance(node, GSeq):
        return " ".join(_emit_atom(item) for item in node.items)
    if isinstance(node, GChoice):
        return " | ".join(_emit(item) for item in node.options)
    if isinstance(node, GRep):
        return _emit_atom(node.item) + node.kind
    if isinstance(node, GNot):
        return f"(!{_emit_atom(node.item)})"
    raise TypeError(type(node).__name__)


def _emit_atom(node: object) -> str:
    if isinstance(node, (GSeq, GChoice)):
        return f"( {_emit(node)} )"
    return _emit(node)


def _quote(text: str) -> str:
    chars = ['"']
    for char in text:
        if char == "\\":
            chars.append("\\\\")
        elif char == '"':
            chars.append('\\"')
        elif char == "\n":
            chars.append("\\n")
        elif char == "\r":
            chars.append("\\r")
        elif char == "\t":
            chars.append("\\t")
        else:
            chars.append(char)
    chars.append('"')
    return "".join(chars)


def _escape_class(part: str) -> str:
    if part == "\n":
        return "\\n"
    if part == "\r":
        return "\\r"
    if part == "\t":
        return "\\t"
    if part == '"':
        return '\\"'
    if part == "\\":
        return "\\\\"
    if part == "]":
        return "\\]"
    return part


def _parse_gbnf(text: str) -> dict[str, GNode]:
    parser = _GbnfParser(text)
    return parser.parse()


class _GbnfParser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.index = 0

    def parse(self) -> dict[str, GNode]:
        rules: dict[str, GNode] = {}
        while True:
            self._skip()
            if self.index >= len(self.text):
                break
            name = self._ident()
            self._skip()
            if not self.text.startswith("::=", self.index):
                raise ValueError(f"expected ::= after {name}")
            self.index += 3
            rules[name] = self._choice()
        if "root" not in rules:
            raise ValueError("gbnf has no root rule")
        return rules

    def _choice(self) -> GNode:
        options = [self._seq()]
        while self._eat("|"):
            options.append(self._seq())
        if len(options) == 1:
            return options[0]
        return GChoice(tuple(options))

    def _seq(self) -> GNode:
        items: list[GNode] = []
        while True:
            self._skip()
            if self.index >= len(self.text) or self.text[self.index] in ")|":
                break
            if self.text.startswith("::=", self.index):
                break
            if self._at_rule_start():
                break
            items.append(self._atom())
        if not items:
            raise ValueError("empty gbnf sequence")
        if len(items) == 1:
            return items[0]
        return GSeq(tuple(items))

    def _at_rule_start(self) -> bool:
        if self.index == 0 or self.text[self.index - 1] != "\n":
            return False
        match = re.match(r"[A-Za-z_][A-Za-z0-9_-]*[ \t]*::=", self.text[self.index :])
        return match is not None

    def _atom(self) -> GNode:
        self._skip()
        if self._eat("("):
            if self._eat("!"):
                inner: GNode = self._atom()
                if not self._eat(")"):
                    raise ValueError("unclosed lookahead")
                node: GNode = GNot(inner)
            else:
                node = self._choice()
                if not self._eat(")"):
                    raise ValueError("unclosed group")
        elif self._eat("["):
            node = self._class()
        elif self.text[self.index] == '"':
            node = GLit(self._string())
        else:
            node = GRef(self._ident())
        self._skip()
        if self.index < len(self.text) and self.text[self.index] in "?*+":
            node = GRep(node, self.text[self.index])
            self.index += 1
        elif self.index < len(self.text) and self.text[self.index] == "{":
            match = re.match(r"\{\d+,\d+\}", self.text[self.index :])
            if match is None:
                raise ValueError(f"bad repetition at {self.text[self.index : self.index + 20]!r}")
            node = GRep(node, match.group(0))
            self.index += len(match.group(0))
        return node

    def _class(self) -> GClass:
        # Whitespace inside a class is a member, not grammar spacing.
        negated = False
        if self.index < len(self.text) and self.text[self.index] == "^":
            negated = True
            self.index += 1
        parts: list[str] = []
        while self.index < len(self.text) and self.text[self.index] != "]":
            char = self._class_char()
            if (
                self.index < len(self.text)
                and self.text[self.index] == "-"
                and self.text[self.index + 1] != "]"
            ):
                self.index += 1
                end = self._class_char()
                parts.append(f"{char}-{end}")
            else:
                parts.append(char)
        if not self._eat("]"):
            raise ValueError("unclosed character class")
        return GClass(negated, tuple(parts))

    def _class_char(self) -> str:
        if self.text[self.index] == "\\":
            mapping = {"n": "\n", "r": "\r", "t": "\t", "\\": "\\", '"': '"', "]": "]"}
            escaped = self.text[self.index + 1]
            self.index += 2
            return mapping[escaped]
        char = self.text[self.index]
        self.index += 1
        return char

    def _string(self) -> str:
        self.index += 1
        chars: list[str] = []
        while self.text[self.index] != '"':
            if self.text[self.index] == "\\":
                mapping = {"n": "\n", "r": "\r", "t": "\t", "\\": "\\", '"': '"'}
                chars.append(mapping[self.text[self.index + 1]])
                self.index += 2
                continue
            chars.append(self.text[self.index])
            self.index += 1
        self.index += 1
        return "".join(chars)

    def _ident(self) -> str:
        match = re.match(r"[A-Za-z_][A-Za-z0-9_-]*", self.text[self.index :])
        if match is None:
            raise ValueError(f"expected a name at {self.text[self.index : self.index + 20]!r}")
        self.index += len(match.group(0))
        return match.group(0)

    def _eat(self, token: str) -> bool:
        self._skip()
        if self.text.startswith(token, self.index):
            self.index += len(token)
            return True
        return False

    def _skip(self) -> None:
        while self.index < len(self.text):
            if self.text[self.index] in " \t\r\n":
                self.index += 1
                continue
            if self.text[self.index] == "#":
                while self.index < len(self.text) and self.text[self.index] != "\n":
                    self.index += 1
                continue
            break


class _Recognizer:
    """Any-derivation matcher for the GBNF we emit.

    llama.cpp keeps every grammar stack, so a string is accepted when some
    derivation consumes it. A first-match PEG would keep a keyword that was
    also a legal name (`end` as a statement) and never try the keyword.
    """

    def __init__(self, rules: dict[str, GNode]) -> None:
        self.rules = rules
        self.text = ""
        self.memo: dict[tuple[int, int], frozenset[int]] = {}
        self.stack: set[tuple[int, int]] = set()
        self.far = 0
        self.steps = 0

    def accepts(self, source: str) -> bool:
        self.text = source
        self.memo.clear()
        self.stack.clear()
        self.far = 0
        self.steps = 0
        return len(source) in self._parse(self.rules["root"], 0)

    def _parse(self, node: GNode, pos: int) -> frozenset[int]:
        key = (id(node), pos)
        cached = self.memo.get(key)
        if cached is not None:
            return cached
        if key in self.stack:
            return frozenset()
        self.steps += 1
        if self.steps > 8_000_000:
            raise RuntimeError("gbnf recognizer exceeded its step budget")
        self.far = max(self.far, pos)
        self.stack.add(key)
        found = self._ends(node, pos)
        self.stack.remove(key)
        self.memo[key] = found
        if found:
            self.far = max(self.far, max(found))
        return found

    def _ends(self, node: GNode, pos: int) -> frozenset[int]:
        if isinstance(node, GLit):
            if self.text.startswith(node.text, pos):
                return frozenset((pos + len(node.text),))
            return frozenset()
        if isinstance(node, GClass):
            if pos < len(self.text) and self._in_class(node, self.text[pos]):
                return frozenset((pos + 1,))
            return frozenset()
        if isinstance(node, GRef):
            return self._parse(self.rules[node.name], pos)
        if isinstance(node, GSeq):
            positions = frozenset((pos,))
            for item in node.items:
                nxt: set[int] = set()
                for start in positions:
                    nxt.update(self._parse(item, start))
                if not nxt:
                    return frozenset()
                positions = frozenset(nxt)
            return positions
        if isinstance(node, GChoice):
            found: set[int] = set()
            for option in node.options:
                found.update(self._parse(option, pos))
            return frozenset(found)
        if isinstance(node, GRep):
            if node.kind == "?":
                return self._parse(node.item, pos) | frozenset((pos,))
            if node.kind.startswith("{"):
                low, high = (int(part) for part in node.kind[1:-1].split(","))
                level = {pos}
                bounded = {pos} if low == 0 else set()
                for count in range(1, high + 1):
                    level = {
                        end
                        for start in level
                        for end in self._parse(node.item, start)
                        if end > start
                    }
                    if not level:
                        break
                    if count >= low:
                        bounded.update(level)
                return frozenset(bounded)
            found = set() if node.kind == "+" else {pos}
            frontier = {pos}
            seen = set(frontier)
            while frontier:
                nxt_frontier: set[int] = set()
                for start in frontier:
                    for end in self._parse(node.item, start):
                        if end <= start or end in seen:
                            continue
                        seen.add(end)
                        found.add(end)
                        nxt_frontier.add(end)
                frontier = nxt_frontier
            return frozenset(found)
        if isinstance(node, GNot):
            if self._parse(node.item, pos):
                return frozenset()
            return frozenset((pos,))
        raise TypeError(type(node).__name__)

    def _in_class(self, node: GClass, char: str) -> bool:
        found = False
        for part in node.parts:
            if len(part) == 3 and part[1] == "-":
                if part[0] <= char <= part[2]:
                    found = True
                    break
            elif char == part:
                found = True
                break
        return not found if node.negated else found
