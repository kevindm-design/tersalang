# GBNF export

`spec/tersa.gbnf` is a [GBNF](https://github.com/ggml-org/llama.cpp/blob/master/grammars/README.md) grammar for llama.cpp's constrained decoding, so a model can be limited to text the Tersalang parser accepts. It is generated from `spec/tersa.lark`, which is the single source. Do not edit the GBNF by hand.

```bash
uv run tersa grammar --format gbnf                      # the full profile
uv run tersa grammar --format gbnf --profile decoding   # the decoding profile
uv run python scripts/check_gbnf.py                     # the committed file matches a fresh generation
```

The Python API is `tersalang.gbnf.generate_gbnf`, `tersalang.gbnf.gbnf_accepts`, and `tersalang.gbnf.llama_gbnf_accepts`. The two recognizers are development checks, not dependencies of `tersa check` or `tersa run`. `llama_gbnf_accepts` accepts a string when any derivation consumes it, as llama.cpp keeps every grammar stack. It memoizes, so its speed says nothing about llama.cpp's.

The file is standard llama.cpp GBNF: literals, character classes, sequences, ordered choice, `?` `*` `+`, and the bounded repetition `{m,n}`. It does not use the `( !rule )` lookahead.

## Profiles

| Profile | Accepts | Use it for |
| --- | --- | --- |
| `full` (default) | Every layout the hand parser accepts, except the two spellings under [Layout](#layout) | Checking that text parses |
| `decoding` | The same programs with the formatter's whitespace: single spaces, LF line breaks, even indentation, at most one blank line in a row | Generation |

Both profiles reserve keywords, encode the lexer's name rules, end every statement in a line break, and cap comments. `decoding` is a subset of `full`.

`full` rejects what the parser rejects: a `do`, `uses`, `requires`, or `ensures` on the header line, a second statement on a line, a statement and `end` on one line, a keyword used as a name, a keyword run into the next word, and a line break where the lexer would end the statement (`return 1` then `+ 2` on the next line). It accepts a little more than the parser in number literals (see [Literals](#literals)).

Beyond `full`, `decoding` rejects exactly these:

- Tabs and CR anywhere outside a literal or comment.
- Two or more spaces between tokens.
- A trailing comment not preceded by exactly two spaces, and trailing whitespace at the end of a line.
- A file that does not end in LF.
- A blank line at the start of the file, two blank lines in a row, and a comment or blank line inside a line break within an expression.

`decoding` constrains whitespace, not layout. Run `tersa fmt` on generated text; `tersa fmt --check` remains the layout gate. Every `tersa fmt` result in the corpus matches `decoding`, except the three `# fmt: skip` fixtures (the CRLF file, the newline-suppression file, and the mixed `and`/`or` file), which `decoding` is not required to accept.

### What the decoding profile still accepts

Each of these matches `decoding` even though `tersa fmt` would change it. `tests/unit/test_wording_issues.py` pins this list and the rejection list above.

- Spacing between tokens: `1+2`, `f( 1 )`, `f(1,2)`, and `f (1)` all match, because every gap may be empty or one space. `function(Int)` and `function (x: Int)` are both canonical, so the grammar cannot tell which gap needs a space.
- Which of the allowed line breaks are used. A line break may follow any continuation token or sit inside brackets, as in the lexer, so `let x =` followed by `1` on the next line matches.
- Indentation depth. An indent is any number of space pairs, plus the one optional gap space, so 0, 3, or 6 spaces all match. Nesting depth is not tracked.
- Whether one blank line or none separates declarations, and a blank line right after `do` or before `end`.
- Import order, `exposing` order, and the `W1103` parentheses around `and` under `or`.
- The 100-column limit for code.
- In number literals: leading zeros, `__`, a trailing `_`, and integers out of range (the lexer reports those). Names follow the lexer exactly; see [Name rules](#name-rules).

## Keyword reservation

`lower` is `[a-z][a-z0-9_]*` minus the 57 words in the negative lookahead of Lark's `LOWER` pattern, which are the hand lexer's `KEYWORDS` (a unit test checks that the two sets are equal). Stock llama.cpp has no lookahead, so the generator writes the exclusion as a trie: `lower-PREFIX` matches the rest of a name that starts with `PREFIX`. At each node a name may stop (unless `PREFIX` is itself a keyword), step to the next trie node on a keyword's next letter, or take any other name character and then a `name-N` tail. After a keyword that no other keyword extends, at least one more character is required. Every name has exactly one derivation, so llama.cpp keeps one stack per name. `do`, `end`, and `in` are not names; `done`, `ending`, `int`, and `x_end` are.

Reservation is what makes a constrained model close its bodies: if `end` were a name, text after the real `end` would parse as more statements. The parser's own message for a keyword used as a name is `E1000` "expected a … name, found the keyword `x` (keywords are reserved and cannot be names)".

## Name rules

A constrained model cannot write a name the lexer rejects. `name-N` is the rest of a lower name with at most `N` more characters: a letter or digit, or `_` and then a letter or digit. So a lower name has no `__` and no trailing `_` (`E0010`), and a leading `_` is never a name: `_` alone is the wildcard token, and `_x` does not match. A lower or Upper name is at most 64 characters (`E0012`), and an Upper name has no `_` (`E0011`). `NAME_CHARS` in `src/tersalang/gbnf.py` is the 64. `tests/unit/test_gbnf.py` checks the grammar against the lexer on each boundary.

## Statement separators

Every statement and declaration ends in `nl`, as `NL` does in the Lark file, so two names can never sit side by side. That removes the word-splitting ambiguity (`end` as `e` `nd`, `0x1000…` as `0` and the name `x1000…`) that would otherwise make llama.cpp keep many stacks.

`nl` is the hand lexer's NL token: the end of a line that has a token, then every blank or comment-only line after it, since those make no token of their own. In `full` that is spaces or tabs, an optional comment, and a line break (LF or CR LF), repeated. NL never follows NL, so the Lark derivations that match a bare NL (`NL*`, an `NL` alternative in the declaration list, `statement? NL` with no statement) only apply after a token, which is how a block may open on the line after `then`. A full-profile comment runs to its line break, except one at the very end of the file, so `# see function f()` is never read as a comment followed by the keyword `function`.

The hand parser accepts a file whose last line has no line break, but GBNF cannot see the end of the input. The generator therefore derives an "open" copy of each rule that can end a file (`file-open`, `function-decl-open`, `header-open`, and so on), with the last `NL` optional, and only `root` uses them. The decoding profile requires the final LF.

## Layout

GBNF has no lexer, so the generator puts the hand lexer's layout rules into the gaps between tokens. Each token gets one of four gaps, chosen by the token before it:

| Gap | `full` | `decoding` | Where |
| --- | --- | --- | --- |
| `sgap` | spaces and tabs | empty or one space | outside brackets: the lexer turns any other line break into NL |
| `gap` | spaces, tabs, comments, line breaks | empty, one space, or one line break and its indent | inside `(`, `[`, `{`, and after a continuation token (`+ - * / == != < <= > >= and or div mod not , = . : with uses requires ensures`) |
| `sgap1`, `gap1` | the same, not empty | the same, not empty | before a word (a keyword, name, or number) after a token that ends in a name character |

A lambda's body is outside brackets again from its parameter `)` to its `end`, as in the lexer. The non-empty gaps keep a keyword from running into the next word: `functions` is not `function s`, `andb` is not `and b`, and `letx` is not `let x`.

The token before a gap is not always known: an expression can end in a name or in `)`. The generator copies each rule once per context it is used in (`-b` inside brackets, `-w` after a word, `-c` after a continuation, `-n` after an NL), gives a rule that can be empty a copy that cannot (`block-some`), splits a rule that can end either at a line break or at a token (`elseif-arm-e`, `elseif-arm-t`), and turns a repeated arm whose start depends on the last one into `-loopN` helper rules. Where a rule can still end either way, the next gap assumes the strictest case. So both profiles reject two spellings the lexer splits on its own: a word right after `)`, `]`, `}`, or a text literal (`(a)and b`, `f(x)then`), and a word right after a number (`7mod 2`). Adding the space makes both acceptable. `x and(y)` is fine.

## Whitespace placement

Each token is preceded by exactly one of the four gaps, and nothing else carries whitespace except `nl`. llama.cpp keeps one grammar stack per reading that still matches and does not memoize, so a space that two adjacent gaps could both take doubles the stacks, and an alternative that repeats a prefix (`a | a "or" a`) doubles them again at each precedence level. The generator therefore left-factors the Lark oracle's tree-shaping alternatives (`and-expr ( "or" and-expr )*`, `primary postfix-op*`, `additive ( comp-op additive )?`) and attaches gaps only to tokens. The slowest corpus input takes about 0.6 seconds in llama.cpp.

Ordered choice tries the longer alternative first. `FLOAT` is tried before `INT`. Constructor patterns are tried before bare identifiers. A named argument (`name = expr`) is tried before a positional expression, so `f(x == y)` is a comparison.

## Comment caps

Both profiles cap comments, so a model cannot loop inside one:

| Cap | Value | Constant in `src/tersalang/gbnf.py` |
| --- | --- | --- |
| Characters in one comment, from its `#` | 500 | `COMMENT_CHARS` |
| Full-line comments before the file's first token (the header) | 100 | `HEADER_LINES` |
| Full-line comments in a row anywhere after that, inside brackets too | 30 | `COMMENT_LINES` |

The header allowance is for license headers. Any run after the first token, including one right after `module`, gets 30. Blank lines are not capped in `full`; `decoding` allows at most one in a row. The caps are shared by both profiles, so `decoding` stays a subset of `full`.

In `decoding`, `nl` is a `break`: LF, an optional `  #` trailing comment, then at most 30 full-line `#` comments, each after at most one blank line, then at most one more blank line, then an indent made of pairs of spaces. That is the formatter's blank-line rule: `tersa fmt` drops blank lines at the start of the file and keeps at most one in a row. A formatted file may open with up to 100 `#` lines, each followed by at most one blank line; those are a banner on `root`, because they come before any token. Only `nl` holds comment and blank lines, and NL never follows NL, so a run cannot restart: a model must write code or stop after at most 30 comment lines.

`tersalang.gbnf.cap_cases` lists formatted programs on each side of each cap. The unit tests and the llama.cpp job check them.

**Caveat for formatted files.** `tersa fmt` keeps comments as written: it reindents them but never wraps, merges, or splits them. So no finite cap accepts every formatted file. A formatted file with a comment over 500 characters, a header of more than 100 comment lines, or more than 30 comment lines in a row after code is valid Tersalang that both profiles reject; split a long block with a line of code, or shorten it. The caps sit far above the corpus (the longest comment in any formatted file is 87 characters, and the longest comment run is 7 lines). A unit test formats a 60-line license header with 300-character comments and checks that both profiles accept the result. Closing the gap for good needs `tersa fmt` to wrap long comments and split long runs, which is a formatter design question.

## Literals

Float literals are a dotted form (`1.0`, `1.0e10`, `1.0e-2`) or digits and an exponent with no dot (`1e10`, `1e+2`). The exponent marker is lowercase `e`; `1E10` is a lexer error.

Text literals accept the lexer's escapes: `\"`, `\\`, `\n`, `\t`, `\r`, `\{`, `\}`, and `\u{` plus 1 to 6 hex digits plus `}`. A raw newline or CR does not match, and neither does an unknown escape.

## How it is checked

- `scripts/check_gbnf.py` (every CI test job) fails when the committed file differs from a fresh generation or contains `(!`.
- The unit tests load the committed file with `llama_gbnf_accepts`, which rejects a grammar containing `(!`. They check that `full` accepts every conformance program and example the hand parser accepts and every lexer literal form above, and that `decoding` accepts every `tersa fmt` result except the three `# fmt: skip` files.
- The `gbnf (llama.cpp)` CI job builds llama.cpp's `test-gbnf-validator` from a pinned commit and runs `scripts/check_gbnf_llama.py PATH/TO/test-gbnf-validator`. The validator parses the grammar with llama.cpp's own GBNF parser and feeds the input to `llama_grammar_accept` one code point at a time, without a model. The script requires every corpus program the parser accepts to match `full`, every `tersa fmt` result to match `decoding`, llama.cpp to agree with `gbnf_accepts` on every corpus input and on broken variants of each, and llama.cpp to give the required verdict on every `cap_cases` program. The job may fail without blocking a pull request, because it depends on an external build. It downloads no model and calls no paid service.

## Generating with a model

Use the `decoding` profile, and give the grammar's `root` a bounded number of declarations if the model tends to keep writing after its answer. `full` allows any number of blank lines at the end of a file, as `tersa check` does, so a model that has finished can keep emitting blank lines until its token limit; `decoding` allows at most one. Measurements with a small model are recorded in [CHANGELOG.md](../CHANGELOG.md#gbnf-measurements).
