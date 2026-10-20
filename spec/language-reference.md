# Tersalang Language Reference (Draft v0.6.0)

**Tersalang** ("terse language") is a programming language built for large language models to write and for reinforcement-learning agents to learn from. CLI: `tersa`. File extension: `.tersa`. Python package: `tersalang`. The language was first called AIOWL.

| Item | Detail |
| :-- | :-- |
| **Version** | Draft v0.6.0, Oct 19, 2026 |
| **Language** | 0.1-draft, implemented by `tersalang` 0.1.0 |
| **Code baseline** | Describes the interpreter in this repository at `tersalang` 0.1.0 |
| **Built commands** | `tersa check`, `run`, `test`, `sandbox`, `harness run`, `harness validate`, `grammar` (`--format ebnf\|lark\|gbnf`), `fmt` (with `--check`), and `version`. Commands marked **planned** aren't built yet |
| **Source of truth** | [Tersalang Design Doc v0.6.0](design-doc.md). If this reference and the Design Doc disagree, the Design Doc wins; please report the mismatch. Diagnostic codes follow `spec/diagnostics.yaml` (Appendix B) |
| **Repository** | https://github.com/kevindm-design/tersalang (default branch `main`) |
| **Licenses** | Apache-2.0 for code, CC BY 4.0 for docs, including this reference |

## Purpose

This reference explains how to write Tersalang programs: the syntax, types, statements, contracts, error handling, effects and limits, modules, testing, the standard library, diagnostics, and formatting. It is for programmers, tool builders, and anyone prompting or training a model to write Tersalang. It restates the rules of the Design Doc, which wins if the two ever disagree.

## Executive Summary

Tersalang ("terse language") is a programming language designed first for AI. Large language models (LLMs) write it and reinforcement-learning (RL) agents learn from it, while people can still read and review the code. It matters because a model gets the most from a language that is strict and predictable: every Tersalang program is checked before it runs, runs the same way every time, and reports each mistake with a stable error code and a suggested fix. That gives models fast, honest feedback and gives RL training a clean reward.

This reference covers how to write programs. It walks through the language from the smallest pieces (words, numbers, text) to whole programs: types, variables, loops, functions, contracts that state what a function promises, errors, effects such as console or file access, resource limits, modules, and tests. It ends with a complete worked example, a cheat sheet, a glossary, the full grammar (Appendix A), every diagnostic code exactly as the official catalog defines it (Appendix B, 128 codes), and trigger rules for selected codes (Appendix C).

**Current status.** The interpreter is built, and CI passes on Linux, macOS, and Windows. Its commands are `tersa check`, `run`, `test`, `sandbox`, `harness run`, `harness validate`, `grammar`, `fmt`, and `version`. The RL harness has passing tests for all 21 reward-hacking defenses, and the generated grammar for constrained decoding (GBNF) is validated with llama.cpp.

**Key decisions.** Integers are exact by default (with a size cap); `Int64` is the only fixed-width type; `do` always goes on its own line and blocks close with plain `end`. Every former "item to confirm" is decided (§22). The name Tersalang is decided.

**What's next.** The commands marked **planned** are still to come, and any change to the language goes through a formal proposal (TEP).

---

## Contents

1. Introduction
2. Lexical Structure
3. Program Structure and Grammar Walkthrough
4. Operators and Precedence
5. Values and Types
6. Variables, Mutability, and Scope
7. Statements and Control Flow
8. Functions
9. Contracts: requires, ensures, invariant
10. Error Handling: Results and Traps
11. Effects, Capabilities, Determinism, and Limits
12. Resources: `using`
13. Modules, Imports, Manifest, and Lockfile
14. Testing and Verification Levels
15. Standard Library v1 Overview
16. Python Interop Tiers
17. Diagnostics (Error Format)
18. Formatting and Style
19. Complete Worked Example
20. Quick-Reference Cheat Sheet
21. Glossary
22. Resolved Items

Appendix A: Full Grammar (EBNF). Appendix B: Diagnostic Codes. Appendix C: Trigger Rules for Selected Codes.

---

## 1. Introduction

### 1.1 What Tersalang is

Tersalang is a small, strict, statically typed language designed to be **written by AI models, checked automatically, and read by humans.** Its main traits:

- **Word-based syntax.** Blocks use `do … end`. Logic uses `and`, `or`, `not`. Mutation is spelled `set`. Universal math symbols (`+ - * / ==`) stay as symbols.
- **One obvious way.** Few synonyms, no operator overloading, no function overloading, no inheritance, no implicit conversions.
- **Everything checkable.** Types, effects, contracts (`requires`/`ensures`/`invariant`), and tests are part of the language.
- **Deterministic.** The same program with the same inputs and seed gives byte-identical output.
- **Sandboxed by design.** A program can only do the I/O it declares (`uses`) and is granted at run time.

### 1.2 Hello, world

```
module hello

import std.console exposing print

public function main() returns Unit
  uses Console
do
  print("Hello, world!")
end
```

How to read it:
- `module hello` names the module. It must match the file name (`hello.tersa`).
- `import std.console exposing print` brings `print` into scope.
- `main` is the entry point. It returns `Unit` (nothing useful).
- `uses Console` declares that `main` writes to the console. Without it, calling `print` is a compile error.
- `do … end` encloses the body. A `Unit` function needs no `return` at the end.

### 1.3 Running programs

| Command | What it does |
| :-- | :-- |
| `tersa check hello.tersa` | Parses and type/effect-checks without running. Add `--json` for machine-readable diagnostics |
| `tersa run hello.tersa --allow Console` | Runs the program, granting the `Console` capability. Without `--allow Console`, the program is refused at load time |
| `tersa test hello.tersa` | Runs the file's `test` blocks and doc examples |
| `tersa fmt hello.tersa` | Rewrites the file in canonical format (§18). `tersa fmt --check` exits 1 if a file would change. A file with a `# fmt: skip` line is left alone (§18.1) |
| `tersa grammar --format gbnf` | Prints standard llama.cpp GBNF generated from the Lark grammar (also `ebnf`, the default, and `lark`). Add `--profile decoding` for the stricter-whitespace profile (§18.2) |
| `tersa sandbox hello.tersa --allow Console --fuel 100000 --memory-units 100000` | Runs `main` in RL mode with only the grants and limits you pass (§11.4) |
| `tersa harness run TASK_DIR --attempt FILE` | Scores a solution against a task's hidden tests and prints result JSON (§14.4) |
| `tersa harness validate TASK_DIR` | Checks that the task's reference solution scores 1 and its mutants (up to 16) don't (§14.4) |

Output of `tersa run hello.tersa --allow Console`:

```
Hello, world!
```

Without the grant (`tersa run hello.tersa`), the program never starts:

```
error[E4010]: main uses Console, but Console was not granted
  --> hello.tersa:5:8
  = fix: run with --allow Console
```

(The human-readable format shown in this reference is generated from the JSON diagnostics in §17. This layout is the reference layout. Only the JSON is a stable interface for tools.)

---

## 2. Lexical Structure

> **Convention:** short snippets in this reference show statements as they would appear inside a function body, unless they start with `module`, `function`, `record`, `choice`, or `test`.

### 2.1 Encoding and characters

**Rule.** Source files MUST be valid UTF-8 with no byte-order mark. **Any** invalid UTF-8 byte sequence anywhere in the file is error `E0001`: a byte that can't start a sequence, a truncated or overlong sequence, an encoded surrogate (U+D800–U+DFFF), or a value above U+10FFFF. A leading byte-order mark is also `E0001`. The lexer reports the byte offset and skips to the next line. Non-ASCII characters are allowed **only** inside text literals and comments. Tab characters are allowed only inside text literals and comments.

**Why.** ASCII-only code tokenizes predictably for language models, and it rules out look-alike characters (such as a Cyrillic "а" posing as a Latin "a").

```
let café = 1        # ERROR E0002: non-ASCII character outside a text literal or comment
let label = "café"  # OK: non-ASCII inside text is fine
```

### 2.2 Lines, newlines, and indentation

**Rule.** A line break ends a statement, **except**:
1. inside an open `(`, `[`, or `{`, or
2. when the line ends with a binary operator, `not`, `,`, `=`, `.`, `:`, `with`, `uses`, `requires`, or `ensures`.

**Lambda-frame exception to rule 1:** from the `)` that closes a lambda's parameter list (`function (…)`) until that lambda's matching `end`, the lexer treats bracket depth as zero again, so line ends there do produce `NL` (rule 2 still applies). When the lambda's `end` is reached, the outer bracket depth is restored. This is what lets a lambda passed as an argument put `do` on its own line. A lambda body is still a single expression, so a statement block never appears inside brackets.

Blank lines and comment-only lines are ignored. **Indentation never matters to the meaning of the program.** Only the formatter cares about it (2 spaces per level).

**Why.** Code copied through chat, diffs, or web pages often loses its indentation. In Tersalang that can't change what a program means, because blocks always end with `end`.

```
let total = price * quantity +     # line ends with "+", so the expression continues
  shipping

let items = [
  "apples",                        # inside [ ], line breaks are ignored
  "pears",
]
```

Incorrect (the second line is a new statement):

```
let total = price * quantity
  + shipping      # ERROR: "+ shipping" is not a valid statement. Put the operator at the end of the line above
```

### 2.3 Whitespace

A space is required between two adjacent words (keywords or names). It is optional elsewhere. Tabs are not allowed outside text and comments (`E0003`). Line endings are LF (CRLF is accepted and normalized). A lone CR is an error (`E0004`).

### 2.4 Comments

| Form | Meaning |
| :-- | :-- |
| `# text` | Comment to end of line |
| `## text` | **Doc comment.** Consecutive `##` lines attach to the next declaration (§14.4, §18) |

There are no block comments.

```
## Returns the larger of two integers.
## Example: larger(2, 7) == 7
public function larger(a: Int, b: Int) returns Int
do
  if a >= b then   # ties go to a
    return a
  end
  return b
end
```

### 2.5 Identifiers and capitalization

**Rule.** There are two kinds of names, told apart by their first letter:

| Kind | Form | Used for | Examples |
| :-- | :-- | :-- | :-- |
| lower name | `a-z` first, then `a-z 0-9 _` (snake_case) | variables, functions, fields, modules | `total`, `parse_line`, `max_retries2` |
| Upper name | `A-Z` first, then letters and digits (PascalCase, no `_`) | types, choice cases, interfaces, effects | `Int`, `Rect`, `NotFound`, `Console` |

More rules:
- Lower names MUST NOT contain `__` or end with `_` (`E0010`). Upper names MUST NOT contain `_` (`E0011`). The maximum length is 64 characters (`E0012`).
- `_` on its own is the wildcard pattern, not a name.
- Keywords cannot be used as names; the parser reports `E1000` naming the keyword.

**Why.** Because capitalization is part of the syntax, `Some(x)` is always a constructor and `some(x)` is always a function call. Neither the parser nor the reader ever has to guess.

```
let MaxSize = 10        # ERROR E1000 (syntax error): let needs a lower name. Write max_size
record point            # ERROR E1000 (syntax error): a record needs an Upper name. Write Point
let user__id = 3        # ERROR E0010: "__" is not allowed
record Line_Item        # ERROR E0011: Upper names cannot contain "_". Write LineItem
```

### 2.6 Keywords

All keywords are reserved everywhere. There are no "soft" keywords.

| Keyword | Meaning |
| :-- | :-- |
| `module` | Names the current module (first line of every file) |
| `import` | Brings another module into scope |
| `as` | Renames an imported module |
| `exposing` | Lists names imported unqualified |
| `public` | Exports a declaration from its module |
| `foreign` | Declares a Python function (host mode only, §16) |
| `function` | Declares a function, a function type, or a lambda |
| `returns` | Introduces a return type |
| `uses` | Lists the effects a function may perform |
| `requires` | Precondition (checked on entry, blames the caller) |
| `ensures` | Postcondition (checked on exit, blames the function) |
| `invariant` | Condition that every value of a record must satisfy |
| `record` | Declares a record (a product type with named fields) |
| `choice` | Declares a choice (a tagged union) |
| `case` | A choice case, or a `match` arm |
| `interface` | Declares a set of functions a type can implement |
| `implements` | Supplies an interface's functions for a type |
| `let` | Declares an immutable binding (or a module constant) |
| `var` | Declares a reassignable local variable |
| `set` | Reassigns a `var` |
| `test` | Declares a test block |
| `do` | Starts a block (function body, loop body, `using`, test) |
| `end` | Ends a block |
| `if` / `then` / `elseif` / `else` | Conditional statement, also `if` guards in `match` arms |
| `match` | Pattern-matching statement |
| `while` | Loop while a condition holds |
| `for` / `in` | Loop over a collection. Also `for all` in property tests |
| `break` / `continue` | Leave a loop / skip to its next iteration |
| `return` | Return from a function |
| `using` | Scoped resource block (§12) |
| `fail` | Stop with a trap and a message |
| `expect` | Assertion inside a test |
| `try` | Unwrap a `Result`/`Option`, or return its error early |
| `and` / `or` / `not` | Boolean operators |
| `div` / `mod` | Integer division and remainder (floored) |
| `with` | Record update: `r with (x = 1)` |
| `true` / `false` | Boolean literals |
| `result` | The return value, inside `ensures` |
| `old` | `old(e)`: the value of `e` at function entry, inside `ensures` |
| `all` | Used in `for all` (property tests) |

**Reserved for future use** (can't be used as names): `parallel spawn send receive type alias async await`.

Because every keyword is reserved, none can be a module name either. `module interface` is a syntax error; an RL task's interface file uses a name such as `module task_spec` (§14.4).

### 2.7 Literals

| Kind | Examples | Rules |
| :-- | :-- | :-- |
| Integer | `0`, `42`, `1_000_000`, `0x2a`, `0b1010` | ASCII digits only. No sign (`-5` is minus applied to `5`). No leading zeros or octal (`E0021`). `_` only between digits. **A literal is always an `Int`**. Using one where an `Int64` is expected is `E3023` (§5.2a). A literal that needs more than 65,536 bits is `E0020`. Hex prefix is lowercase `0x` |
| Float | `3.14`, `0.5`, `1.0e-9`, `2e10` | Digits on both sides of `.` (`.5` and `5.` are `E0022`). No `inf`/`nan` literals: use `Float.infinity`, `Float.nan` |
| Text | `"hello"`, `"tab\tthen"`, `"smile \u{1F600}"` | Single line only (`E0023`). Escapes: `\n \t \r \\ \" \{ \} \u{…}` |
| Boolean | `true`, `false` | — |
| List | `[1, 2, 3]` | Elements share one type. `[]` needs a known type |
| Map | `{"a": 1, "b": 2}` | Keys share one type, values share one type. `{}` needs a known type |

**Digits are ASCII only.** Numeric literals use `0`–`9` (and `a`–`f`/`A`–`F` after `0x`). A Unicode digit such as `²`, `٣`, or a full-width `１` is never part of a number: outside a text literal or comment it is `E0002` (non-ASCII character), and the lexer skips to the next line.

`\u{…}` must be a valid Unicode scalar value, 1–6 hex digits, not a surrogate (`E0024`). `\{` and `\}` are reserved. Text interpolation and multi-line text literals are **not in v1**: use `Text.concat`, `Text.join`, `\n`, or `Text.join_lines`.

```
let big = 123_456_789_012_345_678_901_234_567_890   # OK: Int has no fixed maximum (only the run's size cap)
let n: Int64 = 42                     # ERROR E3023: integer literals are always Int. Write Int64.from_int(42).expect_some("fits")
let bad = 0755                        # ERROR E0021: leading zero. Write 755 (there is no octal)
let half = .5                         # ERROR E0022: write 0.5
```

### 2.8 Operators and punctuation

Tokens: `+ - * / == != < <= > >= = : , . ( ) [ ] { } _`

These are **not** Tersalang tokens. Each gives error `E0030` with a hint:

| You wrote | Use instead |
| :-- | :-- |
| `%` | `mod` |
| `&&`, `\|\|`, `!` | `and`, `or`, `not` |
| `->` | `returns` |
| `=>` | `then` (in `match`) |
| `;` | a line break |
| `?` | `try` |
| `&`, `\|`, `^` | nothing: there are no bitwise operations in v1, neither operators nor `std.math` functions |

---
## 3. Program Structure and Grammar Walkthrough

The full grammar is in Appendix A. This section explains it in plain English.

### 3.1 Files

Every file is one **module**, and every module looks like this:

```
module <module path>          # exactly once, first
import ...                    # zero or more
<declarations and tests>      # in any order
```

**Top-level declarations** are functions, records, choices, interfaces, `implements` blocks, constants (`let` with a type), foreign declarations, and tests. Any of them except `implements` and `test` can be marked `public`. All top-level names in a module are visible throughout that module, so declaration order doesn't matter. Two top-level declarations with the same name are `E2021`. Constants must not form a cycle (`E2003`).

```
module shop.prices

let tax_rate_percent: Int = 8          # module constant: type required, value must be pure

public function with_tax(cents: Int) returns Int
  requires cents >= 0
do
  return cents + (cents * tax_rate_percent) div 100
end
```

### 3.2 Function shape

```
[public] function NAME[TYPE PARAMS](PARAM: Type, ...) returns Type
  uses Effect, ...              # optional: only if the function performs effects
  requires condition            # optional, any number
  ensures condition             # optional, any number
do
  statements
end
```

The header (from `function` through the return type) is on one line. `uses`, `requires`, and `ensures` each go on their own line. **`do` always starts its own line**, because the grammar requires a line break after the return type. There is no same-line form, even without contracts.

**`do` on its own line.** The `do` that opens the body of a function, test, `while`, `for`, `using`, or lambda MUST be the only token on its line (a trailing comment is allowed). The grammar enforces this with `NL` before and after `do`. The parser reports the general syntax error **`E1000`**, with the message **"expected `do` on its own line"**, when `do` follows other tokens on its line (for example `while n > 0 do`) or when anything other than a comment follows `do` on its line (for example `do return 1`). The fix moves `do` to its own line at the header's indentation. Rule source: Design Doc §7.4 and resolved item 1 (Reference §22).

### 3.3 Blocks

Every compound statement ends with `end`:

| Construct | Shape |
| :-- | :-- |
| if | `if c then … elseif c then … else … end` |
| match | `match e` (newline) `case P then …` … `end` |
| while | `while c` (newline) `do` (newline) … `end` |
| for | `for x in xs` (newline) `do` (newline) … `end` |
| using | `using r = e` (newline) `do` (newline) … `end` |
| function, test | header (newline) `do` (newline) … `end` |
| record, choice, interface, implements | `record Name` (newline) … `end` |

### 3.4 Statements vs. expressions

- **Statements** do things: `let`, `var`, `set`, `return`, `fail`, `expect`, `break`, `continue`, `if`, `match`, `while`, `for`, `using`, and function calls.
- **Expressions** produce values: literals, names, arithmetic, comparisons, calls, field access, record update (`with`), lambdas, list and map literals, `try`.
- `if` and `match` are **statements only** (not expressions) in v1.
- A bare expression used as a statement must be a function call (§7.1).

---

## 4. Operators and Precedence

### 4.1 Precedence table (highest first)

| Level | Operators | Associativity | Example | Means |
| :-- | :-- | :-- | :-- | :-- |
| 1 | call `f(x)`, field `a.b`, method `a.f(x)` | left | `order.items.get(0)` | `((order.items).get)(0)` |
| 2 | `with ( … )` | none | `p with (x = 1)` | Copy of `p` with `x` replaced |
| 3 | prefix `-`, `try` | right | `try load(path).value()` | `try (load(path).value())` |
| 4 | `*  /  div  mod` | left | `a * b div c` | `(a * b) div c` |
| 5 | `+  -` | left | `a - b + c` | `(a - b) + c` |
| 6 | `==  !=  <  <=  >  >=` | **none** | `a < b < c` | **Error `E1102`.** Write `a < b and b < c` |
| 7 | `not` | prefix | `not a == b` | `not (a == b)` |
| 8 | `and` | left, short-circuit | `a and b` | `b` is evaluated only if `a` is true |
| 9 | `or` | left, short-circuit | `a or b` | `b` is evaluated only if `a` is false |

### 4.2 Operator rules by type

| Operator | Allowed on | Notes |
| :-- | :-- | :-- |
| `+ - *` | `Int`, `Int64`, `Float` (both sides the same type) | `Int` never overflows (results beyond the run's size cap trap `T6204`). Fixed-width types trap on overflow (`T6001`) |
| `/` | `Float` only | On `Int` it is `E3021`: use `div` |
| `div`, `mod` | `Int` and `Int64` (both sides the same type) | Floored (§5.2) |
| unary `-` | `Int`, `Int64`, `Float` | `-Int64.min` traps (`T6001`) |
| `== !=` | Any two values of the **same** type that is equatable | Structural. Functions and resources can't be compared |
| `< <= > >=` | `Int`, `Int64`, `Float`, `Text` (both sides the same type) | Other comparable types use `compare` |
| `and or not` | `Bool` only | No truthiness |
| `+` on Text | **Not allowed** (`E3020`) | Use `Text.concat` or `Text.join` |

### 4.3 Mixing `and` and `or`

`a and b or c` is legal, but it gets warning `W1103`, and the formatter rewrites it as `(a and b) or c`, so the meaning is always visible.

---

## 5. Values and Types

### 5.1 Built-in types at a glance

| Type | Values | Example |
| :-- | :-- | :-- |
| `Int` | Whole numbers of any size (arbitrary precision, up to the run's size cap) | `42`, `-7` |
| `Int64` | The only fixed-width integer. Opt-in. Overflow traps | `Int64.max`, `Int64.from_int(42)` |
| `Float` | IEEE 754 double precision | `3.14`, `Float.nan` |
| `Bool` | `true`, `false` | `ready and not done` |
| `Text` | Immutable Unicode text (valid UTF-8) | `"héllo"` |
| `Bytes` | Immutable bytes | `Bytes.of_hex("0aff")` |
| `Unit` | One value, written `Unit` | `return Ok(Unit)` |
| `List[T]` | Immutable ordered sequence | `[1, 2, 3]` |
| `Map[K, V]` | Immutable, insertion-ordered key/value map | `{"a": 1}` |
| `Set[T]` | Immutable, insertion-ordered set | `Set.from_list([1, 2])` |
| `MutableList[T]`, `MutableMap[K, V]` | Local-only mutable collections | `MutableList.new()` |
| `Option[T]` | `Some(value)` or `None` | `Some(3)` |
| `Result[T, E]` | `Ok(value)` or `Error(error)` | `Error(NotFound)` |
| `Ordering` | `Less`, `Equal`, `Greater` | `Int.compare(a, b)` |
| `function(A, B) returns R` | Pure function values | A lambda, with `do` on its own line (§8.3) |

There are **no implicit conversions**. `1 + 2.0` is a type error, and so is `Int + Int64` (`E3024`). Write `Float.from_int(1) + 2.0`.

### 5.2 Int

`Int` is arbitrary precision, like Python's `int`.

**Rules:**
- `Int` has **no fixed range** and **never overflows**. There are no `Int.min` or `Int.max` constants.
- **Size cap:** every `Int` value must fit in **65,536 bits** by default (magnitude below 2^65536, about 19,728 decimal digits). The host can change the cap per run: the CLI flag `--max-int-bits N`, the task file's `max_int_bits`, or the host app. Sandbox hosts and task files may lower it. Raising it above 65,536 needs explicit host configuration (§11.4).
- An operation, conversion, literal, or parse whose result would be bigger traps with **`T6204` (integer size limit exceeded)**. The check happens *before* the work when the result is certain to be too big, so `math.pow(2, 10_000_000)` (after `import std.math`) traps instead of burning compute. `Int.parse` returns `None` only for text that isn't an integer; an integer too big for the cap traps `T6204`.
- Big integers also use memory units (`T6202`), and arithmetic on them costs fuel in proportion to their size.
- `div` is **floored** division, which rounds toward negative infinity. `mod` has the sign of the divisor. Always: `a == b * (a div b) + (a mod b)`.
- Dividing by zero traps (`T6002`).
- Results are exact and the same on every machine.

**Why floored division?** C and Java round toward zero, while Python floors. Tersalang picks one rule, matching Python's, and spells it with words (`div`/`mod`) so it can't be confused with `/` or `%`.

| Expression | Result |
| :-- | :-- |
| `7 div 2` | `3` |
| `-7 div 2` | `-4` |
| `7 mod 3` | `1` |
| `-7 mod 3` | `2` |
| `7 mod -3` | `-2` |
| `9_223_372_036_854_775_807 + 1` | `9223372036854775808` (no overflow) |
| A result bigger than the size cap | trap `T6204` |

### 5.2a Fixed-width integers

Use `Int64` only when you need fixed-size behavior. Most code should use `Int`. **`Int32` and `UInt64` are not in v1**.

| Type | Range | Status |
| :-- | :-- | :-- |
| `Int64` | −9,223,372,036,854,775,808 to 9,223,372,036,854,775,807 (`Int64.min`, `Int64.max`) | In v1 |

**Rules:**
- `+`, `-`, `*`, and unary `-` **trap on overflow** (`T6001`). Fixed-width types **never wrap**, and there are no wrapping or saturating functions.
- `Int64.checked_add`, `checked_sub`, and `checked_mul` return `Option[Int64]` (`None` on overflow), for code that wants to handle overflow as a value.
- `div` and `mod` are floored, as for `Int`. Dividing by zero traps (`T6002`). `Int64.min div -1` traps (`T6001`), because the quotient does not fit. `Int64.min mod -1` is `0`, because the remainder always fits.
- **No mixing:** both sides of an operator must be the same type (`E3024`). Convert explicitly:
  - `Int64.from_int(i)` returns `Option[Int64]` (`None` if out of range).
  - `Int64.to_int(x)` always succeeds.
- **Literals are always `Int`.** An integer literal where an `Int64` is expected is `E3023`. Convert instead: `let n = Int64.from_int(42).expect_some("42 fits in Int64")`. Use the constants `Int64.min` and `Int64.max` for the limits.
- `-Int64.min` traps (`T6001`). Comparisons `< <= > >=` work on two `Int64` values.
- `Int64` is `Equatable`, `Hashable`, `Comparable`, and `Showable` (decimal text form, like `Int`).

```
let a: Int64 = Int64.max
let b = a + 1                                # trap T6001: Int64 overflow (never wraps)
let c = Int64.checked_add(a, 1)              # None
let d = Int64.to_int(a) + 1                  # 9223372036854775808 as an Int
let e = Int64.from_int(d)                    # None: out of Int64 range
```


### 5.3 Float

**Rules:**
- IEEE 754 binary64. `+ - * /` and `Float.sqrt` are correctly rounded.
- Dividing by zero does **not** trap: `1.0 / 0.0` is infinity, and `0.0 / 0.0` is NaN.
- There is only one NaN bit pattern (canonical), so results never vary between machines.
- `==` follows IEEE, so `Float.nan == Float.nan` is `false`. Use `Float.total_compare` for a total order, and `Float.same(a, b)` for "identical value".
- There is no hidden fused multiply-add. Call `Float.fma` explicitly.
- Conversions:
  - `Float.from_int(i)` rounds to nearest (ties to even). If the result would be infinite because `i` is too large for a Float, it **traps with `T6003`**. It never returns ±infinity silently.
  - `Int.from_float(x)` truncates toward zero and returns `Option[Int]` (`None` for NaN or infinity).
  - `Float.round`, `Float.floor`, and `Float.ceil` return `Option[Int]` (`None` for NaN or infinity).
- `Float` cannot be a map key or set element (it is not `Hashable`), because NaN breaks hashing.
- Trigonometric, exponential, and logarithm functions (`sin`, `cos`, `tan`, `asin`, `acos`, `atan`, `atan2`, `exp`, `log`, `log2`, `log10`, `float_pow`) live in `std.math`. **In RL mode they are unavailable**: a program that uses one is rejected at load time with `E4011`. In dev, test, and host modes they use the platform math library, and results may differ in the last bits between platforms. `Float.sqrt` and `+ - * /` are always available.
- Text form: shortest round-trip decimal, always containing `.` or an exponent (`1.0`, `2.5e-8`). Special values show as `Float.nan`, `Float.infinity`, `-Float.infinity`, and `-0.0` (§5.14).

### 5.4 Bool and "no truthiness"

**Rule.** Conditions MUST be `Bool`. Numbers, text, lists, and `Option` are never treated as true or false (`E3022`).

**Why.** Truthiness rules differ between languages (in Python, `0`, `""`, and `[]` are falsy) and cause subtle bugs.

```
if items then ...                     # ERROR E3022: condition must be Bool, found List[Text]
if not items.is_empty() then ...      # OK
```

### 5.5 Text and Unicode

**Rules:**
- `Text` is an immutable sequence of Unicode scalar values, always valid UTF-8.
- **No `len` and no `t[i]`**, because "length" could mean bytes, code points, or user-visible characters. Use the explicit functions:

| Need | Function |
| :-- | :-- |
| Size in bytes | `t.byte_length()` |
| Number of code points | `t.code_point_count()` |
| Code points | `t.code_points()` → `List[Int]` |
| User-perceived characters | `t.graphemes()` → `List[Text]` (Unicode UAX #29) |
| Substring by code point | `t.slice(start, end)` (traps `T6010` if out of range), or `t.try_slice(start, end)` → `Option[Text]` |
| Join | `Text.concat(a, b)`, `Text.join(parts, separator)` |

- `==` compares exactly, with **no** automatic Unicode normalization. Use `Text.normalize_nfc` / `normalize_nfd` when needed.
- `<` and `compare` order text by code point (not locale-aware).
- `to_upper` and `to_lower` use Unicode default, locale-independent mappings.
- The Unicode version is fixed for each language version, so results are the same everywhere.
- Converting from bytes can fail: `Text.from_utf8(b)` → `Result[Text, Utf8Error]`.

```
let name = "José"
let a = name.code_point_count()       # 4
let b = name.byte_length()            # 5 ("é" is 2 bytes in UTF-8)
let greeting = "Hi " + name           # ERROR E3020: + is not defined on Text. Use Text.concat("Hi ", name)
```

### 5.6 Bytes

An immutable byte sequence. Create one with `Bytes.of_hex("0a0b")` or `Bytes.of_list([10, 11])`, or with `Bytes.from_hex(…)` / `Bytes.from_list(…)` when the input might be bad. Read with `b.get(i)` → `Option[Int]`.

**Bytes constructors.** `Bytes.from_hex(text)` and `Bytes.from_list(items)` return **`Option[Bytes]`**: `None` when the input is bad (a list value outside 0–255, or hex text that isn't an even number of hex digits `0-9`, `a-f`, `A-F`). This matches the interpreter. The non-Option constructors are `Bytes.of_hex(text)` and `Bytes.of_list(items)`, which return `Bytes` and **trap `T6013`** on the same bad input. This is the same pair pattern as `get`/`at` and `try_slice`/`slice`. Use `from_…` for data you don't control and `of_…` for values you know are valid. The canonical text form (`show`) uses `Bytes.of_hex("…")`, because it must be an expression that builds a `Bytes`, not an `Option`.

```
let header = Bytes.of_hex("0aff")          # Bytes
let parsed = Bytes.from_hex(user_text)     # Option[Bytes]: None if user_text isn't valid hex
let bad = Bytes.of_list([10, 300])         # trap T6013: 300 is outside 0..255
```

### 5.7 Collections

**Rules:**
- `List`, `Map`, and `Set` are **immutable**. "Changing" one returns a new collection, and the old one is unchanged.
- **Naming rule:** every operation that returns a changed copy of an immutable collection is named `with_…` or `without_…`. The verbs `push`, `insert`, `remove`, and `set_at` exist **only** on mutable collections (§6.3), where they change the collection in place. The same name never means both "copy" and "mutate".
- `Map` and `Set` iterate in **insertion order**. Removing and re-inserting a key moves it to the end.
- Map keys and set elements must be `Hashable`: `Int`, `Int64`, `Bool`, `Text`, `Bytes`, and records or choices made only of hashable fields. Not `Float`, and not functions.
- Two maps are `==` if they have the same entries, whatever the order.
- **Access:** `xs.get(i)` returns `Option[T]`. `xs.at(i)` returns `T` but traps (`T6011`) on a bad index, and the checker warns (`W3050`) if it can't see a bounds check nearby. Both forms are kept.

| Operation | List | Map | Set | Complexity (upper bound) |
| :-- | :-- | :-- | :-- | :-- |
| Read | `xs.get(i)`, `xs.at(i)` | `m.get(k)` → `Option[V]` | `s.contains(x)` → `Bool` | List O(log n). Map and Set O(log n) expected |
| Add | `xs.with_appended(x)` → new list | `m.with_entry(k, v)` → new map (adds or replaces) | `s.with_element(x)` → new set | O(log n) |
| Replace | `xs.with_item(i, x)` → new list (traps `T6011` on a bad index) | `m.with_entry(k, v)` | — | O(log n) |
| Remove | — | `m.without_key(k)` → new map | `s.without_element(x)` → new set | O(log n) expected |
| Test | `xs.contains(x)` | `m.contains_key(k)` | `s.contains(x)` | List O(n). Map and Set O(log n) expected |
| Size | `xs.length()`, `xs.is_empty()` | `m.length()`, `m.is_empty()` | `s.length()`, `s.is_empty()` | O(1) |
| Iterate | `for x in xs` | `for k in m.keys()`, `for e in m.entries()` | `for x in s` | O(n) |
| Transform | `xs.map(f)`, `xs.filter(f)`, `xs.fold(init, f)` (pure `f` only) | — | — | O(n) |

- `m.keys()` returns a `List[K]`, and `m.entries()` returns a `List[Entry[K, V]]`. `Entry` is a record in `std.core` with the fields `key` and `value`. Both are in insertion order.
- `Set.from_list(xs)` builds a set, keeping the first occurrence of each element.

```
let prices = {"apple": 30, "pear": 45}
let more = prices.with_entry("plum", 50)     # prices is unchanged; more has 3 entries
match more.get("kiwi")
  case Some(p) then
    print(show(p))
  case None then
    print("no kiwis")
end
```

**Mutable collections** (`MutableList`, `MutableMap`) exist for building results inside one function (§6.3).

### 5.8 Option, Result, Ordering

These are ordinary choice types, imported automatically:

```
choice Option[T]
  case Some(value: T)
  case None
end

choice Result[T, E]
  case Ok(value: T)
  case Error(error: E)
end

choice Ordering
  case Less
  case Equal
  case Greater
end
```

Helpers: `map`, `map_error`, `and_then`, `unwrap_or(default)`, and `expect_some(message)` (traps `T6020` with your message if `None`).

**There is no null.** A value that might be missing has type `Option[T]`, and the compiler makes you handle `None`.

### 5.9 Records (named product types)

```
public record Rect
  width: Int
  height: Int
  invariant width >= 0 and height >= 0
end
```

**Rules:**
- **Construct** with **named** arguments, giving every field: `Rect(width = 3, height = 4)`. There are no default values. A missing field is an error.
- **Read** with a dot: `r.width`.
- **Update** with `with`, which returns a copy: `r with (width = 10)`. The original is unchanged. Only one `with (...)` per expression (`E1101`). Put several fields inside it.
- **Invariants** are checked after construction and after every update (§9.4).
- Records are immutable. `set r.width = 3` is only allowed when `r` is a `var` (`E2030` otherwise), and it means `set r = r with (width = 3)`. Nested paths work the same way: `set r.a.b = e` means `set r = r with (a = r.a with (b = e))`, and invariants are checked for each rebuilt record.
- Record construction needs named arguments: positional arguments are `E3080`, named arguments in any other call are `E3081`, and a missing, duplicated, or unknown field is `E3082`. `E3082` also covers `with`, record field access (`r.nope`), and `set r.nope = …`. An unknown field or method on a non-record type is `E3004`.
- `==` on records compares fields. `Float` fields use IEEE equality, so a record holding NaN is not equal to itself, and records with `Float` fields are not `Hashable`.

```
let r = Rect(width = 3, height = 4)
let wider = r with (width = 10)
let bad = Rect(3, 4)              # ERROR: records must be constructed with named fields: Rect(width = 3, height = 4)
let neg = Rect(width = -1, height = 4)   # TRAP T6103: invariant "width >= 0 and height >= 0" failed
```

### 5.10 Choices (tagged unions / enums)

```
public choice Shape
  case Circle(radius: Float)
  case Square(side: Float)
  case Empty
end
```

**Rules:**
- **Construct** cases **positionally**: `Circle(2.0)`, `Empty`.
- Cases are in scope wherever the choice is. Qualify them (`Shape.Circle(2.0)`) if two choices use the same case name.
- Take a choice apart with `match` (§7.4). The match must handle every case.

### 5.11 Generics

**Rules:**
- Functions, records, choices, and interfaces can take type parameters in square brackets: `function first[T](xs: List[T]) returns Option[T]`.
- **Constraints** name interfaces, joined with `and`: `function largest[T: Comparable](xs: List[T]) returns Option[T]`.
- At call sites, type arguments are inferred: `first([1, 2])` has type `Option[Int]`.
- A record or choice can constrain its type parameters too (`record Keyed[K: Hashable, V]`). A type written with concrete arguments (`Keyed[Float, Int]`) and every construction (`Keyed(key = k, value = v)`) must meet them, with the same codes as a call: `E3042` for `Hashable`, `E3045` for `Showable`, `E3046` otherwise.
- Generic code behaves the same for every type (no specialization).
- **Not in v1:** higher-kinded types, associated types, const generics, variadic generics, and type aliases.

```
public function first[T](xs: List[T]) returns Option[T]
do
  return xs.get(0)
end
```

### 5.12 Interfaces

```
interface Describable[T]
  function describe(value: T) returns Text
end

implements Describable[Rect]
  function describe(value: Rect) returns Text
  do
    return Text.join(["Rect ", show(value.width), "x", show(value.height)], "")
  end
end
```

**Rules:**
- An `implements` block MUST be in the module that defines the interface or the type (the "orphan rule", `E3040`). There is at most one implementation per (interface, type) pair.
- Implementations inherit the interface's contracts. They may add `ensures` clauses but not `requires` clauses (`E5010`).
- `implements` takes exactly the interface's type arguments (`E3007` otherwise). An interface with no type parameter, such as a task's `interface Solution`, has no `implements` block: the program meets it with top-level functions of the same names.
- Constraints are checked at each call site: a type argument that misses one is `E3046` "Type does not implement the interface" (a missed `Showable` is `E3045`, a missed `Hashable` is `E3042`). Interface functions are called by name (`describe(r)`) or as methods (`r.describe()`); a top-level function or local with the same name wins. An `implements` block must supply every function (`E3044`) with the interface's type (`E3000`), may not add others (`E3004`), and inherits the interface's contracts.
- **Built-in interfaces:**

| Interface | Provided how | Notes |
| :-- | :-- | :-- |
| `Equatable` | Automatic for types whose fields are all equatable | **You cannot implement it yourself** |
| `Hashable` | Automatic, the same way (but `Float` isn't hashable) | **You cannot implement it yourself** |
| `Comparable` | Built in for `Int`, `Int64`, `Text`, `Bool`, `Ordering`. You can implement it for records and choices | Requires `compare(a, b) returns Ordering` |
| `Showable` | Automatic for every type except functions, resources, mutable collections, and any record, choice, list, map, set, option, or result containing one of those | Gives the canonical text form (§5.14). `show` requires it at compile time (`E3045`) |

**Showable rule.** `Showable` is derived automatically for every type **except** function types, resource types, and mutable collections (`MutableList`, `MutableMap`), and except any record, choice, `List`, `Map`, `Set`, `Option`, or `Result` that contains one of those, at any depth. `show` requires `T: Showable` and is checked at compile time: calling `show` on a type that isn't `Showable` is error **`E3045`** ("Type is not Showable"). The same rule decides how values are rendered in diagnostic `values`, a `fail` whose message isn't `Text`, a value propagated out of a test, and a `main` that returns `Error`; there, a value that isn't `Showable` is rendered as a placeholder (§5.14) rather than rejected.

```
let f = function (x: Int) returns Int
  do
    x + 1
  end
print(show(f))             # ERROR E3045: function(Int) returns Int is not Showable
print(show([1, 2]))        # OK: "[1, 2]"
```

**Why no custom equality?** If code could redefine `==`, a program could make every test comparison succeed. Fixed, structural equality closes that loophole.

### 5.13 Method-call syntax

`x.f(a)` is shorthand for `f(x, a)`, where `f` comes from the module that defines `x`'s type, a top-level function whose first parameter has that type, or the `implements` block for that type. `xs.get(0)` means `List.get(xs, 0)`. There are no virtual methods. If `x`'s type is known where you write the call, the call is resolved at compile time. Inside generic code, where `x` has a constrained type parameter such as `T: Describable`, the implementation is picked when the call runs, from the actual type of the value passed for the first parameter of type `T`; it is the one the compiler would pick for that type. An interface function with no parameter of type `T` (such as `default() returns T`) can only be called where `T` is a concrete type, which it then takes from the expected type; in generic code that call is `E3010`.

### 5.14 Canonical text form

`show(value)` returns the **canonical text form**: the Tersalang expression that would build the value. The same form appears in diagnostics, test output, and when `main` returns `Error`.

| Type | Form | Example |
| :-- | :-- | :-- |
| `Int`, `Int64` | Decimal, `-` for negatives | `-12` |
| `Float` | Shortest round-trip decimal with `.` or an exponent; special values as constants | `1.0`, `2.5e-8`, `-0.0`, `Float.nan`, `Float.infinity`, `-Float.infinity` |
| `Bool` | `true` / `false` | `true` |
| `Text` | Double-quoted. `\\`, `\"`, `\n`, `\t`, `\r` escaped; other control characters as `\u{…}` (lowercase hex) | `"a\tb"` |
| `Bytes` | `Bytes.of_hex("…")`, lowercase hex | `Bytes.of_hex("0aff")` |
| `Unit` | `Unit` | `Unit` |
| `List` | `[a, b]` | `[1, 2]` |
| `Map` | `{k: v}` in insertion order | `{"a": 1}` |
| `Set` | `Set.from_list([…])` in insertion order | `Set.from_list([1, 2])` |
| Record | `Name(field = value, …)` in declaration order | `Rect(width = 3, height = 4)` |
| Choice | `Case(values)` or `Case`, unqualified | `Some(3)`, `Empty` |
| `Ordering` | `Less`, `Equal`, `Greater` | `Less` |

Functions, resources, mutable collections, and any composite value that contains one are not `Showable` (§5.12), so `show` on them is a compile-time error (`E3045`). To print text without quotes, pass the `Text` itself to `print`.

**Values that aren't Showable.** `show` itself never sees one, because the checker rejects the call (`E3045`). Where the toolchain renders a value without a `show` call (diagnostic `values`, a non-`Text` `fail` message, a value propagated out of a test, or `main` returning `Error`) and the value isn't `Showable`, the **whole value** renders as a single placeholder: `<function>` for a function, `<resource>` for a resource, `<mutable>` for a mutable collection, and `<value>` for a record, choice, list, map, set, option, or result that contains one of those. Placeholders are never partial (a `Some` holding a function renders as `<value>`, not `Some(<function>)`), and they are not Tersalang expressions.

| Value that isn't `Showable` | Renders as |
| :-- | :-- |
| A function | `<function>` |
| A resource (such as `File`) | `<resource>` |
| A mutable collection | `<mutable>` |
| A record, choice, list, map, set, option, or result containing any of the above | `<value>` |

---
## 6. Variables, Mutability, and Scope

### 6.1 `let`: immutable bindings

```
let count = 3                 # type inferred: Int
let name: Text = "Ada"        # explicit type is allowed
```

**Rule.** A `let` binding can never be reassigned. Values themselves are immutable too, so nothing can change a `let` value behind your back.

### 6.2 `var` and `set`: reassignable locals

```
var total = 0
for x in [1, 2, 3]
do
  set total = total + x
end
```

**Rules:**
- `var` declares a local variable that may be reassigned. Every reassignment MUST use `set`.
- `var` is only allowed inside function and test bodies. Module-level variables don't exist.
- `set` on anything that isn't a `var` is an error (`E2030`). `total = total + x` without `set` is a syntax error.

**Why `set`?** Every mutation becomes a visible, searchable word. A reviewer (or a tool) can find all state changes by searching for `set`.

### 6.3 Mutable collections

`MutableList[T]` and `MutableMap[K, V]` are for building up results efficiently inside one function. They are changed in place by calling their methods, and `.freeze()` turns them into an immutable `List` or `Map`:

| `MutableList[T]` | `MutableMap[K, V]` |
| :-- | :-- |
| `MutableList.new()`, `push(x)`, `get(i)` → `Option[T]`, `set_at(i, x)` (traps `T6011` on a bad index), `length()`, `freeze()` | `MutableMap.new()`, `insert(k, v)` (adds or replaces), `remove(k)`, `get(k)` → `Option[V]`, `keys()`, `entries()`, `length()`, `freeze()` |

**Rules (checked by the compiler, `E3070`):** a mutable collection may only live in a local `let` or `var`. It MUST NOT be:
- stored in a record, choice, or immutable collection,
- returned from a public function,
- captured by a lambda.

```
public function squares(n: Int) returns List[Int]
  requires n >= 0
do
  let out: MutableList[Int] = MutableList.new()
  for i in List.range(0, n)      # 0, 1, ..., n-1 (end-exclusive; empty when n == 0)
  do
    out.push(i * i)
  end
  return out.freeze()
end
```

### 6.4 Scope rules

- A name declared with `let` or `var` is visible from its declaration to the `end` of the enclosing block.
- Function parameters are visible in the whole function, including its contracts.
- Top-level declarations are visible throughout their module, and in other modules once imported (if `public`).
- **Shadowing is not allowed** (`E2020`). Declaring a local, parameter, loop variable, pattern binding, or lambda parameter whose name is already in scope (a parameter, an outer local, a top-level name of the module, or an imported name) is an error. Each name means one thing per function.
- Lambdas capture `let` bindings and parameters by value. Capturing a `var` is an error (`E3071`).

```
public function f(x: Int) returns Int
do
  let x = 2      # ERROR E2020: "x" is already defined (parameter). Choose a new name
  return x
end
```

---

## 7. Statements and Control Flow

### 7.1 Expression statements

**Rule.** A bare expression used as a statement must be a function call. If the call returns a value other than `Unit`, you get warning `W3001`; this includes an `Option` (for example `m.get(k)` on its own line). If it returns a `Result`, ignoring it is error `E3002`. So: **ignoring a `Result` is an error, ignoring an `Option` is a warning.** Discard a value on purpose with `let _ = …`.

```
save(record)           # ERROR E3002 if save returns Result: handle it, use try, or write let _ = save(record)
prices.get("kiwi")     # WARNING W3001: ignored Option[Int]. Use the value or write let _ = prices.get("kiwi")
x + 1                  # ERROR E3005: an expression statement must be a call
```

### 7.2 if / elseif / else

```
if score >= 90 then
  set grade = "A"
elseif score >= 80 then
  set grade = "B"
else
  set grade = "C"
end
```

The condition must be `Bool`. `if` is a statement, not an expression.

### 7.3 Loops

```
while queue_size > 0
do
  set queue_size = queue_size - 1
end

for word in words
do
  if word == "" then
    continue
  end
  if word == "stop" then
    break
  end
  print(word)
end
```

**Rules:**
- `for x in e` works when `e` is a `List`, `Set`, or `MutableList`. To loop over a map, use `m.keys()` or `m.entries()`. Iteration order is always defined. A loop over a `MutableList` iterates over a **snapshot taken when the loop starts**, so changing the list inside the loop doesn't affect the iteration.
- `List.range(a, b)` gives `a` up to `b − 1` (end-exclusive), and is empty when `a >= b`.
- The loop variable is a fresh `let` binding on each iteration.
- `break` and `continue` are only valid inside loops (`E2010`).
- Every loop uses fuel, so an infinite loop ends in a deterministic trap (`T6201`), not a hang.

### 7.4 match and exhaustiveness

```
public function area(s: Shape) returns Float
do
  match s
    case Circle(r) then
      return 3.141592653589793 * r * r
    case Square(side) then
      return side * side
    case Empty then
      return 0.0
  end
end
```

**Patterns:**

| Pattern | Matches |
| :-- | :-- |
| `_` | Anything (binds nothing) |
| `name` (lower) | Anything, binding it to `name` |
| `42`, `"text"`, `true`, `-1` | That exact literal |
| `Circle(r)` | That case, matching its fields positionally |
| `Some(Circle(_))` | Nested patterns |

**Rules:**
- **Exhaustive:** every possible value must be handled, or the code fails to compile (`E3030`, which lists the missing cases). Use `case _ then` as a catch-all.
- **Guards:** `case Some(n) if n > 0 then …`. Guarded arms do *not* count toward exhaustiveness.
- An arm that can never match is warning `W3031`.
- Arms are tried top to bottom, and only the first match runs.

Incorrect:

```
match s
  case Circle(r) then
    return r
end
```

```
error[E3030]: match on Shape is not exhaustive
  --> shapes.tersa:12:3
  = missing cases: Square, Empty
  = fix: add the missing cases, or "case _ then"
```

### 7.5 return and fail

- `return e` returns from the function. `return` alone is only for `Unit` functions (a bare `return` in a non-`Unit` function is `E3032`).
- **Every path** through a non-`Unit` function must end in `return` or `fail` (`E3032`).
- `fail "message"` stops the program with a trap (`T6030`) that carries your message. Use it for "this should be impossible" situations, never for expected errors (§10).

---

## 8. Functions

### 8.1 Declaring functions

```
## Returns the average of a non-empty list.
public function average(xs: List[Float]) returns Float
  requires not xs.is_empty()
do
  let sum = xs.fold(0.0, function (acc: Float, x: Float) returns Float
    do
      acc + x
    end)
  return sum / Float.from_int(xs.length())
end
```

**Rules:**
- **Parameters and return type are always written out.** Only local variables are inferred. That keeps every error local to one function.
- No default parameter values, no variable-length argument lists, and no named arguments in function calls (named arguments are only for record construction).
- **No overloading.** One name in a module means one function.
- Recursion is allowed. Call depth is limited (trap `T6203` when exceeded).
- A function that performs effects must declare them with `uses` (§11).

### 8.2 Calling functions

- Positional arguments only: `average([1.0, 2.0])`.
- Method style works on the first argument: `xs.length()` is `List.length(xs)`.
- Qualified style works too: `shapes.area(s)` after `import geometry.shapes`.

### 8.3 Lambdas (anonymous functions)

```
let double = function (x: Int) returns Int
  do
    x * 2
  end
let doubled = [1, 2, 3].map(double)          # [2, 4, 6]
```

**Rules:**
- `do`, the body, and `end` each go on their own lines, even when the lambda is an argument inside parentheses (`E1000`; §2.2 lambda-frame rule). The formatter indents `do` and `end` one level deeper than the line where the lambda starts.
- A lambda body is a **single expression** between `do` and `end`. For multiple statements, write a named top-level function.
- Lambda parameter and return types must be written.
- Lambdas are **pure**: they can't perform effects (`E4002`) and can't capture `var`s (`E3071`).
- Function types are written `function(Int) returns Int`.

### 8.4 The entry point

```
public function main() returns Unit                     # or: returns Result[Unit, MyError]
  uses Console
do
  ...
end
```

**Exit status**:

| Code | Meaning | Commands |
| :-- | :-- | :-- |
| `0` | Success | All. `tersa harness run` also exits 0 for any scored episode, even reward 0 |
| `1` | The command's own "no" | `tersa run` / `tersa sandbox`: `main` returned `Error`. `tersa test`: a test failed or trapped. `tersa fmt --check`: a file would change. `tersa harness validate`: the task failed its gate |
| `2` | A trap in `main` | `tersa run`, `tersa sandbox` |
| `3` | A check or parse failure | All that read source, including `E4010` and a file `tersa fmt` can't parse |
| `4` | Infrastructure or toolchain error | A file can't be read or written, an invalid limit, a task that can't be loaded, a wall-clock backstop: `tersa harness run` exits 4 for any `I` code |

When `main` returns `Error(e)`, the runtime writes `error: ` followed by `show(e)` (§5.14) and a newline to stderr, then exits with status 1.

---

## 9. Contracts: requires, ensures, invariant

### 9.1 What they are

| Clause | Where | Checked | If it fails, blame goes to |
| :-- | :-- | :-- | :-- |
| `requires c` | Function header | On entry, before the body | The **caller** (trap `T6101`, points at the call site) |
| `ensures c` | Function header | On exit, after the body | The **function** (trap `T6102`) |
| `invariant c` | Record declaration | After construction and after every `with` update | The code that **built or updated** the record (trap `T6103`) |

```
public function withdraw(balance: Int, amount: Int) returns Int
  requires amount > 0
  requires amount <= balance
  ensures result == old(balance) - amount
  ensures result >= 0
do
  return balance - amount
end
```

### 9.2 Precise rules

1. **When checked:** at **run time, in every mode** (development, tests, RL). They can't be switched off in language 0.1.
2. **Order:** all `requires` in source order, then the body, then all `ensures` in source order.
3. **`result`** is the return value (only inside `ensures`). **`old(e)`** is `e` as it was on entry (only inside `ensures`, `E5001` elsewhere).
4. **Purity:** contracts cannot perform effects, use `var`s, or use resources (`E5002`). They may call pure functions.
5. **A contract that traps** (for example, by dividing by zero) counts as a violation of that contract (`T6104`).
6. **Fuel:** checking contracts uses fuel like any other code.
7. **Interfaces:** contracts written on an interface apply to every implementation. Implementations may add `ensures`, but not `requires` (`E5010`).
8. **Optional** in your own code, but required on public standard library functions. In RL tasks, the task's contracts are what count. Your own contracts help you, but never earn reward.

### 9.3 What a violation looks like

Calling `withdraw(10, 50)`:

```
trap[T6101]: precondition failed: amount <= balance
  --> bank.tersa:3:12
  = called from here (bank.tersa:21:15)
  = blame: caller
  = amount = 50
  = balance = 10
```

### 9.4 Record invariants

Records are immutable, so an invariant only needs checking when a record is created or updated. Reading fields never re-checks it.

### 9.5 Contracts are checked, not proven (yet)

In language 0.1, a passing contract means "it held on the inputs that ran", which is verification level L2 (§14.5). Proving contracts for all inputs (L3) is planned for later.

---

## 10. Error Handling: Results and Traps

### 10.1 Two kinds of failure

| | Expected failures | Bugs |
| :-- | :-- | :-- |
| Examples | File not found, bad user input, network down | Fixed-width overflow, integer size cap exceeded, division by zero, bad index, failed contract, `fail` |
| Mechanism | **Values:** `Result[T, E]` or `Option[T]` | **Traps:** the program stops (or, in tests, that one test stops) |
| Can code recover? | Yes, by matching on the value | **No.** Traps can't be caught in language 0.1 |
| Output | Your own error type | A structured diagnostic with a `T6xxx` code, location, call stack, and values |

**There are no exceptions.** Why: exceptions create invisible jumps that models and reviewers both miss, and "catch everything" handlers can hide real failures, including from test harnesses.

### 10.2 `try`: propagate errors

**Rule.** `try e`:
- if `e` is `Ok(v)` or `Some(v)`, `try e` is `v`;
- if `e` is `Error(x)` or `None`, the **enclosing function immediately returns** `Error(x)` or `None`.

The enclosing function must return a `Result` with **the same error type**, or an `Option` (`E3060`). Convert error types explicitly with `map_error`.

```
public function load_config(path: Text) returns Result[Config, ConfigError]
  uses FileRead
do
  let text = try File.read_text(path).map_error(function (e: FileError) returns ConfigError
    do
      Unreadable(path)
    end)
  let config = try parse_config(text)          # parse_config returns Result[Config, ConfigError]
  return Ok(config)
end
```

Incorrect (error types differ):

```
let text = try File.read_text(path)            # ERROR E3060: try returns FileError, but load_config returns Result[_, ConfigError]
                                               # fix: add .map_error(...) to convert FileError into ConfigError
```

### 10.3 Ignoring results is an error

A `Result` that is neither matched, propagated with `try`, nor explicitly discarded is error `E3002`. An ignored `Option` is only a warning (`W3001`, §7.1).

### 10.4 Traps you will see

| Code | Trap |
| :-- | :-- |
| `T6001` | `Int64` overflow (`Int` never overflows) |
| `T6002` | Division by zero (integer) |
| `T6003` | `Int` too large to convert to `Float` (`Float.from_int`) |
| `T6010` / `T6011` | Text slice or list index out of range |
| `T6020` | `expect_some` on `None` |
| `T6030` | `fail` was executed |
| `T6031` | An `expect` in a test was false |
| `T6101` / `T6102` / `T6103` / `T6104` | requires / ensures / invariant failed, or a contract itself trapped |
| `T6201` / `T6202` / `T6203` | Out of fuel / memory units / call depth |
| `T6204` | Integer size limit exceeded (an `Int` result bigger than the run's cap) |
| `T6301` | Capability scope violation (for example, reading outside the allowed folder) |
| `T6401` / `T6402` | Python interop error / foreign value can't be converted (for example a Python `int` outside the `Int64` range) |

`fail` (`T6030`) and failed `expect` (`T6031`) trap like any other bug.

---

## 11. Effects, Capabilities, Determinism, and Limits

### 11.1 Effects: declaring what a function may do

**Rule.** A function that performs I/O or other effects lists them after `uses`. A function's effects must include the effects of everything it calls (`E4001`). A function with no `uses` is **pure**: same inputs, same output, no side effects.

| Effect | Allows | Notes |
| :-- | :-- | :-- |
| `Console` | Print, read from the console | Output size is capped |
| `FileRead` / `FileWrite` | Read / write files | Limited to granted folders |
| `Net` | HTTP requests | Limited to granted hosts |
| `Clock` | Current time | Virtual (fixed) clock in RL mode |
| `Random` | Random numbers | Seeded by the host, so reproducible |
| `Env` | Environment variables, command-line arguments | Allowlisted names |
| `Python` | Calling Python (`foreign`) | Host mode only, never in sandbox or RL mode |

```
public function greet(name: Text) returns Unit
do
  print(name)      # ERROR E4001: greet calls print, which uses Console. Add "uses Console" to greet
end
```

### 11.2 Capabilities: what the host grants

- When a program starts, the host (`tersa run`, the test runner, the RL harness) **grants** capabilities: `tersa run app.tersa --allow Console --allow FileRead=./data`.
- `FileRead`, `FileWrite`, and `Net` are scoped and need an explicit scope: `--allow FileRead=FOLDER`, `--allow FileWrite=FOLDER`, `--allow Net=HOST`. A scoped effect with no scope or an empty one, an unscoped effect given a scope (`--allow Console=x`), and an unknown or mis-cased effect name are `I9010`, exit 4, before anything runs. In RL mode an `--allow` for `FileRead`, `FileWrite`, `Net`, or `Python` is `I9017`, exit 4.
- If `main` uses an effect that wasn't granted, the program is **refused before running** (`E4010`). That is the only use of `E4010`.
- If a call reaches an effect that wasn't granted **while running**, for example inside a test, it traps **`T6302`** "Effect was not granted".
- Scoped grants (folders, hosts) are checked on every call (trap `T6301`).
- Packages also declare a **capability ceiling** in `tersa.toml`. No module in the package may use effects beyond it.

### 11.3 Determinism guarantee

> Given the same source, toolchain version, inputs, capability grants, and seed, an Tersalang program produces **byte-identical** output, diagnostics, test results, and reward, on every supported platform.

What makes it work:
- Maps and sets iterate in insertion order.
- Hash values are never visible.
- One NaN bit pattern.
- No hidden fused multiply-add.
- A pinned Unicode version. If the runtime's Unicode tables don't match the language version's pin, the run is refused before it starts (`I9011`).
- Time and randomness only through `Clock` and `Random` (virtual or seeded).
- Exact `Int` arithmetic, with the size cap checked by bit length (not time).
- Limits measured in fuel, not seconds.
- No threads.

### 11.4 Resource limits

| Limit | Unit | When exceeded |
| :-- | :-- | :-- |
| Fuel | Evaluation steps, per the fuel table v0.1 (Design Doc §12.5) | Trap `T6201` |
| Memory | Memory units, per the memory-unit table v0.1 (Design Doc §11.4; cumulative allocation, not real bytes, so the result is deterministic) | Trap `T6202` |
| Call depth | Number of nested calls | Trap `T6203` |
| Integer size | Maximum bits in any `Int` value. **Default 65,536 bits** (about 19,728 decimal digits). Set per run by the host (CLI `--max-int-bits`, task file `max_int_bits`, or host app). Hosts and task files may lower it; raising it above 65,536 needs explicit host configuration. Minimum 64 | Trap `T6204` |
| Output | Bytes written to the console | Truncated and reported as warning `W6205`; the run continues, and an RL episode is not discarded |

**Default limits per mode:**

| Limit | `dev` (`tersa run`) | `test` (`tersa test`) | `rl` (`tersa harness`) | `host` (embedding) |
| :-- | :-- | :-- | :-- | :-- |
| Fuel | Unlimited unless `--fuel N` | Unlimited unless `--fuel N` (per test) | Required in `task.toml` (> 0) | Set by the app |
| Memory units | Unlimited unless `--memory-units N` | Unlimited unless `--memory-units N` (per test) | Required in `task.toml` (> 0) | Set by the app |
| Integer size | 65,536 bits | 65,536 bits | 65,536 bits, or lower if the task says so | 65,536 bits unless the app configures otherwise |
| Call depth | 1,000 | 1,000 | 1,000, or lower | 1,000 unless the app configures otherwise |
| Console output | Unlimited | 1,048,576 bytes per test | 1,048,576 bytes unless the task sets lower | Set by the app |

An invalid limit configuration (for example an integer cap below 64, or a task file that tries to raise a limit) stops the run before it starts (`I9010`). So does a bad host grant (§11.2).

Wall-clock time is a safety backstop. For `tersa sandbox` and `tersa run`, hitting it is an **infrastructure error** (`I9013`, exit 4). In the harness, a candidate's own clock is the trap `T6208` (`Wall-clock limit exceeded`): reward 0, correctness 0, efficiency 0, exit 2. The host cannot be told apart from a slow program, so that clock is not a discard. A reference stopped during validation or measurement keeps `I9013` on that reference episode. `tersa harness validate` then fails its gate and exits 1. `tersa harness run` falls back to the declared or limit basis with `E_basis_reason` `"reference_did_not_execute"`. The harness child also has an OS memory cap and an OS CPU cap on Linux and macOS (Design Doc §20.3). An OS memory kill of the candidate is `T6206`, message `OS memory limit exceeded`. An OS CPU kill is `T6207`, message `OS CPU limit exceeded`. Both score the same way and apply under every backend, including `none`. Windows does not apply those caps in this build. `I9023` is reserved. When the harness child is killed, or crashes without a classified signal, the episode lists every hidden test by name and marks the ones that never started as failed.

**Limits and codes in `tersa harness` and `tersa sandbox`** (as built; `tersa run` stays unlimited unless you pass flags):

| Limit | Set by | Default | When exceeded | Episode outcome |
| :-- | :-- | :-- | :-- | :-- |
| Fuel | `task.toml` `fuel` (required, > 0); `tersa sandbox --fuel` | Harness: none (required). Sandbox: 100,000 until `--fuel` | Trap `T6201` | Scored failure (`limit_hit = "fuel"`) |
| Memory units | `task.toml` `memory_units` (required, > 0); `--memory-units` | Harness: none (required). Sandbox: 100,000 until `--memory-units` | Trap `T6202` | Scored failure (`limit_hit = "memory"`) |
| Call depth | `call_depth`; `--max-depth` | 1,000 (allowed 1–1,000) | Trap `T6203` | Scored failure (`limit_hit = "depth"`) |
| Integer size | `max_int_bits`; `--max-int-bits` | 65,536 bits (allowed 64–65,536) | Trap `T6204` | Scored failure (`limit_hit = "int"`) |
| Console output | `output_bytes`; `--output-bytes` | Harness: 1,048,576 bytes (the maximum). Sandbox: 1,048,576 until `--output-bytes` | Output truncated, warning `W6205` | Run continues; the episode is kept and scored |
| Wall clock (backstop) | `wall_ms`; `--wall-ms` | Harness: 5,000 ms in-process, plus a 30 s timeout on the child process. Sandbox: 5,000 ms until `--wall-ms` | Candidate: `T6208`. Sandbox, `tersa run`, and the reference episode during validation or measurement: `I9013` | A candidate scores reward 0 with correctness 0 and efficiency 0 (exit 2). Sandbox and `tersa run` stay infrastructure (`reward` null, exit 4). A stopped reference fails `tersa harness validate` (exit 1). `tersa harness run` uses `E_basis_reason` `"reference_did_not_execute"` |

In RL mode a task can't grant `FileRead`, `FileWrite`, `Net`, or `Python`. `Env` is available only when `task.toml` lists fixed values. If `main` declares an effect that was not granted, the run is refused before it starts (`E4010`). A call that runs without its grant, including inside a test, traps `T6302`.

### 11.5 Concurrency

There are **no threads, async, or shared memory** in language 0.1. Programs run single-threaded, and I/O calls block. Deterministic parallel loops and message passing are planned for later, and their keywords are already reserved.

---

## 12. Resources: `using`

**Rule.** Resource types (such as `File`) MUST be bound with a `using` block (`using f = …`, then `do` on its own line, then `end`). They are closed automatically at `end`, or when a trap leaves the block. They can't be stored, returned, put in collections, or captured (`E3072`). Nested `using` blocks close in reverse order. There are no finalizers.

```
public function first_line(path: Text) returns Result[Option[Text], FileError]
  uses FileRead
do
  using f = try File.open(path)
  do
    return Ok(f.read_line())
  end
end
```

**Why.** Cleanup happens at a predictable point, every time, which keeps programs deterministic and stops them from leaking file handles.

---
## 13. Modules, Imports, Manifest, and Lockfile

### 13.1 Modules

**Rules:**
- One file is one module. The `module` line MUST match the file's path under the package's `src/` folder (`E2001`). For example, `src/geometry/shapes.tersa` must be `module geometry.shapes`.
- The first part of every module path is the package name.
- A standalone file outside any package uses its file name as the module name (`hello.tersa` → `module hello`). The name must be a valid lowercase name and match the `module` line (`E2001`). A standalone file may import only `std.*` modules.
- Declarations are **private by default**. `public` exports them.
- Import cycles are errors (`E2002`, which shows the cycle; see Appendix C).
- Module constants (`let` at top level) must have a type and a pure value. They are evaluated once, in dependency order, before `main` runs. A cycle among constants is `E2003`. If a constant's value traps, the program stops before `main` (exit status 2).
- `std.core` (Option, Result, Ordering, built-in types and their helpers) is imported automatically.

### 13.2 Imports

| Form | Then you write |
| :-- | :-- |
| `import geometry.shapes` | `shapes.area(r)`, `shapes.Rect(...)` (the last path segment is the qualifier) |
| `import geometry.shapes as gs` | `gs.area(r)` |
| `import geometry.shapes exposing Rect, area` | `area(r)`, `Rect(...)` |

Two imports with the same qualifier, or a qualifier that equals a top-level name in the module, is `E2004`. Fix it with `as`.

- **Prelude names can't be re-imported.** Everything in the prelude (§15: built-in types, `Option`, `Result`, `Ordering`, `Entry`, `show`, `PythonError`, and the prelude types `File`, `FileError`, and `Utf8Error`) is already in scope. Exposing a name that is already in scope, from the prelude or from another import, is `E2021` (duplicate name). So write `import std.file` only if you need other names from it; never `exposing File, FileError`.
- **Unknown module member (`E2005`).** A name after `exposing`, or after a module qualifier (`shapes.nope`), that the module doesn't define or doesn't make `public` is `E2005`. The same code is used if an unknown module member is reached at run time. The message says which case applies.

```
import geometry.shapes exposing Rect, Hexagon   # ERROR E2005: geometry.shapes has no public member Hexagon
import std.file exposing File                   # ERROR E2021: File is already in scope (prelude)
```

There are no wildcard imports (`import x.*` doesn't exist). **Why:** every name in a file can be traced to exactly one import.

### 13.3 Package layout

```
geometry/
  tersa.toml
  tersa.lock
  src/geometry/shapes.tersa
  src/geometry/main.tersa
  tests/
  examples/
```

### 13.4 Manifest `tersa.toml`

```toml
[package]
name = "geometry"
version = "0.1.0"
language = "0.1"                  # Tersalang language version
license = "Apache-2.0"
description = "Shapes and areas"
authors = ["Your Name"]

[capabilities]
ceiling = ["Console", "FileRead"] # no module here may use other effects
mode = "sandbox"                  # or "host" to allow foreign (Python) declarations

[dependencies]
textutils = { git = "https://github.com/example/textutils", rev = "<full commit hash>" }
shapes = { path = "../shapes" }

[dev-dependencies]
proptest_helpers = { path = "../proptest_helpers" }
```

### 13.5 Lockfile `tersa.lock`

Written by tools, never by hand. It records the exact source and a content hash for every dependency. A hash mismatch stops the build (`E2101`; not implemented in the interpreter yet).

```toml
lock_version = 1
language = "0.1"

[[package]]
name = "textutils"
version = "0.2.1"
source = "git+https://github.com/example/textutils#<full commit hash>"
hash = "sha256:<hash>"
capabilities = ["Console"]
```

**Dependency rules:** local paths or git repos pinned to a full commit hash. There is no central registry yet, and only one version of each package per build.

---

## 14. Testing and Verification Levels

### 14.1 Test blocks

```
test "withdraw reduces the balance"
do
  expect withdraw(100, 30) == 70
end
```

**Rules:**
- A `test "name"` block (header, then `do` on its own line, then `end`) is a top-level declaration. `expect condition` is only allowed in tests (`E2011`).
- Each test runs in **fresh state**, in source order. A trap fails only that test, and the others still run.
- Tests get no capabilities unless the test runner grants them.

### 14.2 Property tests

```
test "add is commutative" for all a: Int, b: Int
do
  expect add(a, b) == add(b, a)
end
```

The runner generates many inputs from a seed. On failure, it shrinks the input to a minimal counterexample and reports it with the seed, so you can reproduce it exactly. The default is **100 cases per property**; the host can change it (`--cases N`, or the task file).

**Built-in generators:** every built-in type except function types, resource types, and mutable collections, plus records and choices whose fields all have generators. Generic types must be instantiated (`List[Int]`, not `List[T]`).
- `Int` values stay within the run's integer cap and favor small values and boundaries (0, ±1, and the `Int64` limits).
- `Float` values include NaN, ±infinity, and −0.0.
- `Text` values include non-ASCII characters.
- Generated record values that would break an invariant are discarded and don't count as cases.

### 14.3 Doc examples

```
## Example: add(2, 3) == 5
```

Every `Example:` line in a doc comment runs as a test, and must evaluate to `true`.

### 14.4 Your tests vs. hidden task tests

| Kind | Written by | Where | Counts toward an RL reward? |
| :-- | :-- | :-- | :-- |
| `test` blocks and doc examples | You (human or model) | Next to the code | **No.** They're for your own feedback |
| Harness ("hidden") tests | The task author | A separate package you never see | **Yes** |
| Task contracts | The task author | `interface.tersa`, shown to you | **Yes**: they replace your function's own contracts |

**Why:** if the code's author also wrote the tests that grade it, the grade could be gamed. Hidden tests keep rewards honest.

**How an RL task scores your solution** (`tersa harness run`; Design Doc §22):

- You see `prompt.md`, `interface.tersa`, and `visible_tests.tersa`. The interface file's module has a name such as `task_spec` (`interface` is a keyword). For example:

```
module task_spec

interface Solution
  function add_one(n: Int) returns Int
    ensures result == n + 1
end
```

- Write an ordinary module with a **free function** of that name, for example `function add_one(n: Int) returns Int`. Don't write `implements` for the task's interface. The harness copies the interface's `requires`/`ensures` onto your function and **replaces** your own, so `ensures true` changes nothing. Helper functions the interface doesn't name **keep their own contracts**, and those still run. Your `test` blocks and `main` are not used. Your own `interface` declarations and `implements` blocks are kept, so a helper interface works.
- Each function the interface requires must have the same name, type parameters (by position, so `T` and `U` match) and constraints, parameter types, and return type. Parameter names, `public`, contracts, and effects are not compared. A missing or different function is `E3047`: the run stops at the check stage and scores 0 (not `check_credit`), and the message names the difference, for example ``error[E3047]: `add_one` does not match interface.tersa: it returns `Text`, the interface says `Int` ``. The task author's reference solution is held to the same rule when the task loads (`I9025`).
- Each hidden test runs in a fresh interpreter with the same seed. Correctness `C` = `check_credit + (1 − check_credit) × passed / total`. A parse error, a function that does not match the interface (`E3047`), and zero hidden tests use `C = 0`; any other check error uses `C = check_credit` (default 0). A parse or check failure also sets `E = 0`, because the candidate did not run. The reference basis is used only when the reference executes and passes every hidden test. Then `ref_fuel` is the fuel it uses on those tests under the same limits and seed, and `E = min(1, max(ref_fuel, 1) / max(fuel_used, 1))`. A reference that used no fuel still counts as 1, so a correct reference scores `E = 1`. Matching or beating the reference is 1, twice the fuel is 0.5, and ten times the fuel is 0.1. Otherwise `E = max(0, 1 − fuel_used / fuel)`, `E_basis` is `"limit"`, and `E_basis_reason` is `"no_reference"`, `"reference_did_not_execute"`, or `"reference_failed_hidden_tests"`. The reward is `(1 − w) × C + w × C × E`, where `w` is `efficiency_weight` (default 0.1, set per task in `task.toml`, 0..1). A fast wrong program earns nothing extra. With every hidden test passing, the default weight puts the reward between 0.9 and 1. There is no clip. `w = 0` leaves the reward equal to `C`. The `add_one` reference uses 88 fuel, so `E` is 1 and the reward is 1. The harness measures `ref_fuel` by running the reference and caches it per seed. The floor applies only inside the formula: `breakdown.ref_fuel` reports the raw measured fuel, including 0. `check_credit` can't make a failing reference count: it must pass every hidden test.

| Example: the `add_one` reference | Value |
| :-- | :-- |
| Hidden tests passed | 2 of 2, so `C = 1` |
| Reference fuel `ref_fuel` (`h_forty_one` 16 + `h_property` 72) | 88 |
| Candidate `fuel_used` (the reference itself) | 88 |
| `E = min(1, max(88, 1) / max(88, 1))`, `E_basis`, `E_basis_reason` | 1, `"reference"`, `null` |
| `w` | 0.1 |
| Reward `0.9 × 1 + 0.1 × 1 × 1` | **1.0** |

`C`, `E`, `w`, and the reward are rounded to 10 decimal places and must each be in [0, 1]. `w` outside 0..1 is `I9018`; a `w` that isn't a number is `I9022`. On the limit basis, a fuel limit that isn't positive gives `E = 0` (a task can't load without a positive limit anyway).
- `[reward] reference_fuel` in `task.toml` is optional. A run trusts it only when the reference measurement is not available. `tersa harness validate` runs the reference and fails the task if the number doesn't match, and also if the reference does not pass every hidden test. A value that isn't an integer ≥ 0 is `I9022`. When it stands in, `E_basis` is `"declared"`, `ref_fuel` is the declared number, and `E_basis_reason` is `"no_reference"` or `"reference_did_not_execute"`. The same formula applies, including the `max(ref_fuel, 1)` floor. It is never used when the reference ran and failed hidden tests, and the reference is still run first, so it doesn't skip that run.
- Fuel, memory, depth, and integer-cap traps are scored failures. Truncated output (`W6205`) is kept. A candidate wall-clock stop (`T6208`), OS memory kill (`T6206`), or OS CPU kill (`T6207`) scores reward 0 with correctness 0 and efficiency 0. `I9013` discards a sandbox run and a `tersa run`. A reference stopped during validation or measurement keeps `I9013` on that reference episode: `tersa harness validate` exits 1, and `tersa harness run` uses `E_basis_reason` `"reference_did_not_execute"`. If the interpreter process dies without a result and without one of those OS kills, the score is 0 with correctness 0, and every hidden test is listed as failed.
- The result is one `tersa.result/0.9` JSON object. `breakdown` holds `C`, `E`, `E_basis` (`"reference"`, `"declared"`, or `"limit"`), `E_basis_reason`, `ref_fuel`, and `w`; `reward` is the formula above. `E_basis_reason` is `null` on the reference basis. On the declared basis it names why the reference could not be measured. `isolation` is the backend that actually ran (`none`, `rlimit`, or `bwrap`; `nsjail` and `gvisor` are accepted names but this build does not launch them). `isolation_warning` is null, or the list of stronger backends that were skipped. An infrastructure error sets `reward` and the breakdown to `null`. A crashed interpreter process scores 0 with correctness 0 and efficiency 0, and lists every hidden test as failed. `crash` is `null`, `{"type": "process", ...}`, or `{"type": "invalid_result", ...}` when the child's JSON fails `result.schema.json` or does not echo the attempt, task, and backend the parent sent. `tersa.result/0.8` adds `"invalid_result"`. Both crash types score 0 with `C = 0`. What you get back is filtered: no per-case details and no stdout. Diagnostics from your own parse and check keep full detail (the first `attempt_diagnostics` of them). Any diagnostic raised while your code was checked with the hidden tests or ran them keeps only its code, one position in public code (or `<hidden>`), and the message `raised while checking or running the hidden tests; details are withheld`, so contract values, trap and `fail` text, and related spans never reveal a hidden input, expected value, or name. Fuel and memory used and `ref_fuel` are rounded down to a power of two, and `E` and the reward are recomputed from them, so they are approximate in your copy; the trainer's copy is exact (Design Doc §22.5).
- `tersa harness validate TASK_DIR` is for task authors: the reference solution must execute and pass every hidden test, and every mutant must have correctness below 1. So a mutant that is still fully correct but uses more fuel survives and fails validation. The reference matches its own fuel, including when that fuel is 0, so a correct reference scores 1. A `reference_fuel` value that does not match the reference run fails the task. Mutants are single edits to function, test, and `implements` bodies (never contracts): operator swaps such as `+`↔`-` or `<`↔`>`, literal tweaks, removing `not` or a unary minus, and replacing a returned value with a literal of the function's declared type (`0`/`1` for `Int`, `true`/`false` for `Bool`, `0.0`/`1.0` for `Float`, `""`/`"mut"` for `Text`; nothing for other types). Mutants are drawn round-robin across kinds of edit, in an order seeded from the SHA-256 of the source, until 16 **well-typed** ones are kept. A mutant that doesn't parse or type-check is skipped, not counted as killed. If none can be made, the report has a warning but the task isn't failed for that alone.
- A task that can't be loaded is refused with its own code and `tersa harness` exits 4:

| Code | Cause |
| :-- | :-- |
| `I9014` | `task.toml` is missing |
| `I9015` | `language` doesn't match the interpreter |
| `I9016` | `effects` names something that isn't an effect (the part before `=` when an entry has one) |
| `I9017` | `effects` lists `FileRead`, `FileWrite`, `Net`, or `Python`, with or without a scope (`FileRead=data` is refused too; the same refusal applies to an `--allow` in `tersa sandbox`, `run --mode rl`, and `test --mode rl`) |
| `I9010` | A limit is missing, not above 0, or out of range, or an `effects` entry gives a scope to an effect that takes none (`Console=out`) |
| `I9018` | `check_credit` or `efficiency_weight` is a number outside 0..1 |
| `I9019` | `property_seed_policy` isn't `per_episode` or `fixed` |
| `I9020` | `hidden/` is missing or has no `.tersa` file |
| `I9021` | A hidden test file or a non-empty `interface.tersa` doesn't parse |
| `I9022` | `task.toml` doesn't decode, or a field has the wrong type (including a limit that is present but not an integer, a reward weight that is not a number, and a `reference_fuel` that is not an integer ≥ 0) |
| `I9024` | The requested isolation backend cannot be launched |
| `I9025` | `reference/solution.tersa` lacks a function `interface.tersa` requires, or declares it differently |
| `T6206` | The candidate hit the OS memory cap (scored trap, reward 0, exit 2) |
| `T6207` | The candidate hit the OS CPU cap (scored trap, reward 0, exit 2) |
| `T6208` | The candidate hit its own wall clock (scored trap, reward 0, exit 2) |

### 14.5 Verification levels

| Level | Meaning | How |
| :-- | :-- | :-- |
| **L0 Parsed** | Matches the grammar | `tersa check --parse-only` |
| **L1 Typed** | Names, types, and effects check; matches are exhaustive | `tersa check` |
| **L2 Tested** | Contracts held and tests passed *on the inputs that ran* | `tersa test` |
| **L3 Verified** | Contracts proven for all inputs | Planned (later) |

---

## 15. Standard Library v1 Overview

These names are decided for language 0.1-draft (Design Doc §15).

| Module | Key contents | Effect |
| :-- | :-- | :-- |
| `std.core` (auto-imported) | Built-in types. `PythonError` (record: `type_name: Text`, `message: Text`; used by `foreign` calls, §16.1). `Bytes.from_hex` / `Bytes.from_list` (→ `Option[Bytes]`) and `Bytes.of_hex` / `Bytes.of_list` (→ `Bytes`, trap `T6013`). Prelude types re-exported from other modules: `File`, `FileError` (from `std.file`), and `Utf8Error` (from `std.text`); using `File` operations still requires `uses FileRead` or `FileWrite`. `Option`/`Result`/`Ordering` and their helpers (`map`, `map_error`, `and_then`, `unwrap_or`, `expect_some`). `Int.compare`, `Int.parse` (→ `Option[Int]`), `Int64` with `from_int`/`to_int`/`checked_add`/`checked_sub`/`checked_mul`/`min`/`max`, `Float.from_int`, `Int.from_float`, `Float.total_compare`, `Float.same`, `Entry[K, V]`, `show` | none |
| `std.list` | `get`, `at`, `with_appended`, `with_item`, `length`, `is_empty`, `contains`, `map`, `filter`, `fold`, `sort` (stable), `zip_with`, `List.range`, `List.empty` | none |
| `std.map` | `get`, `with_entry`, `without_key`, `contains_key`, `keys`, `entries`, `length`, `is_empty` | none |
| `std.set` | `Set.from_list`, `contains`, `with_element`, `without_element`, `length`, `is_empty` | none |
| `std.mutable` | `MutableList.new`, `push`, `get`, `set_at`, `length`, `freeze`; `MutableMap.new`, `insert`, `remove`, `get`, `keys`, `entries`, `length`, `freeze` | none |
| `std.text` | `concat`, `join`, `split`, `trim`, `find`, `replace`, `slice`, `try_slice`, `code_points`, `code_point_count`, `byte_length`, `graphemes`, `to_upper`, `to_lower`, `normalize_nfc`, `normalize_nfd`, `from_utf8`, `join_lines`, `is_empty` | none |
| `std.math` | `min`, `max`, `abs`, `clamp`, `gcd`, size-capped integer `pow`, `sqrt`. Transcendental functions (`sin`, `cos`, `tan`, `asin`, `acos`, `atan`, `atan2`, `exp`, `log`, `log2`, `log10`, `float_pow`) are unavailable in RL mode (`E4011`). No bitwise functions | none |
| `std.json` | Parse into a `Json` choice. Serialize. Errors as values | none |
| `std.testing` | Generators for property tests. `approx(a, b, tolerance)` | tests only |
| `std.console` | `print`, `print_error`, `read_line` | `Console` |
| `std.file` | `File.open` (resource), `read_line`, `read_text`, `write_text`, `list_dir` (sorted) | `FileRead` / `FileWrite` |
| `std.clock` | `now`, `monotonic` | `Clock` |
| `std.random` | `Random.int`, `Random.float`, `shuffle` | `Random` |
| `std.env` | `args`, `get` | `Env` |
| `std.net` | Basic HTTP GET/POST | `Net` |

**Not in v1:** regular expressions, bitwise operations, dates and time zones, databases, GUIs, async.

Every public stdlib function has a full signature, a doc comment, a runnable example, contracts where meaningful, a documented complexity, and a fuel cost class.

---

## 16. Python Interop Tiers

| Tier | Where | Python? | Deterministic? |
| :-- | :-- | :-- | :-- |
| **T0 Sandbox** | RL tasks, benchmarks, playgrounds | No | Yes |
| **T1 Vetted** | RL tasks (optional) | No. Vetted features are rebuilt in Tersalang or the stdlib | Yes |
| **T2 Host** | Your own apps, with `mode = "host"` in `tersa.toml` | Yes, via `foreign` | No (marked by `uses Python`) |

### 16.1 Calling Python from Tersalang (T2 only)

```
foreign "python:math.factorial" function factorial(n: Int) returns Int
  uses Python
  requires n >= 0
```

**Rules:**
- The string is `"python:<module>.<name>"`. The declaration MUST include `uses Python`.
- Arguments and results are converted (table below), and contracts are checked on both sides. A value that can't be converted to its declared type at run time traps `T6402` (for example a Python `int` outside the `Int64` range, or a Python `str` where `Int` is declared). Types with no conversion at all are rejected at check time (`E4020`).
- A Python exception becomes trap `T6401`. If you declare the return type as `Result[T, PythonError]`, it becomes `Error(PythonError(type_name = …, message = …))` instead. `PythonError` is a prelude record:

```
record PythonError     # in the prelude (std.core)
  type_name: Text      # the Python exception's class name, for example "ValueError"
  message: Text        # str() of the exception
end
```

```
foreign "python:math.factorial" function try_factorial(n: Int) returns Result[Int, PythonError]
  uses Python
# try_factorial(-1) returns Error(PythonError(type_name = "ValueError", message = "factorial() not defined for negative values"))
```
- `foreign` is rejected at load time in sandbox or RL mode, and in packages without `mode = "host"`.

| Tersalang | Python |
| :-- | :-- |
| `Int` | `int` (exact both ways; beyond the run's size cap → trap `T6204`) |
| `Int64` | `int` (out of the `Int64` range → trap `T6402`) |
| `Float` | `float` (NaN canonicalized) |
| `Bool`, `Text`, `Bytes` | `bool`, `str`, `bytes` |
| `List[T]` | `list` |
| `Map[Text, V]` | `dict` with string keys, order kept |
| `Option[T]`, `Unit` | value or `None` |
| Records and choices | A dict with a `"$type"` key |
| Functions, resources | Not convertible (`E4020`) |

### 16.2 Calling Tersalang from Python (T2)

```python
import tersalang                      # planned Python API
pkg = tersalang.load("path/to/geometry")
pkg.call("area", {"$type": "Rect", "width": 3, "height": 4})
```

---

## 17. Diagnostics (Error Format)

Every error, warning, and trap is produced first as JSON. The human-readable text is generated from it.

### 17.1 Compile-time diagnostic (JSON)

```json
{
  "schema": "tersa.diagnostic/0.1",
  "code": "E3030",
  "severity": "error",
  "category": "type",
  "message": "match on Shape is not exhaustive",
  "file": "src/geometry/shapes.tersa",
  "span": {"start": {"line": 12, "column": 3}, "end": {"line": 15, "column": 6}},
  "related": [{"message": "missing case: Square", "file": "src/geometry/shapes.tersa",
               "span": {"start": {"line": 3, "column": 3}, "end": {"line": 3, "column": 22}}}],
  "blame": null,
  "values": null,
  "fix": {"description": "add the missing cases",
          "edits": [{"span": {"start": {"line": 15, "column": 3}, "end": {"line": 15, "column": 3}},
                     "insert": "case Square(_) then\n  ...\n"}]},
  "docs_url": "https://<docs-site>/diagnostics/E3030"
}
```

### 17.2 Runtime trap (JSON)

```json
{
  "schema": "tersa.diagnostic/0.1",
  "code": "T6101",
  "severity": "error",
  "category": "contract",
  "message": "precondition failed: amount <= balance",
  "file": "src/bank/main.tersa",
  "span": {"start": {"line": 3, "column": 12}, "end": {"line": 3, "column": 29}},
  "related": [{"message": "called from here", "file": "src/bank/main.tersa",
               "span": {"start": {"line": 21, "column": 15}, "end": {"line": 21, "column": 31}}}],
  "blame": "caller",
  "values": {"amount": "50", "balance": "10"},
  "fix": null,
  "docs_url": "https://<docs-site>/diagnostics/T6101"
}
```

`T6102` is "postcondition failed: <condition>" and `T6103` is "invariant failed: <condition>" (related: "`R` built or updated here"). `values` also includes field paths, `result`, and `old(...)`.

As built, `docs_url` is `https://github.com/kevindm-design/tersalang/blob/main/docs/diagnostics.md#` plus the lowercased code (for example `#t6101`), a generated page with the catalog text.

`values` is a JSON object (or `null`): each key is the source text of a name or sub-expression from the failed condition, in order of first appearance, and each value is its canonical text form (§5.14; a value that isn't `Showable` renders as a placeholder such as `<function>`) as a string.

### 17.3 Fields

| Field | Meaning |
| :-- | :-- |
| `code` | Stable code, never reused |
| `severity` | `error`, `warning`, or `info` |
| `category` | lexical, syntax, name, type, effect, contract, runtime, limit, capability, interop, infrastructure |
| `message` | One plain-English line |
| `span` | 1-based line and column, start to end |
| `related` | Extra locations (missing cases, call sites) |
| `blame` | `"caller"` (failed `requires`), `"function"` (failed `ensures`), `"constructor"` (failed invariant, on construction or a `with` update), or `null` |
| `values` | For traps: relevant values, in canonical text form |
| `fix` | A suggested fix. `edits` can be applied automatically when present |
| `docs_url` | A page with a wrong example and a fixed example |

### 17.4 Code ranges

`E00xx` lexical · `E1xxx` syntax · `E2xxx` names and modules · `E3xxx` types · `E4xxx` effects and capabilities · `E5xxx` contract rules · `T6xxx` runtime traps · `W…` warnings · `I9xxx` infrastructure.

**Authoritative code list.** The file `spec/diagnostics.yaml` in this repository is the authoritative list of diagnostic codes and their meanings. This reference and the Design Doc mirror it; if they ever disagree, the YAML file wins and the docs are corrected. A CI test in the repo checks that the catalog, the codes the interpreter emits, and the tests stay in sync. Codes marked `reserved` are retired and never reused. New codes are added there first, within these ranges, and a code is never reused.

---

## 18. Formatting and Style

`tersa fmt` produces the one canonical format. It has no options.

| Rule | Detail |
| :-- | :-- |
| Indentation | 2 spaces per block level. No tabs |
| Line width | Maximum 100 characters. Long calls and literals break to one item per line, with trailing commas |
| Lines | One statement per line. LF endings. Exactly one final newline. No trailing spaces |
| Blank lines | One between top-level declarations. None right after `do` or `then` |
| Spacing | Spaces around binary operators. One space after `,` and `:`. No spaces inside brackets |
| Headers | `uses`, `requires`, `ensures` on their own lines, indented 2 spaces. `do` on its own line at the declaration's indentation |
| Lambdas | `do` and `end` on their own lines, one level deeper than the line where the lambda starts; the body one level deeper again |
| Imports | Sorted alphabetically. `exposing` lists sorted with types first, then values |
| `and`/`or` | Parentheses added when mixed |
| Naming | snake_case for lower names, PascalCase for Upper names (enforced by the lexer) |
| Guarantees | Running the formatter twice changes nothing. Formatting never changes program meaning |

**How `tersa fmt` behaves (CI runs `scripts/check_fmt.py`, which passes every corpus file the formatter can read to `tersa fmt --check`):**

| Topic | Behavior |
| :-- | :-- |
| Paths | `tersa fmt FILE...` rewrites files in place. A directory means every `.tersa` file under it. No paths: read stdin, write stdout |
| `--check` | Writes nothing. Prints `would reformat PATH` and up to 40 diff lines, and exits 1 if any file would change |
| Errors | Any file that doesn't parse, named directly or found in a directory: its parse diagnostic is printed, the file isn't written, exit 3. Read or write failure: exit 4. With several files, the highest code wins (a parse error beats a file that would change) |
| `# fmt: skip` | When the file parses, the whole file is left unchanged. A file that doesn't parse still exits 3 (§18.1) |
| Comments | Kept. Own-line comments stay above the code they precede; trailing comments stay on their line after two spaces. Extra blank lines collapse to one |
| Long lines | A line with no break point inside `()`, `[]`, or `{}` may exceed 100 columns. `uses`, import paths, and `for all` parameters never break |
| Spelling | `function(Int) returns Int` for function types; `function (x: Int)` for lambdas. Parentheses you wrote are kept |
| `and`/`or` | The first format may add one pair of parentheses around an `and` under an `or`; formatting again changes nothing |

**Style guidance (not enforced):** short functions, contracts on public functions, `Result` for anything that can fail for reasons outside the program, and `get` over `at` unless a bounds check is right there.

### 18.1 `# fmt: skip` (official)

See Design Doc §18.2.1. Put this line in a file to keep the formatter away from it:

```
# fmt: skip
```

| Rule | Detail |
| :-- | :-- |
| What counts | A line whose text, after removing leading and trailing whitespace, is exactly `# fmt: skip`: one `#`, one space, `fmt:`, one space, `skip`, lowercase. A line that isn't exactly that but matches, in any case, `#`, optional whitespace, `fmt`, optional whitespace, `:`, optional whitespace, `skip` with nothing else on it (tabs count as whitespace; for example `#fmt:skip`, `# FMT: skip`, `# fmt:skip`) is a near-miss: it warns `W1104` once per line and isn't a marker. `# fmt: skip (reason)` and a trailing `code  # fmt: skip` aren't near-misses and don't warn |
| Where | Any line: first, last, inside a function, indented or not. More than one marker is the same as one. Convention: near the top, with a comment above it saying why |
| Scope | The whole file. There is no per-line or region form |
| `tersa fmt` | The file is always parsed. When the marker is present and the file parses, it is returned unchanged: nothing is rewritten and the command exits 0; stdin is echoed unchanged. When the file doesn't parse, the diagnostic is printed and the command exits 3, marker or not, and the file isn't written. Only the rewrite is skipped |
| `tersa check` | A near-miss warns `W1104`, with or without `--parse-only`. The message names the exact spelling `# fmt: skip`. The warning doesn't fail the check. The exact marker doesn't warn. `tersa run`, `tersa sandbox`, and `tersa test` print it, like every warning, only beside a check error or trap that stops the run; the harness never reports it. |
| `tersa fmt --check` | A skipped file that parses is exempt: never reported as needing a reformat. A skipped file that doesn't parse exits 3 |
| Decoding grammar | A skipped file that parses is exempt: the decoding profile (§18.2) doesn't have to accept it |
| Everything else | It's an ordinary comment. Running, tests, and the RL harness ignore it (the harness never reports `W1104`). A near-miss is formatted normally; a file with both the exact marker and a near-miss is skipped and still warns. Conformance test: `conformance/syntax/w1104_fmt_skip.tersa` |
| Use it for | Files whose exact layout is the point, such as test fixtures. The conformance suite uses it in three: the CRLF fixture, the newline-suppression fixture, and the `W1103` mixed `and`/`or` fixture |

### 18.2 Grammar exports (`tersa grammar`)

`tersa grammar --format ebnf|lark|gbnf [--profile full|decoding]` prints the grammar (`ebnf` is the default; `--kind` is a deprecated alias for `--format` and prints a deprecation warning on stderr). The GBNF is generated from the Lark grammar and is **standard llama.cpp GBNF** with no lookahead:

| Topic | Behavior |
| :-- | :-- |
| Keywords | Reserved in both profiles: a keyword is never a name and can't run into the next word (`functions` is a name) |
| Names | Follow the lexer in both profiles: no `__`, trailing `_`, or leading `_` in a lower name (`E0010`), no `_` in an Upper name (`E0011`), at most 64 characters (`E0012`) |
| Layout | Follows the lexer: a gap outside brackets stays on the line; a line break may go inside brackets and after a continuation token; a word after a word needs a space. `(a)and b` and `7mod 2` don't match, though the parser accepts them |
| Literals | Exponent-only floats such as `1e10` are accepted, and every text escape: `\"`, `\\`, `\n`, `\t`, `\r`, `\{`, `\}`, `\u{…}` (1 to 6 hex digits) |
| `--profile full` | Any layout the parser accepts except those two spellings. Rejects a same-line `do` like the parser. Comments are capped as in `decoding` (100 lines in the opening header, 30 in a row after code, 500 characters each); blank lines aren't |
| `--profile decoding` | Stricter separators: each gap is empty or one space, plus one line break where `full` allows one (LF, an optional two-space `#` comment, at most 30 comment lines, at most one blank line in a row, even indentation). Comments are at most 500 characters, and at most 100 comment lines open the file. No blank line opens the file. Tabs, CR, and runs of spaces don't match. `# fmt: skip` files are exempt |
| Decoding limits | It can't express the 100-column limit, which gap must be a space versus empty, or which allowed line break the formatter picks. `tersa fmt --check` remains the gate for those. `tersa fmt` keeps comments as written, so a formatted file with a comment over 500 characters, a header of more than 100 comment lines, or more than 30 comment lines in a row after code is rejected by both profiles |
| Validation | CI runs `scripts/check_gbnf.py`, the unit tests use the `llama_gbnf_accepts` recognizer, and the `gbnf-llama` job runs llama.cpp's own `test-gbnf-validator` on the corpus |

---
## 19. Complete Worked Example

An inventory report. It reads `name,quantity` lines from a file, validates them, adds up quantities per item, and prints a report. It uses records with invariants, a choice for errors, contracts, `try`, `map_error`, a lambda, `match` with a guard, `for`/`continue`, `var`/`set`, mutable collections, effects, doc examples, and tests.

```
module inventory

import std.console exposing print

## One validated line of the inventory file.
public record Item
  name: Text
  quantity: Int
  invariant name != ""
  invariant quantity >= 0
end

public choice InventoryError
  case CannotRead(path: Text)
  case BadLine(line_number: Int, text: Text)
end

## Parses one "name,quantity" line.
## Example: parse_line("apples,3", 1) == Ok(Item(name = "apples", quantity = 3))
public function parse_line(text: Text, line_number: Int) returns Result[Item, InventoryError]
  requires line_number >= 1
do
  let parts = text.split(",")
  if parts.length() != 2 then
    return Error(BadLine(line_number, text))
  end
  let name = parts.at(0).trim()
  match Int.parse(parts.at(1).trim())
    case Some(quantity) if quantity >= 0 and name != "" then
      return Ok(Item(name = name, quantity = quantity))
    case _ then
      return Error(BadLine(line_number, text))
  end
end

## Reads and parses every non-blank line of the file.
public function load(path: Text) returns Result[List[Item], InventoryError]
  uses FileRead
do
  let content = try File.read_text(path).map_error(function (e: FileError) returns InventoryError
    do
      CannotRead(path)
    end)
  let items: MutableList[Item] = MutableList.new()
  var line_number = 0
  for line in content.split("\n")
  do
    set line_number = line_number + 1
    if line.trim() == "" then
      continue
    end
    let item = try parse_line(line, line_number)
    items.push(item)
  end
  return Ok(items.freeze())
end

## Adds up quantities per item name, in first-seen order.
public function totals(items: List[Item]) returns Map[Text, Int]
  ensures result.length() <= items.length()
do
  let counts: MutableMap[Text, Int] = MutableMap.new()
  for item in items
  do
    let current = counts.get(item.name).unwrap_or(0)
    counts.insert(item.name, current + item.quantity)
  end
  return counts.freeze()
end

public function main() returns Result[Unit, InventoryError]
  uses Console, FileRead
do
  let items = try load("inventory.csv")
  let summary = totals(items)
  for name in summary.keys()
  do
    let count = summary.get(name).unwrap_or(0)
    print(Text.join([name, show(count)], ": "))
  end
  return Ok(Unit)
end

test "parses a good line"
do
  expect parse_line("apples,3", 1) == Ok(Item(name = "apples", quantity = 3))
end

test "rejects a negative quantity"
do
  expect parse_line("pears,-1", 2) == Error(BadLine(2, "pears,-1"))
end

test "totals merges duplicates in first-seen order"
do
  let items = [
    Item(name = "a", quantity = 1),
    Item(name = "b", quantity = 2),
    Item(name = "a", quantity = 3),
  ]
  let merged = totals(items)
  expect merged.keys() == ["a", "b"]
  expect merged.get("a") == Some(4)
end

test "any non-negative quantity round-trips" for all q: Int
do
  if q >= 0 then
    expect parse_line(Text.join(["x", show(q)], ","), 1) == Ok(Item(name = "x", quantity = q))
  end
end
```

**Walkthrough:**
- `Item`'s invariants guarantee that no `Item` with an empty name or a negative quantity can exist anywhere in the program.
- `parse_line` returns errors as values. The `if` guard on `case Some(quantity)` rejects bad values before an `Item` is built, so the invariant never traps.
- `load` uses `try` twice. The first converts `FileError` into `InventoryError` with `map_error`. The second passes `parse_line`'s error straight up.
- `totals` builds its result in a `MutableMap`, then freezes it. Insertion order makes the output order deterministic.
- `main` declares exactly the effects it needs. Note the variable is named `merged`, not `result`, because `result` is a keyword.

**Running it (planned CLI):** given `inventory.csv`:

```
apples,3
pears,2

apples,4
```

```
$ tersa test inventory.tersa
4 tests passed, 1 doc example passed

$ tersa run inventory.tersa --allow Console --allow FileRead=.
apples: 7
pears: 2
```

The last line of `tersa test` stdout is always this summary, after any output of the tests themselves. Failed counts appear only when they are nonzero, each right after the matching passed count, and a count of 1 takes the singular noun. A test that traps counts as failed. If one test failed, the line would be `3 tests passed, 1 test failed, 1 doc example passed` and the exit status 1. With `--json` the line is left out, so stdout still ends with the diagnostic array.

If line 3 were `plums,x`, `main` would return `Error(BadLine(3, "plums,x"))`. The run ends with exit status 1, and stderr shows `error: BadLine(3, "plums,x")` (`error: ` plus the canonical text form).

---

## 20. Quick-Reference Cheat Sheet

```
module app.main                              # first line; matches src/app/main.tersa
import std.console exposing print            # explicit imports only

let limit: Int = 10                          # module constant (typed, pure)

public record Point                          # record: named fields, invariants
  x: Int
  y: Int
  invariant x >= 0
end

public choice Shape                          # choice: tagged union
  case Circle(radius: Float)
  case Empty
end

public function f(a: Int, b: Int) returns Int   # signature always explicit
  uses Console                               # effects (omit if pure)
  requires b != 0                            # precondition: blames caller
  ensures result <= 100                      # postcondition: blames function
do
  let x = a div b                            # immutable, type inferred
  var n = 0                                  # reassignable
  set n = n + 1                              # every reassignment uses set
  if x > 0 and not (n == 2) then
    print("positive")
  elseif x == 0 then
    print("zero")
  else
    print("negative")
  end
  for i in List.range(0, 3)
  do
    print(show(i))
  end
  while n < 5
  do
    set n = n + 1
  end
  match Some(x)
    case Some(v) if v > 100 then
      return 100
    case Some(v) then
      return v
    case None then
      return 0
  end
end

# --- inside a function body: ---
let p = Point(x = 1, y = 2)                  # named fields
let q = p with (x = 5)                       # copy with change
let c = Circle(1.5)                          # positional cases
let sq = function (v: Int) returns Int   # pure lambda
  do
    v * v
  end
let v = try parse(input)                     # unwrap or return early
using fh = try File.open(path)               # resource closed at end
do
  ...
end

test "f works"
do
  expect f(4, 2) == 2
end
```

| Want | Write |
| :-- | :-- |
| Integer division / remainder | `a div b`, `a mod b` (floored) |
| Float division | `x / y` |
| Text join | `Text.concat(a, b)`, `Text.join(parts, sep)` |
| Maybe-missing value | `Option[T]`: `Some(v)` / `None` |
| Fallible result | `Result[T, E]`: `Ok(v)` / `Error(e)` |
| Bug / impossible state | `fail "message"` |
| Convert error type | `.map_error(function (e: A) returns B` (newline) `do` (newline) `…` (newline) `end)` |
| Default for missing | `.unwrap_or(default)` |
| Safe index | `xs.get(i)` → `Option` |


---

## 21. Glossary

| Term | Meaning |
| :-- | :-- |
| **Blame** | Who a contract failure is attributed to: the caller (`requires`), the function (`ensures`), or the constructor/updater (`invariant`) |
| **Capability** | Permission granted by the host at run time (for example `FileRead=./data`) |
| **Capability ceiling** | The maximum set of effects a package's modules may use, declared in `tersa.toml` |
| **Choice** | A tagged union type, with cases that can carry fields |
| **Conformance suite** | Test programs with expected results that every Tersalang implementation must pass |
| **Contract** | A `requires`, `ensures`, or `invariant` condition checked at run time |
| **Determinism contract** | The guarantee of byte-identical results for the same inputs, versions, grants, and seed |
| **Effect** | A kind of side effect a function may perform, declared with `uses` |
| **Exhaustive** | A `match` that handles every possible value |
| **Fuel** | An abstract count of evaluation steps. Running out traps deterministically |
| **Harness (RL harness)** | The tool that runs a task's hidden tests and computes a reward |
| **Hidden tests** | Task tests the program's author never sees. The only tests that count toward reward |
| **Host mode** | The mode that allows Python interop (`foreign`). Never used for untrusted code |
| **Memory units** | An abstract measure of allocation used for deterministic memory limits |
| **Module** | One `.tersa` file, named by its `module` line |
| **Package** | A folder with an `tersa.toml` manifest containing modules |
| **Pure** | A function with no effects: same inputs, same output |
| **Record** | A product type with named fields |
| **Resource** | A value like `File` that must be used inside a `using` block |
| **Trap** | An unrecoverable failure caused by a bug, with a `T6xxx` code |
| **Verification level** | L0 Parsed, L1 Typed, L2 Tested, L3 Verified |

---

## 22. Resolved Items

Every item below is decided (Design Doc §35.2), choosing the most explicit option with the fewest special cases. Changes need a TEP.

1. **`do` placement.** `do` always goes on its own line. There is no same-line form (§3.2). Violations are reported as the general syntax error `E1000` with the message "expected `do` on its own line".
2. **No shadowing.** Re-declaring a name already in scope is `E2020` (§6.4).
3. **Top-level order.** Order doesn't matter. Duplicate top-level names are `E2021`, and constant cycles are `E2003` (§3.1, §13.1).
4. **Ordering operators.** `< <= > >=` work only on `Int`, `Int64`, `Float`, and `Text`. Other `Comparable` types use `compare` (§4.2).
5. **Float inside records.** IEEE equality for `Float` fields, so a record containing NaN is not equal to itself. Such records aren't `Hashable` (§5.9).
6. **Iteration helpers.** Maps have `keys()` and `entries()` (a list of `Entry` records). `List.range(a, b)` excludes `b`. A loop over a `MutableList` iterates a snapshot (§5.7, §7.3).
7. **Stdlib names.** `length`, `is_empty`, `show`, `MutableList.new`, `MutableMap.new`, `push`, `Set.from_list`, `entries`, and `contains` are confirmed. The `Map.insert`/`MutableMap.insert` clash is gone: immutable changes are `with_…`/`without_…` (`Map.with_entry`, `Map.without_key`, `List.with_appended`, `Set.with_element`), and only mutable collections have `insert`, `remove`, `push`, and `set_at` (§5.7, §6.3, §15).
8. **`set r.field = v`.** Allowed only when `r` is a `var` (`E2030` otherwise). It means `set r = r with (field = v)`, and nested paths work the same way (§5.9).
9. **Standalone files.** The module name is the file name, must match the `module` line (`E2001`), and the file may import only `std.*` (§13.1).
10. **Import qualifier.** `import a.b.c` is used as `c.name`. Qualifier clashes are `E2004` (fix: `as`) (§13.2).
11. **Missing codes.** `fail` = `T6030`, failed `expect` = `T6031`, unnamed record arguments = `E3080` (with `E3081` for named arguments elsewhere and `E3082` for missing, duplicate, or unknown fields), shadowing = `E2020` (Appendix B).
12. **Diagnostic details.** The human-readable layout in this reference is the reference layout; only JSON is stable. `values` and `blame` shapes are defined in §17.2–§17.3.
13. **Property-test generators.** All built-in types except functions, resources, and mutable collections, plus records and choices built from them. Default 100 cases (§14.2).
14. **No bitwise operations in v1.** No operators and no `std.math` functions (§2.8, §15).
15. **How `main`'s `Error` is printed.** `error: ` plus `show(e)` on stderr, exit status 1 (§8.4).
16. **Integer details.** The cap is in bits, default 65,536 (§5.2, §11.4). Only `Int64` ships; `Int32` and `UInt64` are not in v1 (§5.2a). Literals are always `Int`, so a literal where `Int64` is expected is `E3023`. Mixing is `E3024`. `Int` → `Float` overflow traps `T6003` instead of giving ±infinity (§5.3). The codes `T6204`, `E3023`, `E3024`, and `T6402` are confirmed. There are no wrapping or saturating functions.

**Name:** Tersalang (formerly AIOWL). It doesn't change any rule here.

---

## Appendix A: Full Grammar (EBNF)

Notation: ISO 14977-style EBNF. `,` concatenation, `|` alternation, `[ ]` optional, `{ }` zero or more. Terminals are quoted. `NL` is a line break as defined in §2.2. `NAMED_ARG` is a lower name followed by `=` inside a call's parentheses (the lexer produces it, so the grammar needs only one token of lookahead).

### A.1 Lexical grammar

```
LOWER  = lower_letter , { lower_letter | digit | "_" } ;   (* values, functions, fields, modules *)
UPPER  = upper_letter , { letter | digit } ;              (* types, cases, interfaces, effects *)
lower_letter = "a".."z" ;  upper_letter = "A".."Z" ;  letter = lower_letter | upper_letter ;  digit = "0".."9" ;
```

```
INT      = dec_int | hex_int | bin_int ;
dec_int  = "0" | nonzero_digit , { [ "_" ] , digit } ;
hex_int  = "0x" , hex_digit , { [ "_" ] , hex_digit } ;     (* lowercase "0x" only *)
bin_int  = "0b" , bin_digit , { [ "_" ] , bin_digit } ;
FLOAT    = dec_digits , "." , dec_digits , [ exponent ] | dec_digits , exponent ;
dec_digits = digit , { [ "_" ] , digit } ;
exponent = "e" , [ "+" | "-" ] , digit , { digit } ;
TEXT     = '"' , { text_char | escape } , '"' ;
escape   = "\" , ( "n" | "t" | "r" | "\" | '"' | "{" | "}" | "u{" , hex_digit , { hex_digit } , "}" ) ;
```

### A.2 Syntactic grammar

```ebnf
(* ===== Files and modules ===== *)
file            = { NL } , module_decl , { import_decl | NL } , { top_decl | NL } , EOF ;
module_decl     = "module" , module_path , NL ;
import_decl     = "import" , module_path , [ "as" , LOWER ] ,
                  [ "exposing" , name , { "," , name } ] , NL ;
module_path     = LOWER , { "." , LOWER } ;
name            = LOWER | UPPER ;

top_decl        = [ "public" ] , ( function_decl | record_decl | choice_decl
                                 | interface_decl | const_decl | foreign_decl )
                | implements_decl
                | test_decl ;
const_decl      = "let" , LOWER , ":" , type , "=" , expression , NL ;

(* ===== Functions ===== *)
function_decl   = header , "do" , NL , block , "end" , NL ;   (* header ends with NL, so "do" starts its own line; E1000 *)
header          = "function" , LOWER , [ type_params ] , "(" , [ params ] , ")" ,
                  "returns" , type , NL ,
                  [ "uses" , UPPER , { "," , UPPER } , NL ] ,
                  { contract } ;
contract        = ( "requires" | "ensures" ) , expression , NL ;
params          = param , { "," , param } , [ "," ] ;
param           = LOWER , ":" , type ;
type_params     = "[" , type_param , { "," , type_param } , "]" ;
type_param      = UPPER , [ ":" , constraint , { "and" , constraint } ] ;
constraint      = UPPER , [ type_args ] ;

(* ===== Types ===== *)
type            = [ module_path , "." ] , UPPER , [ type_args ]
                | "function" , "(" , [ type , { "," , type } ] , ")" , "returns" , type ;
type_args       = "[" , type , { "," , type } , "]" ;

record_decl     = "record" , UPPER , [ type_params ] , NL ,
                  { LOWER , ":" , type , NL } ,
                  { "invariant" , expression , NL } ,
                  "end" , NL ;
choice_decl     = "choice" , UPPER , [ type_params ] , NL ,
                  { "case" , UPPER , [ "(" , params , ")" ] , NL } ,
                  "end" , NL ;
interface_decl  = "interface" , UPPER , [ type_params ] , NL , { header } , "end" , NL ;
implements_decl = "implements" , UPPER , type_args , NL , { function_decl } , "end" , NL ;
foreign_decl    = "foreign" , TEXT , header ;        (* host-mode interop only, §16 *)
test_decl       = "test" , TEXT , [ "for" , "all" , params ] , NL ,
                  "do" , NL , block , "end" , NL ;

(* ===== Statements ===== *)
block           = { [ statement ] , NL } ;
statement       = "let" , LOWER , [ ":" , type ] , "=" , expression
                | "var" , LOWER , [ ":" , type ] , "=" , expression
                | "set" , place , "=" , expression
                | "return" , [ expression ]
                | "fail" , expression
                | "expect" , expression
                | "break" | "continue"
                | if_stmt | match_stmt | while_stmt | for_stmt | using_stmt
                | expression ;                      (* checker: must be a call, §7.4 *)
place           = LOWER , { "." , LOWER } ;
if_stmt         = "if" , expression , "then" , block ,
                  { "elseif" , expression , "then" , block } ,
                  [ "else" , block ] , "end" ;
match_stmt      = "match" , expression , NL ,
                  { "case" , pattern , [ "if" , expression ] , "then" , block } , "end" ;
while_stmt      = "while" , expression , NL , "do" , NL , block , "end" ;
for_stmt        = "for" , LOWER , "in" , expression , NL , "do" , NL , block , "end" ;
using_stmt      = "using" , LOWER , "=" , expression , NL , "do" , NL , block , "end" ;
pattern         = "_" | LOWER | literal | "-" , ( INT | FLOAT )
                | [ module_path , "." ] , UPPER , [ "(" , pattern , { "," , pattern } , ")" ] ;

(* ===== Expressions (lowest to highest precedence; see 7.3) ===== *)
expression      = lambda | or_expr ;
lambda          = "function" , "(" , [ params ] , ")" , "returns" , type , NL ,
                  "do" , NL , expression , NL , "end" ;
                  (* single-expression body. "do" is alone on its line (E1000).
                     Line ends inside a lambda produce NL even within brackets
                     (the lambda-frame rule) *)
or_expr         = and_expr , { "or" , and_expr } ;
and_expr        = not_expr , { "and" , not_expr } ;
not_expr        = "not" , not_expr | comparison ;
comparison      = additive , [ comp_op , additive ] ;      (* non-associative *)
comp_op         = "==" | "!=" | "<" | "<=" | ">" | ">=" ;
additive        = multiplicative , { ( "+" | "-" ) , multiplicative } ;
multiplicative  = prefix , { ( "*" | "/" | "div" | "mod" ) , prefix } ;
prefix          = "-" , prefix | "try" , prefix | update ;
update          = postfix , [ "with" , "(" , field_init , { "," , field_init } , [ "," ] , ")" ] ;
postfix         = primary , { "(" , [ args ] , ")" | "." , name } ;
args            = arg , { "," , arg } , [ "," ] ;
arg             = [ NAMED_ARG ] , expression ;      (* NAMED_ARG = LOWER "=" , see 7.1 *)
field_init      = LOWER , "=" , expression ;
primary         = literal | LOWER | UPPER | "result"
                | "old" , "(" , expression , ")"
                | "(" , expression , ")"
                | "[" , [ expression , { "," , expression } , [ "," ] ] , "]"
                | "{" , [ entry , { "," , entry } , [ "," ] ] , "}" ;
entry           = expression , ":" , expression ;
literal         = INT | FLOAT | TEXT | "true" | "false" ;
```

## Appendix B: Diagnostic Codes

**Authoritative code list.** The file `spec/diagnostics.yaml` in this repository is the authoritative list of diagnostic codes and their meanings. This reference and the Design Doc mirror it; if they ever disagree, the YAML file wins and the docs are corrected. A CI test in the repo keeps the catalog, the emitted codes, and the tests in sync.

This table mirrors `spec/diagnostics.yaml` at the code baseline: one row per code, in the file's order. **Meaning** is the catalog's `message` and **Catalog note** is its `note`, both word for word. **Status** is **RESERVED** for retired codes, which must never be reused. **See** links to the rules in this reference.

| Code | Status | Meaning (catalog `message`) | Catalog note (`note`) | See |
| :-- | :-- | :-- | :-- | :-- |
| E0001 | Active | Source is not valid UTF-8 or starts with a byte-order mark |  | §2.1 |
| E0002 | Active | Non-ASCII character outside a text literal or comment |  | §2.1 |
| E0003 | Active | Tab character outside a text literal or comment |  | §2.1 |
| E0004 | Active | Lone carriage return |  | §2.2 |
| E0010 | Active | Identifier is not lower_snake_case |  | §2.5 |
| E0011 | Active | Type name is not PascalCase |  | §2.5 |
| E0012 | Active | Name is longer than 64 characters |  | §2.5 |
| E0020 | Active | Integer literal exceeds the lexical bit cap |  | §2.7 |
| E0021 | Active | Integer literal has a leading zero or a bad underscore |  | §2.7 |
| E0022 | Active | Float literal needs digits on both sides of the dot |  | §2.7 |
| E0023 | Active | Text literal contains a raw newline |  | §2.7 |
| E0024 | Active | Text escape is not a Unicode scalar |  | §2.7 |
| E0025 | Active | Hex or binary literal is malformed | No digits after 0x or 0b, or a digit outside that base. A leading zero or a bad underscore is E0021. A bad float shape is E0022. |  |
| E0026 | Active | Unterminated text literal |  |  |
| E0027 | Active | Unknown text escape |  |  |
| E0030 | Active | This symbol is not an operator |  |  |
| E1000 | Active | Syntax error | The single general syntax-error code. The message names what was expected, for example "expected `do` on its own line". A reserved keyword where a name is required is also E1000: the lexer always emits a keyword as a keyword token, and the parser reports "expected a ... name, found the keyword `x` (keywords are reserved and cannot be names)". | §3.2, Appendix C. One of its messages is "expected `do` on its own line" (resolved item 1) |
| E1101 | Active | Only one with update is allowed |  |  |
| E1102 | Active | Comparison operators are not associative |  |  |
| W1103 | Active | and and or are mixed without parentheses |  |  |
| W1104 | Active | Format-skip comment is not exactly `# fmt: skip` | A full-line comment that normalizes to #fmt:skip but is not the exact marker `# fmt: skip`. The file is not skipped and is formatted normally. tersa fmt and tersa check (with or without --parse-only) always emit it; tersa run, tersa sandbox, and tersa test emit it only alongside a check error or trap that stops the run; the harness never does. | §18.1, Appendix C |
| E2000 | Active | Unknown name | A value name that is not declared, imported, or in the prelude. An unknown type name is E3008. This single-file tool also uses E2000 for a user module it cannot load. |  |
| E2001 | Active | Module name does not match the file name |  | §13.1 |
| E2002 | Active | Import cycle |  | Appendix C |
| E2003 | Active | Constant cycle |  | §13.1 |
| E2004 | Active | Import qualifier clashes with another name |  | §13.2 |
| E2005 | Active | Unknown module member |  | §13.2, Appendix C. Also reported at run time |
| E2010 | Active | break and continue are only allowed inside a loop |  |  |
| E2011 | Active | expect is only allowed inside a test |  |  |
| E2020 | Active | Name is already defined in this scope |  | §6.4 |
| E2021 | Active | Duplicate name | Two top-level declarations with the same name, or an import that exposes a name already in scope, including a prelude name. | §13.2 |
| E2022 | Active | Ambiguous name |  |  |
| E2030 | Active | `set` target is not a `var` |  | §6.2 |
| E2101 | Active | Dependency content hash does not match tersa.lock | Not implemented. Nothing reads tersa.lock. | §13.5, Appendix C |
| W3001 | Active | A non-Unit value is ignored |  | §7.1 |
| E3000 | Active | Type mismatch | Fallback type error, used only when no more specific code applies. |  |
| E3002 | Active | A Result value is ignored |  | §7.1, §10.3 |
| E3003 | Active | Wrong number of arguments | A call, case constructor, or case pattern whose argument list has the wrong length. A case that has fields and is written with no argument list is E3006. |  |
| E3004 | Active | Unknown field or method | A field or method a non-record type does not have, or an unknown member of a type. An unknown record field is E3082. An unknown module member is E2005. | §5.9, §5.13 |
| E3005 | Active | Expression statement must be a function call |  | §7.1 |
| E3006 | Active | Case constructor is missing its arguments | A case that has fields, used as a bare name. The wrong number of arguments on a call or pattern is E3003. |  |
| E3007 | Active | Wrong number of type arguments |  | §5.11 |
| E3008 | Active | Unknown type | A type name, or a record name in a construction. An unknown value name is E2000. |  |
| E3010 | Active | Cannot infer this type |  |  |
| E3013 | Active | No property-test generator for this type |  | §14.2 |
| E3020 | Active | Operator is not defined on Text |  |  |
| E3021 | Active | Division operator is not defined on this type |  |  |
| E3022 | Active | Condition must be Bool |  | §5.4 |
| E3023 | Active | Integer literals are always Int |  | §5.2 |
| E3024 | Active | Int and Int64 cannot be mixed |  | §5.2 |
| E3025 | Active | Ordering operator is not defined for this type |  |  |
| E3026 | Active | Type cannot be compared with == |  |  |
| E3027 | Active | Builtin numeric function does not accept this type |  |  |
| E3030 | Active | Match is not exhaustive |  |  |
| W3031 | Active | Match arm is unreachable |  |  |
| E3032 | Active | Function is missing a return | A path does not return or fail, or a bare return in a function whose return type is not Unit. | §7.5 |
| E3033 | Active | Return value does not match the function return type |  |  |
| E3034 | Active | main must return Unit or Result[Unit, E] |  | §8.4 |
| E3040 | Active | Orphan interface implementation |  | §5.12 |
| E3041 | Active | This interface cannot be implemented by user code |  | §5.12 |
| E3042 | Active | Type is not Hashable |  | §5.7 |
| E3043 | Active | Duplicate interface implementation |  | Appendix C |
| E3044 | Active | Interface implementation is missing a function |  |  |
| E3045 | Active | Type is not Showable |  | §5.12, §5.14, Appendix C |
| E3046 | Active | Type does not implement the interface | A type argument that misses a constraint (T: Comparable, T: Describable, T: Equatable), or a call to an interface function for a type with no implements block. A missed Showable is E3045 and a missed Hashable is E3042. | §5.11, §5.12 |
| E3047 | Active | Function does not match the task interface | Harness only. The attempt has no top-level function a task's interface.tersa requires, or declares it with different type parameters (compared by position), constraints, parameter count or types, or return type. Parameter names, public, contracts, and effects are not compared; the task's effects grant governs effects. The episode stops at the check stage with C 0 and reward 0, and the diagnostic keeps full detail in the agent view, because the interface is public. A reference solution that does not match is I9025 when the task loads. | §14.4 |
| W3050 | Active | at can trap when the index is out of range |  | §5.7 |
| E3060 | Active | try requires Option or Result | try on a value that is neither, or try in a function that does not return Option or a Result with the same error type. | §10.2 |
| E3070 | Active | A mutable collection cannot be stored or returned here |  | §6.3 |
| E3071 | Active | A lambda cannot capture a var |  | §8.3 |
| E3072 | Active | A resource must be bound with using |  | §12 |
| E3080 | Active | Record is built with positional arguments |  | §5.9 |
| E3081 | Active | Named arguments are only allowed when constructing a record |  | §5.9 |
| E3082 | Active | Unknown or duplicate record field | Also a missing record field. Covers construction, with, field access, and set. A method a non-record type does not have is E3004. | §5.9 |
| E4001 | Active | Function is missing an effect |  | §11.1 |
| E4002 | Active | An effectful function cannot be used as a value |  | §11.1 |
| E4003 | Active | Unknown effect |  |  |
| E4010 | Active | main uses an effect that was not granted | Reported before main runs, when main's declared effects are not in the host grants. A call that reaches an ungranted effect at run time, including inside a test, is T6302. | §11.2, Appendix C |
| E4011 | Active | Function is not available in RL mode |  | §5.3 |
| E4012 | Active | foreign declarations are only allowed in host mode |  | §16.1 |
| E4013 | Active | Unknown standard-library module |  |  |
| E4020 | Active | Value is not convertible at the Python boundary |  | §16.1, Appendix C |
| E5001 | Active | `result` or `old` is used outside `ensures` |  | §9.2 |
| E5002 | Active | Contract uses an effect or a var |  | §9.2 |
| E5010 | Active | Implementation adds a requires clause |  | §5.12, §9.2 |
| T6001 | Active | Int64 overflow |  |  |
| T6002 | Active | Division by zero |  |  |
| T6003 | Active | Int is too large for Float |  |  |
| T6010 | Active | Text slice is out of range |  | §5.5 |
| T6011 | Active | Index is out of range |  | §5.7 |
| T6012 | Active | Use of a closed resource | Runtime safety net. A checked program cannot reach a closed resource (E3072, and using closes it after the body), so only a unit test that bypasses the checker produces it. | Appendix C |
| T6013 | Active | Invalid byte data |  | §5.6 |
| T6020 | Active | expect_some failed |  |  |
| T6021 | **RESERVED** (do not reuse) | Value is not Showable | Retired Oct 18, 2026 because show is now checked statically. Calling show on a type that is not Showable is E3045. Do not reuse this number. | Reserved. Never reuse this number (replaced by E3045) |
| T6030 | Active | fail |  |  |
| T6031 | Active | expect failed |  |  |
| T6101 | Active | requires failed |  |  |
| T6102 | Active | ensures failed |  |  |
| T6103 | Active | invariant failed |  |  |
| T6104 | Active | Contract trapped |  |  |
| T6201 | Active | Fuel exhausted |  |  |
| T6202 | Active | Memory limit exceeded |  |  |
| T6203 | Active | Call depth exceeded |  |  |
| T6204 | Active | Integer size limit exceeded |  | §11.4 |
| W6205 | Active | Console output was truncated | A reported result. The run is kept, and an RL episode is not discarded. This replaced I9012. | §11.4, Appendix C |
| T6206 | Active | OS memory limit exceeded | A candidate died from the address cap or a memory fault: MemoryError, SIGKILL, SIGSEGV, SIGBUS, or SIGABRT. The episode scores reward 0 with correctness 0 and efficiency 0, and the harness exits 2. Every hidden test is listed by its real name. One that was running is trapped; tests that never started are failed. The kill diagnostic is on the episode. This applies under every isolation backend, including none. | §11.4, §14.4, Appendix C |
| T6207 | Active | OS CPU limit exceeded | A candidate died from the CPU cap (SIGXCPU). The episode scores reward 0 with correctness 0 and efficiency 0, and the harness exits 2. Every hidden test is listed by its real name. One that was running is trapped; tests that never started are failed. The kill diagnostic is on the episode. A process-count cap stops new processes with an error instead of this code. | §11.4, §14.4, Appendix C |
| T6208 | Active | Wall-clock limit exceeded | A candidate's own execution hit the in-process wall clock or the child-process timeout. The message names which clock. The episode scores reward 0 with correctness 0 and efficiency 0, and the harness exits 2, because a slow program must not be discarded. The host cannot be told apart from that program. Every hidden test is listed by its real name. One that was running is trapped; tests that never started are failed. A wall-clock stop while measuring the reference is I9013 on that reference episode. tersa harness validate then fails its gate and exits 1. tersa harness run falls back to the declared or limit basis with E_basis_reason reference_did_not_execute. | §11.4, §14.4, Appendix C |
| T6301 | Active | Capability scope violated |  |  |
| T6302 | Active | Effect was not granted | A runtime trap. main's missing grants are E4010, before any code runs. | §11.2, §11.4, Appendix C |
| T6401 | Active | Foreign call failed |  | §16.1 |
| T6402 | Active | Foreign value cannot be converted |  | §16.1, Appendix C |
| I9010 | Active | Invalid limit or grant configuration | Fuel, memory units, the integer cap, call depth, output bytes, wall_ms, and property-test case count, when the field is missing, not positive, or out of range. Also a host grant that names an unknown effect, a scoped effect (FileRead, FileWrite, Net) without its scope, or an unscoped effect with one, and a task.toml effects entry that gives a scope to an unscoped effect (Console=out). A limit field that is present but not an integer is I9022. Other task-load failures use I9014 through I9022. | §11.2, §11.4, §14.4, Appendix C |
| I9011 | Active | Unicode version does not match the language pin | Not implemented. No Unicode version is pinned (the host unicodedata version is used), so nothing emits this code. | Appendix C |
| I9012 | **RESERVED** (do not reuse) | Console output was truncated | Retired. Output truncation is W6205, a reported result, not an infrastructure error. Do not reuse this number. | Reserved. Never reuse this number |
| I9013 | Active | Wall-clock timeout stopped the run | Infrastructure only. The message names the backstop: in-process wall-clock backstop reached (N ms), or child process wall-clock backstop reached (N s). tersa sandbox and tersa run use this code and exit 4. A reference stopped during validation or measurement keeps this code on that reference episode. tersa harness validate fails its gate and exits 1. tersa harness run falls back to the declared or limit basis with E_basis_reason reference_did_not_execute. A candidate's own clock is T6208. An OS memory kill is T6206. | §11.4, Appendix C |
| I9014 | Active | task.toml is missing |  | §14.4, Appendix C |
| I9015 | Active | Task language does not match this interpreter |  | §14.4, Appendix C |
| I9016 | Active | Unknown effect |  | §14.4, Appendix C |
| I9017 | Active | Effect cannot be granted in RL mode | FileRead, FileWrite, Net, and Python. A task.toml that lists one fails to load, with or without a scope (FileRead=data is refused at load time too, so a task grant never carries a scope). tersa sandbox, tersa run --mode rl, tersa test --mode rl, and run_sandboxed refuse the same grants before anything runs. All exit 4. | §11.2, §14.4, Appendix C |
| I9018 | Active | Reward weight is outside 0..1 | check_credit and efficiency_weight are numbers outside 0..1. A reward field that is not a number is I9022. | §14.4, Appendix C |
| I9019 | Active | Unknown property seed policy |  | §14.4, Appendix C |
| I9020 | Active | hidden/ is missing or has no tests |  | §14.4, Appendix C |
| I9021 | Active | A task source file did not parse |  | §14.4, Appendix C |
| I9022 | Active | task.toml field has the wrong type | Includes a limit field that is not an integer and a reward weight that is not a number. | §14.4, Appendix C |
| I9023 | **RESERVED** (do not reuse) | OS CPU limit killed the process | Retired Oct 18, 2026. A candidate OS CPU kill is T6207, a scored trap (reward 0), not an infrastructure discard. Do not reuse this number. | Reserved. Never reuse this number |
| I9024 | Active | Isolation backend is not available | The message names the backend. nsjail has no launcher. gVisor is not launched because it needs host cgroup access this build does not grant. | §14.4, Appendix C |
| I9025 | Active | Reference solution does not match the task interface | The task fails to load (exit 4) when reference/solution.tersa parses but lacks a function interface.tersa requires or declares it differently. The message names the function and the difference, as in E3047. | §14.4, Appendix C |

---

## Appendix C: Trigger Rules for Selected Codes

Each code below has a precise trigger rule and, where useful, an example. `T6012` and `I9011` have the meanings the interpreter's `spec/diagnostics.yaml` gives them; bad byte data is `T6013` and the OS backstop is `I9013`.

**E1000: syntax error, message "expected `do` on its own line".** `E1000` is the general syntax-error code; this is one of its messages. Raised by the parser when the `do` of a function, test, `while`, `for`, `using`, or lambda shares its line with any token before it, or with anything but a comment after it (§3.2).

```
while n > 0 do        # ERROR E1000: expected `do` on its own line
  set n = n - 1
end
```

**E2002: import cycle.** Raised by the resolver when the import graph of the modules being checked (the package plus its dependencies) contains a cycle. It is reported at the import that closes the cycle, and the message lists the whole cycle.

```
# src/app/a.tersa
module app.a
import app.b          # ERROR E2002: import cycle app.a -> app.b -> app.a

# src/app/b.tersa
module app.b
import app.a
```

**E2005: unknown module member.** Raised when a name after `exposing`, or after a module qualifier, isn't defined in that module or isn't `public` (§13.2). It is also used if such a member is reached at run time.

```
import geometry.shapes
let h = shapes.Hexagon(2)    # ERROR E2005: geometry.shapes has no public member Hexagon
```

**E2101: dependency content hash does not match `tersa.lock`** (not implemented yet). Raised before checking starts when a dependency's computed content hash differs from the `hash` recorded for it in `tersa.lock` (§13.5). The build stops; nothing from that dependency is loaded.

```
# tersa.lock says:   hash = "sha256:<hash A>"
# fetched textutils hashes to sha256:<hash B>
error[E2101]: lockfile hash mismatch for package textutils
```

**E3043: duplicate implementation.** Raised when a second `implements` block exists for an (interface, type) pair that already has one, anywhere in the program (§5.12: at most one implementation per pair).

```
implements Describable[Rect]
  ...
end
implements Describable[Rect]   # ERROR E3043: Describable[Rect] is already implemented (first at shapes.tersa:12)
  ...
end
```

**E4020: value not convertible at the Python boundary.** Raised at check time when a `foreign` declaration has a parameter or return type with no Python mapping (§16.1): a type the §16.1 table marks as not convertible (functions, resources), a type the table doesn't list (for example `Set`, mutable collections, or a `Map` whose keys aren't `Text`), or any type that contains one of these.

```
foreign "python:mylib.apply" function apply(f: function(Int) returns Int, x: Int) returns Int
  uses Python
# ERROR E4020: parameter f has a function type, which can't cross the Python boundary
```

**T6012: use of a closed resource.** A runtime trap raised when an operation (such as `f.read_line()`) runs on a resource that has already been closed. The `using` rules (resources can't be stored, returned, or captured; `E3072`) make this unreachable in checked Tersalang code, so the trap is a safety net: seeing it points to a host or `foreign` handoff, or an interpreter bug, and it should be reported.

```
# Not writable in checked code. Example: a host passes in a File it has already closed,
# and the program calls f.read_line()  -> trap T6012: use of a closed resource
```

**T6013: invalid byte data.** A runtime trap raised by the non-Option constructors: `Bytes.of_list` when an element is outside 0–255, and `Bytes.of_hex` when its text isn't an even number of hex digits (`0-9`, `a-f`, `A-F`). `Bytes.from_list` and `Bytes.from_hex` never trap; they return `None` (§5.6).

```
let b = Bytes.of_list([10, 300])     # trap T6013: byte value 300 is outside 0..255
let c = Bytes.of_hex("abc")          # trap T6013: odd number of hex digits
let d = Bytes.from_hex("abc")        # None (no trap)
```

**T6401: Python exception.** A runtime trap raised when a `foreign` function raises a Python exception and its declared return type is not `Result[T, PythonError]`. With a `Result[T, PythonError]` return type, the exception becomes `Error(PythonError(type_name = …, message = …))` instead. `PythonError` is a prelude record (§15).

```
foreign "python:math.factorial" function factorial(n: Int) returns Int
  uses Python
# Without the requires line, factorial(-1) makes Python raise ValueError -> trap T6401
```

**T6402: foreign value cannot be converted.** A runtime trap raised when a value crossing the Python boundary (a `foreign` result, or an argument passed in through the host API, §16.2) can't be converted to its declared Tersalang type, for example a Python `str` returned where `Int` is declared. One specified case: a Python `int` crossing into a value typed `Int64` that is outside −2^63 to 2^63−1.

```
foreign "python:mylib.big" function big() returns Int64
  uses Python
# mylib.big() returns 2**63 -> trap T6402: 9223372036854775808 is outside the Int64 range
```

**E3045: type is not Showable.** Raised at check time when `show` is called on a type that isn't `Showable`: a function type, a resource type, a mutable collection, or a record, choice, list, map, set, option, or result that contains one (§5.12). It replaced the runtime trap `T6021`, which is reserved.

```
record Handler
  name: Text
  run: function(Int) returns Int
end
function describe(h: Handler) returns Text
do
  return show(h)   # ERROR E3045: Handler is not Showable (field run is a function)
end
```

**W6205: console output was truncated.** A warning, not an error or an infrastructure fault. When a run writes more console output than its output cap (§11.4), the extra output is dropped, the run **continues**, and the result reports `W6205`. In RL mode the episode is kept and scored normally; it is **not** discarded. `W6205` replaced `I9012`, which is reserved and never reused.

```
# Output cap reached partway through a loop of print calls:
warning[W6205]: console output was truncated
```

**I9011: Unicode version does not match the language pin.** An infrastructure error raised before the run starts when the Unicode tables the runtime would use (for case mapping, normalization, and grapheme segmentation) are a different Unicode version from the one pinned for the package's language version. The run is refused, and in RL mode the episode is discarded, not scored.

```json
{"reward": null,
 "infrastructure_error": {"code": "I9011", "message": "Unicode version does not match the language pin"}}
```

**W1104: format-skip comment is not exactly `# fmt: skip`.** A warning raised by `tersa fmt` (including `--check` and stdin) and `tersa check` (including `--parse-only`) for each line that, without surrounding whitespace, matches `#`, `fmt`, `:`, `skip` in any case with optional whitespace between them but isn't the exact marker. The file is **not** skipped: it is formatted normally. A warning alone doesn't change the exit code (0 when nothing else is wrong). Fix it by writing the marker exactly, or by deleting the line.

```
# The next line warns W1104 (a comment after it on the same line would stop it matching)
#fmt:skip
module w1104_fmt_skip
```

**E4010 and T6302: an effect that wasn't granted.** `E4010` is raised **before `main` runs**, when `main` declares an effect the host didn't grant; no code runs. `T6302` is a **runtime trap** raised when a call actually reaches an effect that wasn't granted, for example an attempt that calls `File.read_text` in RL mode, where `FileRead` can never be granted (§11.2). In the RL harness that fails the test; it is a scored result, not an infrastructure error.

**I9010 and I9014–I9022: the task or its limits can't be used.** Infrastructure errors raised before any attempt runs, by `tersa harness` (task loading) or by the CLI and sandbox (limits). `I9010` is an invalid limit value (missing, not positive, or out of range): fuel, memory units, the integer cap, call depth, output bytes, `wall_ms`, or the property-test case count. In `task.toml` it is also an `effects` entry that gives a scope to an effect that takes none (`Console=out`), and `I9017` is also an entry that lists `FileRead`, `FileWrite`, `Net`, or `Python` with a scope (`FileRead=data`), so a task grant never carries a scope. On the command line it is also a bad host grant: an unknown or mis-cased effect, a scoped effect without its scope, or an unscoped effect with one (§11.2). `I9017` is also raised when `tersa sandbox`, `run --mode rl`, or `test --mode rl` gets an `--allow` for `FileRead`, `FileWrite`, `Net`, or `Python`. A limit that is present but not an integer, a reward weight that isn't a number, or a `[reward] reference_fuel` that isn't an integer ≥ 0, is `I9022`. Every other task-load failure has its own code (table in §14.4). `I9025` is a `reference/solution.tersa` that parses but lacks a function `interface.tersa` requires or declares it differently; the message names the function and the difference, as `E3047` does for an attempt. `tersa harness` prints `error[CODE]: <reason>` and exits 4.

```
error[I9017]: RL mode cannot grant FileRead
```

**I9013: OS backstop limit hit.** An infrastructure error raised by the runner when `tersa sandbox` or `tersa run` is stopped by the wall clock, and on the reference episode when the reference is stopped during validation or measurement (§11.4). That reference episode has reward null. `tersa harness validate` fails its gate and exits 1. `tersa harness run` falls back to the declared or limit basis with `E_basis_reason` `"reference_did_not_execute"`. A candidate's own clock is `T6208`, a scored trap. An OS memory kill of the candidate is `T6206`. Fuel, memory units, and the other language limits are hit first in normal operation.

```json
{"stage_reached": "run", "reward": null,
 "infrastructure_error": {"code": "I9013", "message": "in-process wall-clock backstop reached (5000 ms)"}}
```

As built, `I9013` names the backstop: `in-process wall-clock backstop reached (N ms)` or `child process wall-clock backstop reached (N s)`. A candidate's own clock is `T6208` with that same message, reward 0, and exit 2. An OS memory kill is `T6206` (`OS memory limit exceeded`). An OS CPU kill is `T6207` (`OS CPU limit exceeded`). `I9023` is reserved. A requested sandbox that this host cannot launch is `I9024` (the message names the backend, reward null, exit 4). When the reference is stopped, `tersa harness validate` adds a report `message` such as `reference stopped during validation: I9013: <backstop message>`.
