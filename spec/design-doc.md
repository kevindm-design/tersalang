# Tersalang Design Doc

**Tersalang** ("terse language") is a programming language built for large language models (LLMs) to write and for reinforcement-learning (RL) agents to learn from. CLI: `tersa`. File extension: `.tersa`. Python package: `tersalang`. The language was first called AIOWL.

| Item | Detail |
| :-- | :-- |
| **Version** | v0.6.0, Oct 19, 2026 |
| **Status** | Specification for language 0.1-draft, implemented by `tersalang` 0.1.0 |
| **Code baseline** | Describes the interpreter in this repository at `tersalang` 0.1.0 |
| **Implementation language** | Python (§17.1) |
| **Repository** | https://github.com/kevindm-design/tersalang (default branch `main`). GitHub is primary; a GitLab mirror comes later |
| **Licenses** | Apache-2.0 for code, CC BY 4.0 for the specification and docs (§32) |
| **Started** | Oct 17, 2026 |
| **Companion doc** | [Tersalang Language Reference (Draft v0.6.0)](language-reference.md), the language written out for programmers |

## Purpose

This document explains why Tersalang exists and how it is designed: its principles, its type system and semantics, its tooling, and the RL harness that scores programs. It is written for the language's designers, implementers, and reviewers, and for anyone who needs to understand the reasoning behind each rule. It is the source of truth: the Language Reference restates its rules for programmers.

## Executive Summary

Tersalang ("terse language") is a programming language designed first for AI. Large language models (LLMs) write it, and reinforcement-learning (RL) agents learn from it, while people can still read and review the result. Today's languages were built for humans, so models inherit their ambiguity, their many ways to do the same thing, and errors that only show up at run time. Tersalang is small, strict, and word-based: every program is checked before it runs, runs the same way every time, and reports problems as stable error codes. That gives an AI fast, honest feedback and gives an RL agent a clean, reproducible reward.

This document covers the why and the architecture: the goals, the syntax and types, error handling, effects and limits, modules, tooling, the sandbox, the RL harness and its defenses against reward hacking, constrained decoding, benchmarks, and governance.

**Current status.** A Python reference interpreter is built, and CI passes on Linux, macOS, and Windows. The RL harness scores each attempt on correctness with a small efficiency bonus, and all 21 reward-hacking defenses have passing tests. The generated grammar for constrained decoding (GBNF) is validated with llama.cpp.

**Key decisions.** Integers are exact by default (with a size cap), and `Int64` is the only fixed-width type. The reference implementation is in Python. RL training environments come first, general code generation second. Code is licensed Apache-2.0 and docs CC BY 4.0. The name Tersalang is decided. No design question is open.

**What's next.** Finish sandbox hardening, then the tokenizer study and baseline benchmarks, training data, and a faster backend (§36). Changes to the language go through a formal proposal process (§31).

## How to read this document

- Every section is the **normative specification for language 0.1-draft**. Changes go through a Tersalang Enhancement Proposal (TEP, §31).
- Normative words follow RFC 2119: **MUST**, **MUST NOT**, **SHOULD**, **MAY**.
- **As built** marks text that describes what the code at the baseline does.
- **DEFERRED** marks work that is intentionally postponed.

# Part I: Foundations

## 1. Vision

Today's languages were designed for humans. Models learned them second-hand from human code. So models inherit human ambiguity, many ways to do the same thing, and errors that only show up at runtime.

Tersalang flips that. It is designed first for machines to generate, check, and learn from, and it stays readable for the humans who review the output. "Word-based" is part of that promise. Tersalang uses plain English keywords where they make code easier to read, review, and tokenize, and keeps symbols where symbols are universal.

**One-sentence pitch:** A small, strict, verifiable, word-based language where every program can be checked automatically, so an AI writing it gets fast, honest feedback and an RL agent gets a clean, reproducible reward signal.

---

## 2. Goals and Non-Goals

**Priority:** RL training environments come first, and general LLM code generation second. When the two compete for effort, the RL harness, reward design, and sandbox (§20–§23) win over breadth of stdlib and interop (§15–§16).

### Goals (each with how it is measured)

| Goal | Measured by (§26) |
| :-- | :-- |
| Easy for LLMs to generate correctly on the first try | First-attempt check rate (L1) and pass@1 on the Tersalang benchmark suite, compared with Python on the same tasks |
| Every program can be checked automatically, with machine-readable feedback | 100% of programs get a result at levels L0–L2 (§21.1). Every diagnostic has a stable code and a JSON form (§18.1) |
| Safe to run thousands of attempts in parallel | Red-team results (§20, §23). Zero sandbox escapes. Resource limits always enforced |
| Deterministic, reproducible rewards | Reward variance across reruns of the same attempt is exactly zero (§12.4) |
| Readable by humans for review | Human review time per solution, compared with Python (§26) |
| Useful on day one | Tiered interop (§16) works in host mode without weakening the RL sandbox |

"Checked" means *checked*, not *proven*. Proof is an optional later level (L3, §21.1).

### Non-Goals (for now)

- Replacing Python, Rust, or JavaScript for general human programming.
- Maximum raw performance. *Exception:* check-and-run latency matters, because it limits RL throughput (§19).
- A large standard library at launch (v1 scope is in §15).
- Shared-memory concurrency (§13).
- Metaprogramming: macros, reflection, and runtime code loading.
- Implicit conversions, operator overloading, function overloading, and inheritance.

---

## 3. Design Principles

1. **One obvious way.** Minimize syntax and synonyms so the model has fewer ways to be wrong.
2. **Explicit over implicit.** No hidden coercions, no implicit globals, no mutable default arguments. Signatures are always fully written out. Inference applies to local variables only.
3. **Fail fast and loud.** Mistakes surface as early as possible (lex, parse, check, then runtime contract or trap) as structured, actionable diagnostics.
4. **Everything is checkable.** Types, effects, pre/post-conditions, invariants, and tests are part of the language.
5. **Deterministic by default.** Same input, same output, same reward. Randomness, time, and I/O are declared effects (§12).
6. **Small surface, deep checks.** A tiny core language with a powerful checker.
7. **Word-based where it helps, symbols where they are universal.** Token cost is measured (§25), not assumed. Readability wins ties.
8. **Grammar first.** The grammar is context-free, unambiguous, and not sensitive to indentation, and it ships in formats that constrained decoders accept (§24).
9. **No undefined behavior.** Every operation either has a defined result or traps with a diagnostic.

---

## 4. Two Audiences

### 4.1 LLMs (code generation)

- A regular grammar that is easy to constrain (§7, §24).
- Strong static types with local inference (§8).
- Structured JSON diagnostics with fix hints (§18.1).
- Runnable examples attached to every public function (§29).
- A compact LLM-facing reference small enough for a prompt (§29.3).

### 4.2 RL agents (learning from feedback)

- **Clear rewards** from staged gates and hidden tests (§22).
- **Partial credit:** the fraction of isolated hidden tests passed.
- **Safe exploration:** fuel, memory-unit, depth, and output limits, plus capability grants (§12, §20).
- **Reproducibility:** the determinism contract (§12.4).
- **Resistance to reward hacking:** the catalog in §23, with a conformance test for every entry.

---

## 5. Word-Based Syntax Philosophy

### 5.1 Why words

- **Tokenization.** Common English words are usually encoded compactly by the BPE-style tokenizers LLMs use. Dense symbol runs may split unpredictably. *This is a hypothesis, tested by the method in §25.*
- **Readability.** `if ready and not done then` reads aloud correctly.
- **Robust structure.** Keyword-delimited blocks (`do ... end`) survive whitespace mangling. Indentation-based blocks do not, and single-character braces are easy to miscount.
- **Searchability.** Mutation (`set`), effects (`uses`), propagation (`try`), and interop (`foreign`) are greppable words. This helps audits and reward-hacking detection.

### 5.2 Where symbols stay

Tersalang is not COBOL. COBOL's `ADD A TO B GIVING C` style made programs long, and its English-like grammar did not make them easier to write correctly.

| Use | Tersalang choice | Why |
| :-- | :-- | :-- |
| Arithmetic | `+ - * /` | Universal |
| Comparison | `== != < <= > >=` | Universal across mainstream languages |
| Integer division and remainder | `div`, `mod` | Semantics differ across languages (C and Java truncate toward zero; Python floors), so a distinct word signals a documented rule |
| Boolean logic | `and`, `or`, `not` | Python precedent; avoids `&&` vs. `&` confusion |
| Blocks | `do ... end`, `then ... end` | Robust to whitespace; easy to constrain |
| Signatures | `function f(a: Int) returns Int` | `returns` replaces `->` |
| Type annotation | `name: Type` | Widely understood (Python, TypeScript, Kotlin, Rust) |
| Generics | `List[Int]`, `[T: Comparable]` | Square brackets avoid the `<`/`>` parsing ambiguity |
| Mutation | `var` to declare, `set` to assign | Every mutation is explicit and searchable |
| Error propagation | `try expr` | A word instead of Rust's `?` |
| Record update | `p with (x = 3)` | Reads as English |
| Comments | `#`, `##` for docs | Familiar from Python and shell |

### 5.3 Guardrails against verbosity

- One keyword per concept, with no synonyms.
- Prefer short, common words (`do`, `end`, `set`, `uses`).
- Plain `end` closes every block (labeled closers are not in v1).
- The keyword list in §6.6, `returns` (not `->`), and plain `end` are **decided for language 0.1-draft**. The tokenizer and accuracy study (§25) still runs in roadmap phase 4. If it shows a clear win, a change goes through a TEP and the pre-1.0 deprecation policy (§30.1).

---
# Part II: Language Specification (language 0.1-draft)

## 6. Lexical Structure

### 6.1 Source text

- Source files MUST be valid UTF-8 with no byte-order mark. **Any** invalid UTF-8 byte sequence anywhere in the file (a byte that can't start a sequence, a truncated or overlong sequence, an encoded surrogate, or a value above U+10FFFF) is error `E0001`. A leading byte-order mark is also `E0001`.
- File extension: `.tersa`.
- Source is a sequence of Unicode code points. Non-ASCII code points MAY appear only inside text literals and comments (`E0002` otherwise).
- Tab characters are not allowed outside text literals and comments (`E0003`). The formatter uses spaces.

### 6.2 Line terminators and the NL token

- Line terminators are LF or CRLF. A lone CR is `E0004`. The formatter writes LF.
- The lexer emits an `NL` token at the end of a line, **except** when either of these holds:
  1. it is inside an open `(`, `[`, or `{` (bracket depth > 0), or
  2. the last token on the line is one of: a binary operator (`+ - * / == != < <= > >= and or div mod`), `not`, `,`, `=`, `.`, `:`, `with`, `uses`, `requires`, `ensures`.
- Consecutive line ends collapse into one `NL`. Lines that are only whitespace or comments produce no tokens.
- **Indentation is never significant.**
- **Lambda-frame exception to rule 1:** from the `)` that closes a lambda's parameter list (`function (…)`) until that lambda's matching `end`, the lexer treats bracket depth as zero again, so line ends there do produce `NL` (rule 2 still applies). When the lambda's `end` is reached, the outer bracket depth is restored. This is what lets a lambda passed as an argument put `do` on its own line. A lambda body is still a single expression, so a statement block never appears inside brackets. The lexer keeps a stack of saved bracket depths, one per open lambda, so the rule stays simple and needs no parser feedback beyond spotting `function (` in expression position.

### 6.3 Whitespace

Spaces separate tokens. They are required between adjacent words (keywords and identifiers) and are otherwise optional. The formatter normalizes spacing (§18.2).

### 6.4 Comments

- `#` starts a comment that runs to the end of the line.
- `##` starts a **doc comment**. Consecutive `##` lines attach to the next declaration (§29.1).
- There are no block comments, which keeps one way to comment.

### 6.5 Identifiers

```
LOWER  = lower_letter , { lower_letter | digit | "_" } ;   (* values, functions, fields, modules *)
UPPER  = upper_letter , { letter | digit } ;              (* types, cases, interfaces, effects *)
lower_letter = "a".."z" ;  upper_letter = "A".."Z" ;  letter = lower_letter | upper_letter ;  digit = "0".."9" ;
```

- `LOWER` names use snake_case and MUST NOT contain `__` or end with `_` (`E0010`).
- `UPPER` names use PascalCase with no underscores (`E0011`).
- The lexer classifies identifiers by their first letter. So the parser never needs to guess whether `Foo` is a constructor or a variable.
- `_` on its own is the wildcard pattern, not an identifier.
- Maximum identifier length: 64 characters (`E0012`). This keeps diagnostics and tokenization bounded.

### 6.6 Keywords (reserved)

| Group | Keywords |
| :-- | :-- |
| Modules | `module import as exposing public foreign` |
| Declarations | `function returns uses requires ensures invariant record choice case interface implements let var test` |
| Blocks and control | `do end if then elseif else match while for in break continue return using` |
| Statements | `set fail expect try` |
| Operators (word) | `and or not div mod with` |
| Values | `true false result old all` |
| Reserved for future use | `parallel spawn send receive type alias async await` |

There are no contextual (soft) keywords. Every keyword is reserved everywhere, so the lexer never needs parser context.

Because every keyword is reserved, a keyword can't be a module name or a module path segment either. In particular `module interface` is a syntax error, so a task's interface file uses a name such as `module task_spec` (§22.1).

### 6.7 Literals

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

- **Digits are ASCII only.** `digit` is `0`–`9`, `nonzero_digit` is `1`–`9`, `hex_digit` is `0`–`9` and `a`–`f` or `A`–`F`, and `bin_digit` is `0` or `1`. A Unicode digit such as `²`, `٣`, or a full-width `１` is never part of a numeric literal. Outside a text literal or comment it is `E0002` (non-ASCII character), and the lexer recovers at the next line (§6.9).
- Integer literals have no sign. `-5` is unary minus applied to `5`. **An integer literal always has type `Int`.** There is no context-dependent literal typing. Using one where an `Int64` is expected is `E3023` (§9.1a).
- An integer literal whose value needs more than 65,536 bits (the default integer-size cap, §9.1) is `E0020`. A literal within that limit but above a lower run cap traps (`T6204`) when evaluated.
- No octal literals, and no leading zeros (`E0021`). Underscores only go between digits.
- Floats need digits on both sides of the dot (`.5` and `5.` are `E0022`). There are no `inf` or `nan` literals; use `Float.infinity` and `Float.nan`.
- Text literals are single-line. A raw newline inside one is `E0023`. Multi-line text uses `\n` escapes or `Text.join_lines([...])`. There is no multi-line literal form in v1.
- `\u{...}` must name a Unicode scalar value (not a surrogate), with at most 6 hex digits (`E0024`).
- `\{` and `\}` are reserved escapes. Text interpolation is **not in v1**. Reserving the escapes lets a later TEP add it without breaking code.

### 6.8 Operators and punctuation

`+ - * / == != < <= > >= = : , . ( ) [ ] { } _`

Tokenization uses longest match (so `<=` is one token). `!` on its own, `&`, `|`, `^`, `%`, `?`, `->`, `=>`, and `;` are not tokens (`E0030`). Each of these errors comes with a fix hint naming the Tersalang equivalent, for example "`%`: use `mod`". For `&`, `|`, and `^` the hint says that **v1 has no bitwise operations** (no operators and no stdlib functions).

### 6.9 Lexical error codes

The `E00xx` range is reserved for lexical errors (§18.1). Every lexical error recovers to the next line, so one mistake doesn't hide the rest.

---

## 7. Grammar

### 7.1 Notation

ISO 14977-style EBNF: `,` concatenation, `|` alternation, `[ ]` optional, `{ }` zero or more, `(* *)` comments. Terminals are quoted. `NL`, `LOWER`, `UPPER`, `INT`, `FLOAT`, `TEXT`, and `EOF` come from §6.

Target: LALR(1) with no conflicts, checked in CI by Lark. The single known spot needing two tokens of lookahead is `arg` (named vs. positional argument). It is resolved in the lexer, which emits `LOWER` followed by `=` inside a call as a `NAMED_ARG` token.

### 7.2 Core grammar

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

### 7.3 Operator precedence and associativity

| Level (high → low) | Operators | Associativity | Notes |
| :-- | :-- | :-- | :-- |
| 1 | call `f(x)`, field/method `a.b` | left | `x.f(y)` is method-call sugar (§8.7) |
| 2 | `with ( ... )` | none | Record update. `a with (x = 1) with (y = 2)` is `E1101`; use one `with` |
| 3 | prefix `-`, `try` | right | `try a.b(c)` applies to the whole postfix expression |
| 4 | `* / div mod` | left | `/` only on `Float`; `div`/`mod` only on `Int` and `Int64` |
| 5 | `+ -` | left | `+` on `Text` is `E3020`; use `Text.concat` or `Text.join` |
| 6 | `== != < <= > >=` | **none** | `a < b < c` is a parse error (`E1102`) with a hint to use `and` |
| 7 | `not` | right (prefix) | `not a == b` means `not (a == b)` |
| 8 | `and` | left | Short-circuit |
| 9 | `or` | left | Short-circuit |

Mixing `and` and `or` without parentheses is a warning (`W1103`), and the formatter adds the parentheses.

### 7.4 Rules enforced by the checker, not the grammar

- An expression statement must be a function call. A non-`Unit` result that is ignored is `W3001` (`E3002` if it is a `Result`). In other words, **ignoring a `Result` is an error (`E3002`) and ignoring an `Option` is a warning (`W3001`)**. Discard explicitly with `let _ = ...`.
- `result` and `old(...)` are only valid inside `ensures` (`E5001`).
- `break` and `continue` are only valid inside `while` or `for` (`E2010`).
- `expect` is only valid inside `test` blocks (`E2011`). Production code uses contracts or `fail`.
- `return` without a value is only valid in functions returning `Unit`.
- Named arguments (`NAMED_ARG`) are required for record construction (`Rect(width = 2, height = 3)`) and not allowed anywhere else. Function calls and choice-case construction are positional (`Ok(n)`, `Missing(path)`). That gives one obvious way for each.
- `foreign` declarations are only allowed in packages whose manifest enables `host` mode (§14, §16).
- **Record construction:** positional arguments in a record construction are `E3080`. Named arguments anywhere else are `E3081`. A missing, duplicated, or unknown field is `E3082`, in a construction, a `with` update, a field access, or a `set`. An unknown field or method on a non-record type is `E3004`.
- **No shadowing:** declaring a name that is already in scope is `E2020`. This covers locals (`let`, `var`), parameters, loop variables, pattern bindings, and lambda parameters, and the names they may not reuse include parameters, outer locals, top-level names of the module, and imported names. Each name means one thing in a function.
- **Top-level order doesn't matter.** Every top-level name is visible throughout its module. Two top-level declarations with the same name are `E2021`.
- **`set`:** `set x = e` requires `x` to be a `var` (`E2030`, "`set` target is not a `var`", otherwise). `set r.a.b = e` is allowed only when the root `r` is a `var`, and means `set r = r with (a = r.a with (b = e))`. Invariants are checked for every record rebuilt this way.
- **`do` placement:** the grammar puts `do` on its own line after the header (and after `uses`, `requires`, and `ensures`) for functions, tests, `while`, `for`, `using`, and lambdas. There is no same-line form (resolved item 1, §35.2). A `do` that shares its line with other tokens (a trailing comment is fine) is reported as the general syntax error **`E1000`**, with the message **"expected `do` on its own line"**.

### 7.5 Example programs (illustrative)

**Contracts and tests:**

```
module examples.math

## Adds two integers.
## Example: add(2, 3) == 5
public function add(a: Int, b: Int) returns Int
  ensures result == a + b
do
  return a + b
end

public function safe_divide(a: Int, b: Int) returns Int
  requires b != 0
do
  return a div b
end

test "add works"
do
  expect add(2, 3) == 5
end

test "add is commutative" for all a: Int, b: Int
do
  expect add(a, b) == add(b, a)
end
```

(`Int` is unbounded, so `add` never overflows. The only way it can fail is if a result exceeds the run's integer-size cap (`T6204`, §9.1), which the property test's generators stay well within.)

**Records, invariants, update, and interfaces:**

```
module examples.shapes

public record Rect
  width: Int
  height: Int
  invariant width >= 0 and height >= 0
end

public function area(r: Rect) returns Int
  ensures result >= 0
do
  return r.width * r.height
end

public function widen(r: Rect, by: Int) returns Rect
  requires by >= 0
do
  return r with (width = r.width + by)
end

implements Comparable[Rect]
  function compare(a: Rect, b: Rect) returns Ordering
  do
    return Int.compare(area(a), area(b))
  end
end
```

**Choices, matching, errors as values, effects, and resources:**

```
module examples.config

# File and FileError are prelude names (§14.1), so no import is needed.
# Re-importing them with exposing would be E2021.

choice ConfigError
  case Missing(path: Text)
  case BadLine(line: Int)
end

public function load_port(path: Text) returns Result[Int, ConfigError]
  uses FileRead
do
  using f = try File.open(path).map_error(function (e: FileError) returns ConfigError
    do
      Missing(path)
    end)
  do
    let first = f.read_line()
    match first
      case Some(line) then
        match Int.parse(line)
          case Some(n) if n > 0 then
            return Ok(n)
          case _ then
            return Error(BadLine(1))
        end
      case None then
        return Error(BadLine(1))
    end
  end
end
```

---
## 8. Type System

### 8.1 Overview

Tersalang is statically and strongly typed, with nominal types and **no subtyping**. With no subtyping there is no variance to specify, which removes a whole class of rules that Java and C++ need. Shared behavior comes from interfaces (§8.6). There are no implicit conversions of any kind.

### 8.2 Inference boundary

- **Always annotated:** function parameters, return types, effects (`uses`), record fields, choice-case fields, top-level `let` constants, and lambda parameters and returns.
- **Inferred:** local `let` and `var` bindings, and type arguments at call sites (`List.empty()` takes its type from context; `E3010` if there is no context).
- **Algorithm:** local bidirectional type checking. Types flow down from annotations and up from expressions. There is no global (Hindley–Milner-style) inference across functions. So every error can be reported inside one function, against a signature the model wrote.

### 8.3 Built-in types

| Type | Summary (details in §9) |
| :-- | :-- |
| `Int` | **Arbitrary-precision integer**, subject to the run's integer-size cap |
| `Int64` | The only fixed-width integer in v1. Overflow traps, never wraps (§9.1a) |
| `Float` | IEEE 754 binary64 |
| `Bool` | `true` / `false`, no truthiness |
| `Text` | Immutable, valid UTF-8 |
| `Bytes` | Immutable byte sequence |
| `Unit` | A single value, written `Unit` |
| `List[T]`, `Map[K, V]`, `Set[T]` | Immutable collections |
| `MutableList[T]`, `MutableMap[K, V]` | Local mutable collections (§11.2) |
| `Option[T]` | `Some(value)` / `None` |
| `Result[T, E]` | `Ok(value)` / `Error(error)` |
| `Ordering` | `Less` / `Equal` / `Greater` |
| `function(A, B) returns R` | Function values (pure only, §12.2) |

### 8.4 User-defined types

- **`record`**: a named product type. Construct with named fields (`Rect(width = 2, height = 3)`), read with `r.width`, update with `r with (width = 4)`. All fields MUST be given. There are no defaults, so construction can't hide anything. `invariant` clauses are checked at construction and update (§10.5).
- **`choice`**: a tagged union. Each case may carry positional fields. Cases are in scope wherever the choice is, and MAY be qualified (`ConfigError.Missing(p)`) to resolve clashes.
- **Type aliases** and **newtypes** are not in v1. Use a single-field record for a distinct type.

### 8.5 Generics stance

- **Parametric polymorphism** on functions, records, choices, and interfaces: `function first[T](xs: List[T]) returns Option[T]`.
- **Constraints** name interfaces: `[T: Comparable and Hashable]`.
- **No** specialization, higher-kinded types, associated types, const generics, or variadic generics in v1.
- **Implementation-neutral semantics:** generic code behaves identically for every type argument (parametricity), so the interpreter can erase types while a later Wasm backend can monomorphize. Neither choice is observable.

### 8.6 Interfaces

- An `interface` lists function headers, and their contracts, that a type must provide.
- `implements Interface[Type]` supplies them. There MUST be at most one implementation per (interface, type) pair in a whole program (coherence). A second `implements` block for the same pair is `E3043`.
- **Orphan rule** (as in Rust): an `implements` block MUST live in the module that defines either the interface or the type (`E3040`).
- **Calls and constraints.** Constraints are checked at each call site: a type argument that misses one is `E3046` "Type does not implement the interface" (a missed `Showable` is `E3045`, a missed `Hashable` is `E3042`). Interface functions are called by name (`describe(r)`) or as methods (`r.describe()`); a top-level function or local with the same name wins. An `implements` block must supply every function (`E3044`) with the interface's type (`E3000`), may not add others (`E3004`), and inherits the interface's contracts.
- **Built-in interfaces:**
  - `Equatable` is derived automatically for every type whose fields are all equatable. Function types and resource types are not equatable.
  - `Hashable` is derived the same way, except that `Float` is not hashable (NaN breaks hashing).
  - `Comparable` is built in for `Int`, `Int64`, `Text` (code-point order), `Bool`, and `Ordering`. It is user-implementable for records and choices. `Float` uses `Float.total_compare` instead.
  - **Ordering operators** `< <= > >=` work only on `Int`, `Int64`, `Float` (IEEE comparison), and `Text` (code-point order). Every other `Comparable` type uses `compare` (§35.2).
  - `Showable` is derived automatically for every type **except** function types, resource types, and mutable collections (`MutableList`, `MutableMap`), and except any record, choice, `List`, `Map`, `Set`, `Option`, or `Result` that contains one of those, at any depth. `show` requires `T: Showable` and is checked at compile time: calling `show` on a type that isn't `Showable` is error **`E3045`** ("Type is not Showable"). The same rule decides how values are rendered in diagnostic `values`, a `fail` whose message isn't `Text`, a value propagated out of a test, and a `main` that returns `Error`; there, a value that isn't `Showable` is rendered as a placeholder (§9.8) rather than rejected. `Showable` gives the canonical text form (§9.8) used by `show`, diagnostics, and test output.
  - **Records with `Float` fields** use IEEE equality for those fields, the same rule as `Float ==`. So a record holding NaN is not equal to itself, and such records are not `Hashable`.
- **Users cannot implement `Equatable` or `Hashable`.** Derived structural equality is the only equality (closes RH-05, §23).

### 8.7 Method-call sugar

`x.f(a, b)` means `f(x, a, b)`, where `f` comes from the module that defines the type of `x`, a top-level function whose first parameter has that type, or the `implements` block for that type. There are no virtual methods and no subtyping. When the type of `x` is concrete, the call resolves at compile time. When it is a type parameter `T` with an interface constraint, the `implements` block is chosen at run time from the type of the argument passed for the first parameter of type `T`. A program has at most one block per (interface, type) pair (§8.6), so that is the block a compile-time choice in the instantiated caller would make, and erasing types stays unobservable (§8.5). If no parameter has type `T` (for example `function default() returns T`), a call with `T` still a type parameter has nothing to dispatch on and is `E3010`; the same call where `T` is concrete resolves from the expected type.

### 8.8 Exhaustiveness and reachability

- `match` MUST be exhaustive (`E3030` lists the missing cases). Arms with an `if` guard don't count toward exhaustiveness.
- Unreachable arms are `W3031`.
- Every path through a non-`Unit` function MUST end in `return` or `fail` (`E3032`). A bare `return` in a non-`Unit` function is also `E3032`.

### 8.9 Typing rules (sample of the formal style, §28)

The judgment `Γ ⊢ e : T ! ε` means: in context Γ, expression `e` has type `T` and may perform effects `ε`.

```
Γ ⊢ e1 : Int ! ε1     Γ ⊢ e2 : Int ! ε2
---------------------------------------- (T-Add-Int)
Γ ⊢ e1 + e2 : Int ! ε1 ∪ ε2

Γ ⊢ e : Result[T, E] ! ε     return type of enclosing function = Result[U, E]
------------------------------------------------------------------------------ (T-Try-Result)
Γ ⊢ try e : T ! ε

f : function[X](A1..An) returns R uses ε_f     Γ ⊢ ai : Ai[X := S] ! εi     ε_f ⊆ ε_enclosing
--------------------------------------------------------------------------------------------- (T-Call)
Γ ⊢ f(a1..an) : R[X := S] ! ε_f ∪ ε1 ∪ … ∪ εn
```

### 8.10 Later (deferred, with sketch)

- **Refinement types:** `Int where value > 0`, checked by runtime contracts first, then statically with an SMT solver (§21, level L3). Deferred until the core checker is stable.
- **Effect polymorphism** (§12.2).
- **Type aliases.**

---

## 9. Core Data Semantics

### 9.1 Int

- `Int` is an **arbitrary-precision** (unbounded) signed integer, like Python's `int`. `+ - *` and unary `-` **never overflow.**
- **Integer-size cap (default 65,536 bits).** Every `Int` value `n` must satisfy `bit_length(|n|) <= max_int_bits`. The default is **65,536 bits**, so allowed magnitudes are below 2^65536 (about 19,728 decimal digits; the largest allowed magnitude, 2^65536 − 1, has 19,729 digits). Any operation, conversion, literal, or parse whose exact result would exceed the cap traps with **`T6204` (integer size limit exceeded)**. Example: `pow(2, 10000000)` traps instead of burning compute.
- **Who sets the cap.** The host sets it per run: the CLI flag `--max-int-bits N`, the RL task file (`max_int_bits` in `task.toml`, §22.1), or the embedding app's configuration.
  - Sandbox hosts and task files MAY lower it.
  - Raising it above 65,536 requires explicit host configuration (the CLI flag, or the harness or host configuration). A task file alone cannot raise it.
  - The minimum is 64, so every `Int64` converts to `Int`. A value below 64 is refused at startup (infrastructure error `I9010`, invalid limit configuration). So is a task file that tries to raise the cap without host permission.
- **No oversized value is ever computed.** The trap depends only on the exact result's bit length. Implementations MUST NOT build an oversized value first. Required checks, where `bl(x)` is the bit length of `|x|` and `L` is the cap:
  - `x * y`: if `bl(x) + bl(y) − 1 > L`, trap. If `bl(x) + bl(y) <= L`, compute. Otherwise compute (the result has at most `L + 1` bits) and check.
  - `pow(x, e)` (`std.math`, `e >= 0`; a negative `e` violates its `requires`, `T6101`): for `|x| <= 1` the result is trivial. Otherwise, if `(bl(x) − 1) × e + 1 > L`, trap. If `bl(x) × e <= L`, compute. Otherwise compute by repeated squaring and check every intermediate value against `L`.
  - `+`, `-`, unary `-`, `div`, `mod`: the result grows by at most one bit, so compute and check.
  - Text → `Int` (`Int.parse`, literals, `std.json`): if the number of significant decimal digits exceeds `ceil(L × log10(2)) + 1`, trap before converting. Otherwise convert and check. `Int.parse` returns `None` only for text that is not an integer. Text that is an integer too big for the cap traps (`T6204`), the same as every other `Int` operation.
  - `Int` → Text (`show`, `std.json`) can't exceed the cap, because the value already fits.
- **Evaluation order for an `Int` operation** (it makes fuel and traps reproducible):
  1. Charge the base fuel.
  2. Run the definite-trap pre-check (`T6204`).
  3. Charge the size-dependent fuel (§12.5; `T6201` if fuel runs out).
  4. Compute.
  5. Run the final cap check (`T6204`).
- The cap is checked by bit length, not by time, so hitting it is **deterministic**: the same program and the same cap always trap at the same operation.
- `div` is **floored** division (rounds toward −∞). `mod` takes the sign of the divisor, so `a == b * (a div b) + (a mod b)` always holds. Division by zero traps (`T6002`).
- `/` is not defined on `Int` (`E3021`, hint: use `div` or convert to `Float`).
- There are no `Int.min` or `Int.max` constants.
- **Results are exact and identical on every machine.** Text form is plain decimal, with a `-` sign for negatives.
- **Rationale:** it matches LLM and Python habits, removes overflow failures that would add noise to RL rewards, and simplifies the rules while staying deterministic. **Costs:** speed (hidden in the Python interpreter, more visible in later backends) and the need for sandbox size caps. The 65,536-bit default leaves plenty of room for ordinary programs, cryptography-sized numbers, and factorials of a few thousand, while bounding the cost of any single operation.

### 9.1a Fixed-width integers (only `Int64` in v1)

- **`Int64`** (signed, −2^63 to 2^63−1) is the only fixed-width integer in language 0.1. Use it for performance or exact hardware-style behavior. **`Int32` and `UInt64` are not in v1.** A TEP may add them later if there is real demand.
- **Overflow traps** (`T6001`, fixed-width integer overflow). `Int64` **never wraps**, and there are no wrapping or saturating operators or functions. `Int64.checked_add`, `checked_sub`, and `checked_mul` return `Option[Int64]` for code that wants to handle overflow as a value. Unary `-Int64.min` traps (`T6001`). `div` and `mod` are floored, as for `Int`. Dividing by zero traps (`T6002`). `Int64.min div -1` traps (`T6001`), because the quotient does not fit. `Int64.min mod -1` is `0`, because the remainder always fits.
- **Operators:** `+ - * div mod`, unary `-`, `== !=`, and `< <= > >=`, with both sides `Int64`.
- **No mixing:** `Int + Int64` is a type error (`E3024`). Convert explicitly:
  - `Int64.from_int(i)` returns `Option[Int64]` (`None` if out of range).
  - `Int64.to_int(x)` always succeeds.
- **Integer literals are always `Int`** (§6.7). Writing a literal where an `Int64` is expected is `E3023`. The fix hint is to convert, for example `let n = Int64.from_int(42).expect_some("42 fits in Int64")`. The constants `Int64.min` and `Int64.max` are provided.
- `Int64` is `Equatable`, `Hashable`, `Comparable`, and `Showable`. Its canonical text form is plain decimal, the same as `Int`.

### 9.2 Float

- IEEE 754 binary64. `+ - * /` and `Float.sqrt` are correctly rounded (round-to-nearest-even).
- Division by zero follows IEEE (gives ±infinity or NaN) and does **not** trap. NaN is propagated.
- There is no fused multiply-add unless called explicitly (`Float.fma`), so results don't depend on the backend.
- **NaN canonicalization:** every NaN produced is the canonical quiet NaN, so bit patterns never vary.
- `==` follows IEEE (`nan != nan`). `Float.total_compare` gives IEEE 754 total ordering. `Float.same(a, b)` tests bitwise equality after canonicalization.
- Conversions:
  - `Float.from_int(i)` rounds to nearest-even. If the rounded result would be infinite (`|i|` too large for binary64), it **traps with `T6003`** (Int too large for Float). It never returns ±infinity silently.
  - `Int.from_float(x)` truncates toward zero and returns `Option[Int]` (`None` for NaN or infinity). The result can still hit the integer-size cap.
  - `Float.round`, `Float.floor`, and `Float.ceil` also return `Option[Int]` (`None` for NaN or infinity).
- **Transcendental functions** (`sin`, `cos`, `tan`, `asin`, `acos`, `atan`, `atan2`, `exp`, `log`, `log2`, `log10`, `float_pow`) are in `std.math`. Their results can differ slightly between platforms' C math libraries. in RL mode they are **unavailable**, and a program that references one is rejected at load time (`E4011`). In dev, test, and host modes they call the platform math library, and the docs say results may differ in the last bits across platforms. `sqrt` and the basic operations are always available, because IEEE 754 requires them to be correctly rounded.
- Text form: shortest round-trip decimal representation, always with a `.` or exponent (`1.0`, `1.0e-9`).

### 9.3 Bool

There is no truthiness. Conditions MUST be `Bool` (`E3022`). `and` and `or` short-circuit.

### 9.4 Text and Unicode

- `Text` is an immutable sequence of Unicode scalar values, stored as valid UTF-8. A `Text` can never hold invalid UTF-8. `Text.from_utf8(bytes)` returns `Result[Text, Utf8Error]`.
- **No integer indexing and no `len`**, because "length" is ambiguous. Instead there are explicit functions:
  - `t.byte_length()` and `t.code_point_count()`
  - `t.code_points()` returns `List[Int]`
  - `t.graphemes()` (stdlib, extended grapheme clusters per Unicode UAX #29)
- Slicing works by code-point index (`t.slice(start, end)`) and traps on an out-of-range index (`T6010`). `t.try_slice` returns `Option`.
- `==` compares scalar values exactly, with **no implicit normalization**. `Text.normalize_nfc` and `Text.normalize_nfd` are explicit.
- Ordering is lexicographic by code point. Locale-aware collation is not in v1.
- Case mapping (`to_upper`, `to_lower`) uses Unicode default (locale-independent) mappings.
- **The Unicode version is pinned per language version** (recorded in the spec), so case mapping and segmentation are deterministic. If the runtime's Unicode tables don't match the pin, the run is refused before it starts (infrastructure error `I9011`).
- `+` is not defined on Text. Use `Text.concat(a, b)` or `Text.join(list, separator)`.

### 9.5 Bytes

An immutable byte sequence. Literals come from `Bytes.of_hex("0a0b")` or `Bytes.of_list([10, 11])`.

- **Bytes constructors.** `Bytes.from_hex(text)` and `Bytes.from_list(items)` return **`Option[Bytes]`**: `None` when the input is bad (a list value outside 0–255, or hex text that isn't an even number of hex digits `0-9`, `a-f`, `A-F`). This matches the interpreter. The non-Option constructors are `Bytes.of_hex(text)` and `Bytes.of_list(items)`, which return `Bytes` and **trap `T6013`** on the same bad input. This is the same pair pattern as `get`/`at` and `try_slice`/`slice`. Use `from_…` for data you don't control and `of_…` for values you know are valid. The canonical text form (`show`) uses `Bytes.of_hex("…")`, because it must be an expression that builds a `Bytes`, not an `Option`.
- Indexing uses `b.get(i)`, which returns `Option[Int]`.

### 9.6 Collections

| Type | Semantics | Complexity guarantee (upper bound) |
| :-- | :-- | :-- |
| `List[T]` | Immutable, persistent (structure-sharing) sequence | `get`/`at`: O(log n). `with_appended`/`with_item`: O(log n). `length`: O(1). Iteration: O(n) |
| `Map[K, V]` | Immutable. **Insertion-ordered** iteration. `K: Hashable` | `get`/`with_entry`/`without_key`/`contains_key`: O(log n) expected. `length`: O(1) |
| `Set[T]` | Immutable. **Insertion-ordered**. `T: Hashable` | `contains`/`with_element`/`without_element`: O(log n) expected. `length`: O(1) |
| `MutableList[T]` | Local mutable list | `push`: amortized O(1). `get`/`set_at`: O(1). `length`: O(1) |
| `MutableMap[K, V]` | Local mutable map, insertion-ordered | `get`/`insert`/`remove`: expected O(1). `length`: O(1) |

- **Naming rule:** an operation on an immutable collection that returns a changed copy is always named `with_…` or `without_…`: `xs.with_appended(x)`, `xs.with_item(i, x)` (replaces item `i`, traps `T6011` if out of range), `m.with_entry(k, v)`, `m.without_key(k)`, `s.with_element(x)`, and `s.without_element(x)`. The verbs `push`, `insert`, `remove`, and `set_at` exist **only** on mutable collections, where they change the collection in place and return `Unit`. So the same name never means both "copy" and "mutate".
- Access never traps silently and never returns garbage. `xs.get(i)` returns `Option[T]`. `xs.at(i)` traps on a bad index (`T6011`), and the diagnostic shows the index and length. The checker warns (`W3050`) when `at` is used without a nearby bounds check. **Both forms are kept.** This is the only place two forms exist, and it is deliberate: `get` for possibly-missing items, `at` for indexes the code has already checked.
- Literals: `[1, 2, 3]` for List and `{"a": 1}` for Map. An empty `[]` or `{}` needs a type from context.
- **Iteration:** `for x in e` works when `e` is a `List`, `Set`, or `MutableList`. Maps are iterated through `m.keys()` (a `List[K]`) or `m.entries()` (a `List[Entry[K, V]]`, where `Entry` is a `std.core` record with fields `key` and `value`), both in insertion order. `MutableMap` has the same two functions. A `for` loop over a `MutableList` iterates over a **snapshot taken when the loop starts**, so changing the list inside the loop never affects the iteration.
- `List.range(a, b)` yields `a, a + 1, …, b − 1` (end-exclusive). It is empty when `a >= b`.
- Iteration order is always defined: list order, or insertion order for maps and sets. Removing then re-inserting a key moves it to the end.
- Structural equality: two maps are equal if they have the same entries, *regardless* of order. Iteration order is still observable through `for`.

### 9.7 Option, Result, Ordering

These are ordinary `choice` types defined in `std.core` and imported automatically. Helpers: `map`, `map_error`, `and_then`, `unwrap_or`, and `expect_some(message)` (traps with the message, `T6020`).

### 9.8 Canonical text form (`show`)

`show(value)` returns the canonical text form, which is also used in diagnostics, test output, and when `main` returns `Error`. **Rule: the canonical form is the Tersalang expression that would build the value.**

| Type | Canonical form | Example |
| :-- | :-- | :-- |
| `Int`, `Int64` | Decimal, with `-` for negatives | `-12` |
| `Float` | Shortest round-trip decimal, always with `.` or an exponent. Special values as constants | `1.0`, `2.5e-8`, `-0.0`, `Float.nan`, `Float.infinity`, `-Float.infinity` |
| `Bool` | `true` / `false` | `true` |
| `Text` | Double-quoted. `\\`, `\"`, `\n`, `\t`, and `\r` are escaped, and other control characters are written as `\u{…}` (lowercase hex). Other characters appear as themselves | `"a\tb"` |
| `Bytes` | `Bytes.of_hex("…")`, lowercase hex | `Bytes.of_hex("0aff")` |
| `Unit` | `Unit` | `Unit` |
| `List` | `[a, b]` | `[1, 2]` |
| `Map` | `{k: v, …}` in insertion order | `{"a": 1}` |
| `Set` | `Set.from_list([…])` in insertion order | `Set.from_list([1, 2])` |
| Record | `Name(field = value, …)` in declaration order | `Rect(width = 3, height = 4)` |
| Choice | `Case(value, …)`, or `Case` for a case without fields. Names are unqualified | `Some(3)`, `Empty`, `Error(NotFound("a.txt"))` |
| `Ordering` | `Less`, `Equal`, `Greater` | `Less` |

To print text without quotes, pass the `Text` itself to `print`.

**Values that aren't Showable.** `show` itself never sees one, because the checker rejects the call (`E3045`). Where the toolchain renders a value without a `show` call (diagnostic `values`, a non-`Text` `fail` message, a value propagated out of a test, or `main` returning `Error`) and the value isn't `Showable`, the **whole value** renders as a single placeholder: `<function>` for a function, `<resource>` for a resource, `<mutable>` for a mutable collection, and `<value>` for a record, choice, list, map, set, option, or result that contains one of those. Placeholders are never partial (a `Some` holding a function renders as `<value>`, not `Some(<function>)`), and they are not Tersalang expressions.

---

## 10. Errors, Traps, and Contracts

### 10.1 Two kinds of failure

1. **Expected failures are values:** `Result[T, E]` and `Option[T]`. Ignoring a `Result` is `E3002`.
2. **Bugs are traps:** fixed-width overflow (`T6001`), division by zero (`T6002`), `Int` too large for `Float` (`T6003`), bad index (`T6010`/`T6011`), `expect_some` on `None` (`T6020`), `fail` (`T6030`), a failed `expect` (`T6031`), contract or invariant violations (`T61xx`), exhausted resources including the integer-size cap (`T62xx`), and capability violations (`T63xx`). A trap stops the program (or the current test, §21). It **cannot be caught inside Tersalang in v1.** It produces a structured diagnostic with a trap code (`T6xxx`), the location, the call stack, and the values involved.

There are no exceptions. Rationale: exceptions add hidden control flow that models and reviewers both miss, and catch-all handlers are a classic reward hack (RH-07).

### 10.2 Propagation

`try e`:
- On `Ok(v)` or `Some(v)` it evaluates to `v`.
- On `Error(x)` or `None` it returns `Error(x)` or `None` from the enclosing function.
- The enclosing return type MUST be a `Result` with the *same* error type, or an `Option` (`E3060`). Error conversion is explicit with `map_error`.

### 10.3 Contracts: syntax and policy

- `requires` and `ensures` are allowed on functions, interface headers, and foreign declarations. Records can have `invariant` clauses.
- **Policy:**
  - Optional in user code.
  - Required on every public stdlib function, where meaningful (§15).
  - **Task-provided** in RL (§22). The model's own contracts never add reward.

### 10.4 Contract semantics

| Aspect | Rule |
| :-- | :-- |
| **Purity** | Contract expressions MUST be pure: no effects, no `var` mutation, no resource use (`E5002`). They may call pure functions. |
| **Evaluation order** | All `requires` clauses run in source order before the body, then the body, then all `ensures` clauses in source order. |
| **`result`** | Inside `ensures`, `result` is the return value. |
| **`old(e)`** | Inside `ensures`, `old(e)` is `e` evaluated at function entry. Values are immutable, so this costs a reference, not a copy. |
| **Blame** | A failed `requires` blames the **caller** (`T6101`) and reports the call site. A failed `ensures` blames the **function** (`T6102`). A failed invariant blames whoever constructed or updated the record (`T6103`). |
| **Contracts that trap** | A trap inside a contract counts as a violation of that contract (`T6104`). |
| **Fuel** | Contract evaluation uses fuel like any other code. |
| **Checking** | Checked at **runtime in every mode** in v1. Turning contracts off is not available. If it ever comes for speed, it MUST NOT be allowed in RL mode. |
| **Interface contracts** | Implementations inherit the interface's contracts. They MAY add `ensures` clauses but MUST NOT add `requires` clauses (`E5010`, the Liskov-style rule). |

### 10.5 Record invariants

Invariants are checked after construction and after every `with` update. Field reads never re-check them, because records are immutable.

### 10.6 Levels of "checked"

See §21.1 (L0 Parsed, L1 Typed, L2 Tested, L3 Verified).

---

## 11. Memory and Resource Model

### 11.1 Value semantics

- All values of built-in immutable types, records, and choices are **immutable**. Aliasing cannot be observed, so the language never needs to say whether something was copied or shared.
- **Memory management is automatic.** There are no pointers, no manual freeing, and no user-visible ownership or borrowing. Rationale: correctness and generation success come before performance (§2), and an ownership system adds a class of errors the model must learn.

### 11.2 Local mutability

- `var` bindings can be reassigned with `set`.
- `MutableList` and `MutableMap` values may only be held in `var` or `let` bindings inside a function body. They MUST NOT be stored in records, choices, or immutable collections, returned from public functions, or captured by lambdas (`E3070`). Convert with `.freeze()`, which is O(1) for ownership transfer or O(n) for a copy (the choice of strategy is an implementation detail).
- Lambdas capture `let` bindings by value. Capturing a `var` is `E3071`. So closures are always pure snapshots.

### 11.3 Resources (files, sockets, ...)

- **Resource types** (`File`, `Socket`, and others marked in the stdlib) MUST only be bound by a `using` block: `using name = expr`, then `do` on its own line, then the body and `end`. They cannot be stored, returned, put in collections, or captured (`E3072`).
- At `end`, or when a trap unwinds out of the block, the resource is closed. Nested `using` blocks close in reverse order. **There are no finalizers**, so cleanup timing is deterministic.

### 11.4 Deterministic memory accounting

The interpreter charges **memory units** by a fixed table that is part of the language version. The memory limit is enforced on these units, not on real process memory, so hitting the limit is deterministic (`T6202`). An OS-level memory limit stays in place as a backstop. Hitting the backstop is an infrastructure error (§22.4).

**Accounting rule:** memory units count **cumulative allocation** during a run. Units are charged when a value is created and are never refunded. This over-approximates peak memory, is trivially deterministic, and needs no cooperation from Python's garbage collector. A later language version MAY switch to live-size accounting through a TEP. The result field is `memory_units_used` (§22.3).

**Memory-unit table v0.1** (charges are defined by what the operation produces, not by how an implementation stores it):

| Allocation | Units |
| :-- | :-- |
| A new record or choice value with fields | 1 + 1 per field |
| A collection built from scratch (literal, `List.range`, `map`, `filter`, `keys`, `entries`, `split`, `Set.from_list`, `freeze`, …) | 1 + 1 per element (2 per map entry) |
| A collection derived from an existing one (`with_appended`, `with_item`, `with_entry`, `without_key`, `with_element`, `without_element`) | 1 + 1 for the added element (2 for an added map entry) |
| `push` or `insert` on a mutable collection | 1 per element (2 per map entry) |
| A new mutable collection (`MutableList.new`, `MutableMap.new`) | 1 |
| A new `Text` or `Bytes` value (literal, concatenation, slice, conversion, …) | 1 + 1 per started 8 bytes of content |
| An `Int` result with more than 64 bits | 1 per started 64 bits |
| A lambda (closure) | 1 + 1 per captured binding |
| `Int` values up to 64 bits, `Int64`, `Float`, `Bool`, `Unit`, cases without fields | 0 |

### 11.5 Stack depth

Call depth is counted by the interpreter and traps at the configured limit (`T6203`). It never depends on the host's C stack or Python's recursion limit.

### 11.6 Reclamation strategy (implementation detail)

The Python reference interpreter relies on CPython's own memory management. For the later Wasm backend, **reference counting** is chosen (studied in Swift and in Koka's Perceus work). It fits immutable data, and Tersalang values can't form cycles, because values are immutable and mutable collections can't be stored inside other values. The WebAssembly GC feature stays a possible later optimization. Neither choice is observable.

---
## 12. Effects, Capabilities, and Determinism

### 12.1 Effects (static)

A function declares what it may do with `uses`. Pure functions declare nothing. The checker makes sure every function's effects include the effects of everything it calls (`E4001` names the missing effect and where it came from).

| Effect | Grants access to | Capability scoping at runtime |
| :-- | :-- | :-- |
| `Console` | `std.console` (stdout/stderr write, stdin read) | Output size cap |
| `FileRead` | `std.file` read operations | A list of allowed directory roots |
| `FileWrite` | `std.file` write operations | A list of allowed directory roots |
| `Net` | `std.net` (HTTP client in v1) | A list of allowed hosts |
| `Clock` | `std.clock` (wall time, monotonic time) | Virtual clock in RL mode |
| `Random` | `std.random` | Host-supplied seed |
| `Env` | `std.env` (environment variables, args) | An allowlist of variable names |
| `Python` | `foreign` calls (§16) | Host mode only, never in RL mode |

User-defined effects are not in v1.

### 12.2 Effects and higher-order functions

In v1, **function values are pure**: function types carry no effects, and passing an effectful function as a value is `E4002`. Higher-order stdlib functions (`map`, `filter`, `fold`) therefore take pure functions. Effectful iteration uses `for` loops. *Later:* effect polymorphism (`uses E`) in the style of Koka.

### 12.3 Capabilities (runtime)

- The host (CLI, RL harness, or embedding app) grants capabilities at launch, for example `tersa run main.tersa --allow FileRead=./data --allow Console`.
- `FileRead`, `FileWrite`, and `Net` are scoped and need an explicit scope: `--allow FileRead=FOLDER`, `--allow FileWrite=FOLDER`, `--allow Net=HOST`. A scoped effect with no scope or an empty one, an unscoped effect given a scope (`--allow Console=x`), and an unknown or mis-cased effect name are `I9010`, exit 4, before anything runs. In RL mode an `--allow` for `FileRead`, `FileWrite`, `Net`, or `Python` is `I9017`, exit 4.
- The **load-time check** requires `main`'s declared effects to be a subset of the grants. Otherwise the program fails before running any code (`E4010`). `E4010` is only this pre-run check on `main`.
- **At run time**, a call that reaches an effect that wasn't granted (for example inside a test, which the harness runs with only the task's grants) traps **`T6302`** "Effect was not granted". In RL mode a task can never grant `FileRead`, `FileWrite`, `Net`, or `Python`, so such a call always traps.
- Scoped capabilities (directories, hosts) are also checked at each call (`T6301` on a violation).
- There is no ambient authority. A pure function cannot do I/O, and code cannot reach a capability it wasn't granted. This is the same capability-style approach WASI takes.
- The package manifest declares a **capability ceiling** (§14). Dependencies cannot declare effects beyond it.

### 12.4 Determinism contract

> **Given the same source, the same toolchain version, the same inputs, the same capability grants, and the same seed, an Tersalang program MUST produce byte-identical stdout, stderr, diagnostics, test results, and reward, on every supported platform.**

| Source of nondeterminism | Rule |
| :-- | :-- |
| Map/set iteration | Insertion order, always (§9.6) |
| Hashing | Hash values are never observable. No per-process hash seeds affect behavior |
| Integers | `Int` arithmetic is exact (arbitrary precision), so it is identical on every machine. The integer-size cap is checked by bit length, not time. Fixed-width types trap on overflow at the same operation everywhere |
| Floating point | binary64 only, correctly rounded basic ops, canonical NaNs, no implicit FMA, transcendental functions unavailable in RL mode (`E4011`, §9.2) |
| Unicode tables | Pinned Unicode version per language version (§9.4) |
| Time | Only via `Clock`. RL mode supplies a virtual clock that starts at a task-defined instant and advances only by fuel |
| Randomness | Only via `Random`, seeded by the host. The algorithm is fixed and documented per language version |
| Resource limits | **Fuel** (instruction budget), **memory units**, the integer-size cap, call depth, and output caps decide outcomes. Wall-clock and OS limits are backstops only. When one stops a candidate in the harness, the episode is a **scored resource trap**, not a discard: `T6206` (OS memory cap), `T6207` (OS CPU cap), or `T6208` (wall clock), each with reward 0, `C` 0, `E` 0, and exit 2, so a slow or crashing attempt cannot be farmed as a null reward. Because these depend on the host, they are outside the byte-identical promise above. Only an external fault the candidate cannot cause (the harness itself fails, an isolation backend cannot launch, or a reference is stopped while it is measured) is an infrastructure error, with a null reward and exit 4. In `tersa run` and `tersa sandbox` the wall-clock backstop stays `I9013` |
| Concurrency | None in v1 (§13) |
| Interop | `Python` effect not grantable in RL mode |
| Environment | `Env` not grantable in RL mode unless the task supplies fixed values |
| Toolchain | The result schema records the toolchain and language versions. Determinism is promised only within the same versions |

**Verification (part of the conformance suite, §28):** every conformance program runs repeatedly on each CI operating system, and the outputs must match byte for byte across reruns and across Linux, macOS, and Windows.

### 12.5 Fuel

- Every evaluation step costs fuel according to the table below, which is part of the language version, so fuel counts are reproducible.
- When fuel runs out, the program traps (`T6201`). Fuel is checked before each charge, so the trap happens at a deterministic point.

**Fuel table v0.1:**

| Event | Fuel |
| :-- | :-- |
| Evaluating any expression node (literal, name, operator, field access, `with`, list or map literal, lambda creation, `try`, `old`) | 1 |
| Executing any statement (`let`, `var`, `set`, `return`, `fail`, `expect`, `break`, `continue`, an expression statement), and each `if`, `match`, `while` condition check or `for` iteration | 1 |
| A function call (in addition to evaluating its arguments) | 1 |
| A contract clause or invariant | The cost of evaluating its expression |
| A stdlib function | 1, plus 1 per collection element, `Text` code point, or `Bytes` byte that it reads or produces |
| `Int` `+`, `-`, unary `-`, or a comparison where an operand has more than 64 bits | Extra `max(w(x), w(y))` |
| `Int` `*`, `div`, or `mod` where an operand has more than 64 bits | Extra `w(x) × w(y)` |
| `pow(x, e)` with a result over 64 bits | Extra `r × r`, where `r = ceil(bl(x) × e / 64)` |
| `Int` ↔ `Text` conversion of a value over 64 bits | Extra `w × w` |

Here `w(x) = ceil(bl(x) / 64)` is the number of 64-bit words in `|x|`. The quadratic terms are deliberately conservative upper bounds, so operations on huge integers are never cheap. Interpreter measurements (§19) may recalibrate the table only through a TEP before the first release.

### 12.6 Default limits per mode

| Limit | `dev` (`tersa run`) | `test` (`tersa test`) | `rl` (`tersa harness`) | `host` (embedding) |
| :-- | :-- | :-- | :-- | :-- |
| Fuel | Unlimited unless `--fuel N` | Unlimited unless `--fuel N` (per test) | **Required** in `task.toml` (> 0) | Set by the app (default unlimited) |
| Memory units | Unlimited unless `--memory-units N` | Unlimited unless `--memory-units N` (per test) | **Required** in `task.toml` (> 0) | Set by the app (default unlimited) |
| Integer size (`max_int_bits`) | 65,536 bits | 65,536 bits | 65,536 bits, or lower if the task says so | 65,536 bits unless the app configures otherwise |
| Call depth | 1,000 | 1,000 | 1,000, or lower if the task says so | 1,000 unless the app configures otherwise |
| Console output | Unlimited | 1,048,576 bytes per test | 1,048,576 bytes unless the task sets lower | Set by the app |
| Property-test cases | — | 100 per property unless `--cases N` | Set by the task (default 100) | — |

**Limits and codes as built** (`tersa harness` and `tersa sandbox`; `tersa run` stays unlimited unless flags are set):

| Limit | Set by | Default | When exceeded | Episode outcome |
| :-- | :-- | :-- | :-- | :-- |
| Fuel | `task.toml` `fuel` (required, > 0); `tersa sandbox --fuel` | Harness: none (required). Sandbox: 100,000 until `--fuel` | Trap `T6201` | Scored failure (`limit_hit = "fuel"`) |
| Memory units | `task.toml` `memory_units` (required, > 0); `--memory-units` | Harness: none (required). Sandbox: 100,000 until `--memory-units` | Trap `T6202` | Scored failure (`limit_hit = "memory"`) |
| Call depth | `call_depth`; `--max-depth` | 1,000 (allowed 1–1,000) | Trap `T6203` | Scored failure (`limit_hit = "depth"`) |
| Integer size | `max_int_bits`; `--max-int-bits` | 65,536 bits (allowed 64–65,536) | Trap `T6204` | Scored failure (`limit_hit = "int"`) |
| Console output | `output_bytes`; `--output-bytes` | Harness: 1,048,576 bytes (the maximum). Sandbox: 1,048,576 until `--output-bytes` | Output truncated, warning `W6205` | Run continues; the episode is kept and scored |
| Wall clock (backstop) | `wall_ms`; `--wall-ms` | Harness: 5,000 ms in-process, plus a 30 s timeout on the child process. Sandbox: 5,000 ms until `--wall-ms` | Candidate: `T6208`. Sandbox, `tersa run`, and the reference episode during validation or measurement: `I9013` | A candidate scores reward 0 with `C = 0` and `E = 0` (exit 2). The host cannot be told apart from a slow program. Sandbox and `tersa run` stay infrastructure (`reward` null, exit 4). A stopped reference fails `tersa harness validate` (exit 1). `tersa harness run` uses `E_basis_reason` `"reference_did_not_execute"` |
| OS memory (address space and data; harness child only) | The harness (`OsLimits`); not set by `task.toml` or a flag | 4 GiB under `rlimit` and `bwrap` on Linux and macOS; none on Windows or under `none` | The OS kills the child | Trap `T6206` (`OS memory limit exceeded`): reward 0 with `C = 0` and `E = 0`; `tersa harness run` exits 2 |
| OS CPU time (harness child only) | The harness (`OsLimits`) | 30 s soft, 31 s hard, under `rlimit` and `bwrap` on Linux and macOS | `SIGXCPU` at the soft cap | Trap `T6207` (`OS CPU limit exceeded`): reward 0 with `C = 0` and `E = 0`; exit 2 |

Only explicit host configuration can raise any limit above these defaults (CLI flags or host or harness configuration, §9.1). The OS caps apply only to the `tersa harness run` child (§20.3); "unlimited" `tersa run` and `tersa sandbox` stay in-process with no OS cap. The child's other OS caps (64 MiB file size, 256 open files, no core dumps, and on Linux a process cap of the user's current process count plus 64) make the offending call fail with an error; they are not kill codes. Exceeding output truncates the output and is reported as warning `W6205`; the run continues, and an RL episode is not discarded (it is not an infrastructure error). Exceeding call depth traps (`T6203`).

---

## 13. Concurrency and Parallelism

| Stage | What | Determinism |
| :-- | :-- | :-- |
| **v1** | **None.** Programs are single-threaded. I/O calls block. | Trivial |
| **Later, stage 2** | **Deterministic data parallelism:** `parallel for x in xs` (newline) `do` (newline) `expression` (newline) `end` (new keyword) over a *pure* single-expression body. Results are combined in input order. The runtime may use threads or processes underneath. | Guaranteed, because the bodies are pure and results are merged in order |
| **Later, stage 3** | **Message passing** between isolated tasks (actor-style). No shared mutable memory. In RL mode, a deterministic scheduler with a host seed. | Guaranteed in RL mode. In host mode, scheduling is free but data races are impossible by construction |
| **Not planned** | Shared-memory threads, locks, atomics | Not offered |

Rationale: Java's memory model (JLS Ch. 17) and C++'s (since C++11) show how much specification shared-memory concurrency needs. Avoiding shared mutable state removes the need for a memory model at the language level.

---

## 14. Modules, Packages, Manifest, and Lockfile

### 14.1 Modules

- **One file = one module.** The `module` line MUST match the file path relative to the package's `src/` directory: `src/geometry/shapes.tersa` is `module geometry.shapes` (`E2001`).
- The first path segment of every module in a package is the package name.
- **Imports:** `import geometry.shapes` (qualified use: `shapes.area(r)`), `import geometry.shapes as gs`, or `import geometry.shapes exposing Rect, area`. **No wildcard imports.**
- **Qualifier rule:** a plain `import a.b.c` is used through its **last path segment** (`c.name`). Two imports with the same qualifier, or a qualifier equal to a top-level name of the module, is `E2004` (fix: add `as`).
- **Standalone files:** a file run outside any package (for example `tersa run hello.tersa`) uses its file name without `.tersa` as its module name. It must be a valid lower name and match the `module` line (`E2001`). Standalone files may import only `std.*` modules.
- **Visibility:** private by default. `public` exports from the module. Package-internal visibility is not in v1.
- **No import cycles** (`E2002` shows the cycle; reported at the import that closes it).
- **Unknown module member (`E2005`):** a name after `exposing`, or after a module qualifier (`shapes.nope`), that the module doesn't define or doesn't make `public`. The same code is used if such a member is reached at run time.
- **Module initialization:** top-level `let` constants MUST be pure. They are evaluated once, in dependency order, before `main`. A cycle among constants is `E2003`. A constant whose initializer traps stops the program before `main` (exit status 2).
- **Prelude (imported automatically):** `std.core` (Option, Result, Ordering, built-in types, and their helpers), plus the prelude types `File`, `FileError` (from `std.file`), `Utf8Error` (from `std.text`), and the record `PythonError` (fields `type_name: Text`, `message: Text`; §16.2). Prelude names are always in scope. Importing one again (for example `import std.file exposing File, FileError`) is `E2021`, like any other duplicate name. Using `File` operations still requires `uses FileRead` or `FileWrite`.

### 14.2 Package layout

```
my_package/
  tersa.toml
  tersa.lock
  src/my_package/main.tersa
  src/my_package/...
  tests/          # extra developer tests (optional)
  examples/
```

### 14.3 Manifest `tersa.toml` (draft format)

```toml
[package]
name = "geometry"                 # LOWER identifier, unique within a registry
version = "0.1.0"                 # semantic versioning
language = "0.1"                  # Tersalang language version (edition after 1.0)
license = "Apache-2.0"            # SPDX identifier
description = "Shapes and areas"
authors = ["Your Name"]

[capabilities]
ceiling = ["Console", "FileRead"] # max effects any module here may declare
mode = "sandbox"                  # "sandbox" (default) or "host" (allows foreign/Python)

[dependencies]
textutils = { git = "https://github.com/example/textutils", rev = "<full commit hash>" }
shapes = { path = "../shapes" }

[dev-dependencies]
proptest_helpers = { path = "../proptest_helpers" }
```

### 14.4 Lockfile `tersa.lock` (draft format)

```toml
lock_version = 1
language = "0.1"

[[package]]
name = "textutils"
version = "0.2.1"
source = "git+https://github.com/example/textutils#<full commit hash>"
hash = "sha256:<hash of normalized source tree>"
capabilities = ["Console"]
```

- Builds MUST use the lockfile when present. A hash mismatch is a hard error (`E2101`; not implemented in the interpreter yet).
- The lockfile is written by tooling and is never hand-edited.

### 14.5 Dependency resolution

- v1 has **no central registry.** Dependencies are local paths or git repos pinned to a full commit hash. Version ranges arrive with a registry.
- There is exactly one version of each package per build. A conflict is an error that lists both requirements.
- **Registry (later):** content-addressed packages, signed publishing, and capability metadata shown at install time.

---

## 15. Standard Library v1 Scope

Every public stdlib function MUST have: a full signature, a `##` doc comment, at least one runnable example, contracts where meaningful, a documented complexity, and a fuel cost class.

| Module | Contents (v1) | Effect |
| :-- | :-- | :-- |
| `std.core` (prelude) | Prelude types from other modules: `File`, `FileError`, `Utf8Error`. The record `PythonError` (`type_name: Text`, `message: Text`). `Bytes.from_hex` / `from_list` (→ `Option[Bytes]`), `Bytes.of_hex` / `of_list` (→ `Bytes`, trap `T6013`). `Int`, `Int64`, `Float`, `Bool`, `Text`, `Bytes`, `Unit`, `Option`, `Result`, `Ordering`, `Entry[K, V]`, `show`, `Int.compare`, `Int.parse`, `Int64.from_int` / `to_int` / `checked_add` / `checked_sub` / `checked_mul` / `min` / `max`, `Float.from_int`, `Int.from_float`, `Float.total_compare` / `same` | none |
| `std.list` | `List.empty`, `List.range`, `get`, `at`, `with_appended`, `with_item`, `length`, `is_empty`, `contains`, `map`, `filter`, `fold` (pure functions), `sort` (stable, takes a `Comparable` or comparator), `zip_with` | none |
| `std.map` | `get`, `with_entry`, `without_key`, `contains_key`, `keys`, `entries`, `length`, `is_empty` | none |
| `std.set` | `Set.from_list`, `contains`, `with_element`, `without_element`, `length`, `is_empty` | none |
| `std.mutable` | `MutableList.new`, `push`, `get`, `set_at`, `length`, `freeze`; `MutableMap.new`, `insert`, `remove`, `get`, `keys`, `entries`, `length`, `freeze` | none |
| `std.text` | `concat`, `join`, `join_lines`, `split`, `trim`, `find`, `replace`, `slice`, `try_slice`, `code_points`, `code_point_count`, `byte_length`, `graphemes`, `to_upper`, `to_lower`, `normalize_nfc`, `normalize_nfd`, `from_utf8`, `is_empty` | none |
| `std.math` | `min`, `max`, `abs`, `clamp`, `gcd`, integer `pow` (size-capped), `sqrt`. Transcendental functions (§9.2) are unavailable in RL mode. No bitwise functions in v1 | none |
| `std.json` | Parse to a `Json` choice type, serialize with sorted or insertion order (documented), with errors as values | none |
| `std.testing` | Generators for property tests (seeded), approximate float comparison with an explicit tolerance | none (test only) |
| `std.console` | `print`, `print_error`, `read_line` | `Console` |
| `std.file` | `File.open` (a resource), `read_text`, `write_text`, `list_dir` | `FileRead` / `FileWrite` |
| `std.clock` | `now`, `monotonic` | `Clock` |
| `std.random` | `Random.int(range)`, `Random.float`, `shuffle` (fixed algorithm) | `Random` |
| `std.env` | `args`, `get` | `Env` |
| `std.net` | Basic HTTP GET/POST client | `Net` |

**Not in v1:** regex (a candidate for v1.x, as a linear-time engine for predictable fuel), bitwise operations, dates and time zones, databases, GUIs, and async.

The names above are **decided for language 0.1-draft**. The normative signatures, contracts, and examples for each function are written in `spec/`, following these names.

---

## 16. Interop / FFI Tiers

### 16.1 Tiers

| Tier | Where | Python access | Determinism |
| :-- | :-- | :-- | :-- |
| **T0 Sandbox** | RL harness, benchmarks, playgrounds | None. Pure Tersalang plus stdlib | Guaranteed |
| **T1 Vetted modules** | RL harness (optional) | None at runtime. Vetted functionality is re-implemented in Tersalang or in the interpreter's stdlib, then reviewed and added to the conformance suite | Guaranteed |
| **T2 Host interop** | Developer CLI and apps, with `mode = "host"` in the manifest | `foreign` declarations call Python. Python can call Tersalang | Not guaranteed. Marked by the `Python` effect |

### 16.2 Tersalang → Python (T2)

```
foreign "python:math.factorial" function factorial(n: Int) returns Int
  uses Python
  requires n >= 0
```

- The string names a Python module and attribute.
- Every foreign function MUST declare `uses Python` plus any other effects the Python code performs (on the honor system, and documented as such).
- Arguments and results are converted at the boundary (table below), and contracts are checked on both sides of the call.
- A Python exception becomes a trap (`T6401`) unless the declared return type is `Result[T, PythonError]`, in which case it becomes `Error(PythonError(type_name = …, message = …))`. `PythonError` is a prelude record:

```
record PythonError     # in the prelude (std.core)
  type_name: Text      # the Python exception's class name, for example "ValueError"
  message: Text        # str() of the exception
end
```


### 16.3 Data conversion

| Tersalang | Python | Rule |
| :-- | :-- | :-- |
| `Int` | `int` | Exact both ways. A Python int beyond the run's integer-size cap traps (`T6204`) |
| `Int64` | `int` | A Python int outside the `Int64` range traps (`T6402`, one specified case of a foreign value that can't be converted) |
| `Float` | `float` | NaN is canonicalized on entry |
| `Bool` | `bool` | Exact |
| `Text` | `str` | Strings with lone surrogates are rejected |
| `Bytes` | `bytes` | Copy |
| `List[T]` | `list` | Deep conversion |
| `Map[Text, V]` | `dict` (string keys) | Insertion order kept |
| `Option[T]` | value or `None` | `None` ↔ `None` |
| `Unit` | `None` | — |
| Records, choices | A dict with a `"$type"` key | Documented JSON-like shape |
| Functions, resources | Not convertible | `E4020` |

### 16.4 Python → Tersalang (T2)

The `tersalang` Python package exposes something like `tersalang.load("path/to/pkg")`, then `module.call("add", 2, 3)`, using the same conversion rules. Calls run with the capabilities the embedding app grants. Because the implementation is Python, this works in-process, which is exactly why it is never used for untrusted code.

### 16.5 Later

The WebAssembly Component Model as a general interop layer once the Wasm backend exists (§17.5), and other host languages.

---
# Part III: Implementation, Tooling, and Operations

## 17. Implementation, Runtime, and Targets

### 17.1 Implementation language

**The reference interpreter, checker, and toolchain are written in Python**. Consequences:
- Fast iteration while the spec changes.
- PyPI is the primary distribution channel.
- The tree-walking interpreter will be slow, which is acceptable for a reference implementation.
- **Python cannot sandbox code in-process**, so OS-level isolation is required for untrusted programs (§20).
- Python-specific determinism pitfalls must be handled explicitly. They include unbounded `int`, unordered `set`, hash randomization, platform `libm` differences, and recursion limits.

### 17.2 Pipeline

| Stage | Input → Output | Spec sections |
| :-- | :-- | :-- |
| Lexer | Source → tokens (with `NL` rules) | §6 |
| Parser | Tokens → concrete syntax tree, keeping comments for the formatter → AST | §7 |
| Resolver | AST → names bound, modules linked, cycles rejected | §14 |
| Type and effect checker | Resolved AST → typed AST, diagnostics | §8, §9, §12 |
| Contract instrumentation | Typed AST → AST with contract checks, `old()` snapshots, invariants | §10 |
| Typed IR (later) | Typed AST → a lower-level IR for backends | §17.5 |
| Reference interpreter | Typed AST → execution with fuel, memory units, and traps | §9–§12 |

### 17.3 Program lifecycle

1. Load the package and lockfile, then verify hashes.
2. Check the whole program.
3. Load-time capability check (§12.3).
4. Initialize module constants in dependency order.
5. Call `main`, which is `public function main() returns Unit` or `returns Result[Unit, E]` with declared effects.
6. Close resources and flush output.
7. Exit status: `0` on success, `1` when `main` returns `Error`, `2` on a trap, `3` on a check failure, `4` on an infrastructure or toolchain error. The RL harness never uses exit codes for reward (§22). As built, each command uses the codes this way:
   - `0`: success. For `tersa harness run`, every scored episode, including reward 0.
   - `1`: the command's own "no". `tersa run` and `tersa sandbox`: `main` returned `Error`. `tersa test`: a test failed or trapped. `tersa fmt --check`: a file would change. `tersa harness validate`: the task failed its gate (the reference isn't a perfect score, or a mutant still scores 1).
   - `2`: a trap in `main` (`tersa run`, `tersa sandbox`). `tersa harness run` also exits 2 for a candidate resource trap (`T6206`, `T6207`, `T6208`).
   - `3`: a check or parse failure, including `E4010` and a file `tersa fmt` can't parse.
   - `4`: an infrastructure or toolchain error: a file that can't be read or written, an invalid limit or a bad host grant (`I9010`), an RL-mode refusal of `FileRead`, `FileWrite`, `Net`, or `Python` (`I9017`), a task that can't be loaded (`I9014`–`I9022`, or `I9025` when the reference solution doesn't match `interface.tersa`), a backend that cannot launch (`I9024`), or a wall-clock stop that is still infrastructure (`I9013` on `tersa sandbox` and `tersa run`). `tersa harness run` exits 4 whenever the candidate episode's `infrastructure_error.code` starts with `I`. A reference stopped during validation fails `tersa harness validate` with exit 1. A candidate run whose reference did not execute exits with the scored episode, not 4. An `invalid_result` crash (§22.3) is a scored episode and exits 0. `I9023` is reserved.
8. **When `main` returns `Error(e)`**: the runtime writes `error: ` followed by `show(e)` (§9.8) and a newline to stderr, then exits with status 1. A trap writes the human-readable diagnostic (§18.1) to stderr and exits with status 2.

### 17.4 Execution modes

| Mode | Used by | Capabilities | Contracts | Limits | `foreign` |
| :-- | :-- | :-- | :-- | :-- | :-- |
| `dev` | `tersa run` | As granted on the command line | On | Defaults in §12.6 | Only if the manifest says `host` |
| `test` | `tersa test` | None by default | On | Per test, defaults in §12.6 | Only if the manifest says `host` |
| `rl` | `tersa harness`, `tersa sandbox` | Task-defined (harness) or `--allow` (sandbox) only. `FileRead`, `FileWrite`, `Net`, and `Python` never. `Env` only when `task.toml` supplies fixed values (§12.4) | On (in the harness, the task's interface contracts replace the attempt's own, §22.1) | Task-defined, fuel-based (§12.6) | **Never** (`E4012`) |
| `host` | Embedding from Python | As granted by the app | On | App-defined | Allowed |

### 17.5 Later targets

| Target | Approach | Notes |
| :-- | :-- | :-- |
| Bytecode VM (in Python) | Typed IR → compact bytecode → loop-based VM | A moderate speedup, easy to keep deterministic |
| PyPy | Run the same interpreter on PyPy | Often faster for interpreter-style code. Must re-verify determinism |
| **WebAssembly** | Typed IR → Wasm, run with wasmtime-py (which supports fuel metering) | The long-term sandboxed target. `Int` needs a bignum representation. The backend MAY use native `i64` for an `Int` when it can **prove** the value fits, falling back to bignum otherwise, with no observable difference. `Int64` maps to `i64` with overflow checks. **Restricted feature set:** no threads, no relaxed-SIMD or other nondeterministic instructions, canonical NaNs. The WebAssembly spec itself lists limited nondeterminism (NaN bit patterns, resource exhaustion, threads/relaxed operations), so these restrictions are required, not optional. |
| Native (Rust runtime), GPU | Possible much later | The same rule applies: `Int` may be narrowed to fixed width only where proven to fit. Only a Rust runtime would make crates.io matter |

Every backend MUST pass 100% of the conformance suite with results identical to the reference interpreter's.

---

## 18. Tooling

### 18.1 Diagnostics: JSON schema

```json
{
  "schema": "tersa.diagnostic/0.1",
  "code": "E3030",
  "severity": "error",
  "category": "type",
  "message": "match on ConfigError is not exhaustive",
  "file": "src/app/config.tersa",
  "span": {"start": {"line": 14, "column": 5}, "end": {"line": 22, "column": 8}},
  "related": [{"message": "missing case: BadLine", "file": "src/app/config.tersa",
               "span": {"start": {"line": 5, "column": 3}, "end": {"line": 5, "column": 23}}}],
  "blame": null,
  "values": null,
  "fix": {"description": "add the missing case",
          "edits": [{"span": {"start": {"line": 22, "column": 5}, "end": {"line": 22, "column": 5}},
                     "insert": "case BadLine(_) then\n  ...\n"}]},
  "docs_url": "https://<docs-site>/diagnostics/E3030"
}
```

**Code ranges:**

| Range | Category |
| :-- | :-- |
| `E00xx` | Lexical |
| `E1xxx` | Syntax |
| `E2xxx` | Names, modules, packages |
| `E3xxx` | Types |
| `E4xxx` | Effects and capabilities |
| `E5xxx` | Contracts (static rules) |
| `T6xxx` | Runtime traps (`T60xx` arithmetic/data, `T61xx` contracts, `T62xx` limits, `T63xx` capabilities, `T64xx` interop) |
| `W` + range | Warnings |
| `I9xxx` | Infrastructure and toolchain |

**Authoritative code list.** The file `spec/diagnostics.yaml` in the language repo is the authoritative list of diagnostic codes and their meanings. This doc and the Language Reference (Appendix B) mirror it; if they disagree, the YAML file wins and the docs are corrected. New codes are added there first. A CI test in the repo checks that the catalog, the codes the interpreter emits, and the tests stay in sync. Codes marked `reserved` (for example `I9012`, replaced by `W6205`) are retired and never reused. The interpreter's code `T6402` ("Foreign value cannot be converted") covers any value that can't cross the Python boundary at run time.

**Rules:**
- Codes are **never reused or renumbered.**
- Every code has a docs page with a wrong example and a fixed example.
- Messages are one line, in plain English, naming the construct.
- `fix.edits` are machine-applicable where safe.
- Human output is generated from the JSON, never the other way round.
- Codes not named in this document are assigned in `spec/diagnostics.yaml` within the ranges above, then never reused.

**Field shapes:**
- `blame` is `"caller"` (failed `requires`), `"function"` (failed `ensures`), `"constructor"` (a failed invariant, whether from construction or a `with` update), or `null`.
- `values` is a JSON object, or `null`. Its keys are the source text of the names and sub-expressions that appear in the failed condition, in order of first appearance. Its values are canonical text forms (§9.8; a value that isn't `Showable` renders as a placeholder such as `<function>` or `<value>`) as JSON strings.

**Human-readable layout:** this is the reference layout. Only the JSON is a stable interface, so tools MUST use `--json`.

```
error[E3030]: match on ConfigError is not exhaustive
  --> src/app/config.tersa:14:5
  = missing cases: BadLine
  = fix: add the missing case
```

- Line 1 is `severity[CODE]: message`. Traps print `trap[T6101]: …`.
- Line 2 is `  --> file:line:column`.
- Each `related` entry, value, and blame gets its own `  = …` line. The `fix` line comes last.

### 18.2 Formatter rules (`tersa fmt`)

- **No configuration options**, in the spirit of Go's `gofmt`.
- 2-space indentation per block level, LF line endings, one final newline, no trailing whitespace.
- Maximum line width: 100 characters. Long calls and literals break one item per line with trailing commas.
- One statement per line. One blank line between top-level declarations. No blank line right after `do` or `then`.
- Spaces around binary operators. No spaces inside brackets. One space after commas and colons.
- `uses`, `requires`, and `ensures` go on their own lines, indented under the header. **`do` always gets its own line**, at the declaration's indentation, as the grammar requires (§7.2). There is no same-line form (`E1000`).
- **Lambdas:** `do` and `end` go on their own lines, indented one level deeper than the line where the lambda starts; the body goes one level deeper again.
- Imports are sorted alphabetically. `exposing` lists are sorted (types first, then values).
- Parentheses are AST nodes. The formatter never removes one the author wrote. The only parentheses it adds are one pair around an `and` that is the direct operand of an `or`, which clears `W1103`.
- **Idempotent:** `fmt(fmt(x)) == fmt(x)`. Apart from that inserted group, formatting does not change the AST: it changes only whitespace, line breaks, comment placement, and the order of imports and `exposing` lists. CI checks both.
- **Opt-out:** a file containing a `# fmt: skip` line is left exactly as written when it parses (§18.2.1). A file that does not parse is still an error.
- Canonical formatted code is accepted by the decoding profile (§24), which is looser than the formatter, except a file with a comment over 500 characters, an opening header of more than 100 comment lines, or more than 30 comment lines in a row after code: `tersa fmt` keeps comments as written, and both profiles reject those.

**As built (`tersa fmt`, checked in CI by `scripts/check_fmt.py`).** The rules above hold, with these implementation details:

- **Invocation.** `tersa fmt FILE...` rewrites each file in place. A directory argument formats every `.tersa` file under it. With no paths, `tersa fmt` reads stdin and writes the result to stdout. `tersa fmt --check` writes nothing: it prints `would reformat PATH` and up to 40 lines of a unified diff to stderr, and exits 1 if any file would change. The Python API is `tersalang.fmt.format_source`.
- **Exit codes.** 0 when nothing needed to change or the files were rewritten; 1 for `--check` when a file would change; 3 when any file doesn't parse, whether it was named directly or found in a directory (its parse diagnostic is printed and it isn't written), including a `# fmt: skip` file; 4 when a file can't be read or written. With several files the highest code wins, so a run that finds both a parse error and a file that would change exits 3. A near-miss of the marker warns `W1104` and does not by itself change the exit code.
- **CI gate.** `tersa fmt --check conformance` exits 3, because that tree holds fixtures that are supposed to fail lexing or parsing. CI therefore runs `scripts/check_fmt.py`, which passes every `conformance/` and `examples/` file the formatter can read to `tersa fmt --check`. Unmarked fixtures that are meant to fail lexing or parsing are left out, but a `# fmt: skip` file that doesn't parse prints its diagnostic and makes the script exit 3.
- **`# fmt: skip`** files that parse are returned unchanged (§18.2.1). A marked file that does not parse raises the same format error as any other file.
- **Comments** are kept: a comment on its own line stays above the code it precedes (a comment group separated from that code by a blank line keeps the blank line), and a trailing comment stays on its line after two spaces. Runs of blank lines collapse to one, and trailing blank lines are removed.
- **Imports** are sorted by module path (then alias). `exposing` names are sorted with Upper names (types) first, then lower names.
- **Breaking.** A call, list, map, or `with` that doesn't fit in 100 columns breaks one item per line, each followed by a comma, with the closing bracket on its own line. A line that has no break point inside `()`, `[]`, or `{}` may exceed 100 columns. `uses` lists, import paths, and `for all` parameter lists always stay on one line, because a newline would end the production.
- **Spelling.** Function types print as `function(Int) returns Int`; a lambda keeps a space before its parameters: `function (x: Int)`. Other parentheses the author wrote are kept, so `(a + b) * c` is never rewritten.
- **`and`/`or` grouping.** The first format of a file with `a or b and c` writes `a or (b and c)`. That adds one group node with the same meaning, the only AST change `tersa fmt` makes. CI parses, formats, and re-parses every example and conformance program and requires identical trees, treating that one group as the bare `and` and comparing imports as a sorted set.

#### 18.2.1 `# fmt: skip` (official)

`# fmt: skip` is part of the language's tooling contract, not a build quirk. It opts a whole file out of canonical formatting. The marker below is unchanged. A marked file is still lexed and parsed; only the rewrite is skipped when that parse succeeds.

- **The marker.** A line whose text, after leading and trailing whitespace is removed, is exactly `# fmt: skip`: one `#`, one space, `fmt:`, one space, `skip`, all lowercase. Anything else on the line disqualifies it, so `#fmt: skip`, `# fmt:skip`, `# FMT: SKIP`, `# fmt: skip (CRLF fixture)`, and a trailing comment such as `let x = 1  # fmt: skip` are **not** markers (the first three are near-misses that warn `W1104`, below). Lines are split the way Python's `str.splitlines` does (LF, CRLF, and CR all end a line).
- **Placement.** Any line of the file counts: the first line, the last line, inside a function body, indented or not. Writing the marker more than once is the same as writing it once. Convention: put it near the top of the file with a comment above it saying why, so a reader sees it before the code.
- **Scope: the whole file.** There is no per-line, per-block, or `fmt: off`/`fmt: on` region form. A file is either fully canonical or fully skipped.
- **Effect on `tersa fmt`.** The file is always lexed and parsed, marker or not. When the exact marker is present and the file parses, the input is returned unchanged: `tersa fmt FILE` leaves the bytes untouched and exits 0, and stdin is echoed unchanged. When the file doesn't parse, the parse diagnostic is printed and the command exits 3, the same as for a file with no marker, and the file isn't written. Only the rewrite is skipped. `tersa fmt --check` uses that same rule.
- **Near-miss spellings (`W1104`).** After leading and trailing whitespace is removed, a line that is not the exact marker but matches, in any case, `#`, optional whitespace, `fmt`, optional whitespace, `:`, optional whitespace, `skip` (tabs count as whitespace; nothing else may appear on the line) warns `W1104` "Format-skip comment is not exactly `# fmt: skip`", once per such line, pointing at the comment. The message includes the exact spelling `# fmt: skip`. Examples: `#fmt:skip`, `# FMT: skip`, `# fmt:skip`. The file is **not** skipped and is formatted normally. `tersa fmt` and `tersa check` both emit the warning, and the warning alone does not change a successful exit code. Extra words (`# fmt: skip (reason)`) and a trailing comment after code (`let x = 1  # fmt: skip`) do not normalize to the marker and get no warning. The exact marker, including when leading or trailing whitespace surrounds it, does not warn. A file that has both the exact marker and a near-miss line is skipped and still warns. `tersa fmt` prints the warning before formatting, so it also appears when the file then fails to parse. `tersa check` emits it with or without `--parse-only`. `tersa fmt` (including `--check` and stdin) and `tersa check` (with or without `--parse-only`) always emit it, with or without other errors. `tersa run`, `tersa sandbox`, and `tersa test` print it, like every warning, only beside a check error or trap that stops the run; a run that succeeds, or whose `main` returns `Error`, prints none. The RL harness never reports it. Conformance test: `conformance/syntax/w1104_fmt_skip.tersa` (a `#fmt:skip` line, expected result `check-warn W1104`).
- **Exempt from the gates.** A skipped file that parses is exempt: `tersa fmt --check` never reports it as needing a reformat, so it can't cause exit 1. The decoding grammar profile (§24) is **not required to accept** it; the CI test that matches formatter output against the decoding profile leaves those files out. A skipped file that doesn't parse is not exempt: it fails the formatter gate with exit 3.
- **Everywhere else it is an ordinary comment.** `#` starts a comment, so the marker has no effect on lexing, parsing, type checking, running, the harness, or the reward. A correctly marked file gets no diagnostic for the marker.
- **Intended use.** Files whose exact layout is the point: test fixtures and corpora that must stay non-canonical. The conformance suite uses it in exactly three files: the CRLF fixture, the newline-suppression fixture (formatting would collapse the continuation lines it exists to test), and the `W1103` mixed `and`/`or` fixture (formatting would add parentheses and remove the warning). Ordinary code shouldn't use it.

### 18.3 Language server (LSP)

| Phase | Features |
| :-- | :-- |
| 1 | Diagnostics (same JSON source), formatting, document symbols, semantic highlighting |
| 2 | Hover (type plus doc comment plus contracts), go-to-definition, find references, completion for names and keywords |
| 3 | Code actions from `fix.edits`, rename, signature help, effect and capability hints |

Implementation: Python, sharing the checker (for example on the `pygls` library). A TextMate grammar provides basic highlighting in editors without the LSP.

### 18.4 Other tools

- `tersa test` (§21).
- The commands:

| Command | What it does |
| :-- | :-- |
| `tersa check FILE [--json] [--parse-only] [--mode dev\|test\|rl\|host]` | Lex, parse, and check one file. `--json` ends stdout with one line holding the diagnostic array |
| `tersa run FILE [--allow EFFECT[=SCOPE]] [--seed N] [limit flags] [--json] [--mode dev\|test\|rl\|host]` | Run in dev mode. Warnings are printed only beside a check error or trap that stops the run |
| `tersa test FILE [--seed N] [--cases N] [limit flags] [--json] [--mode ...]` | Developer tests, property tests, doc examples; ends with `N tests passed, M doc examples passed` |
| `tersa sandbox FILE [--allow EFFECT[=SCOPE]] [--seed N] [--fuel N] [--memory-units N] [--max-int-bits N] [--max-depth N] [--output-bytes N] [--wall-ms N] [--json]` | Runs `main` in RL mode with only the grants passed: no `foreign`, no transcendental math, no effect the host didn't grant. Limit defaults and codes are in §12.6 |
| `tersa harness run TASK_DIR --attempt FILE [--seed N] [--attempt-id ID] [--in-process] [--isolation none\|rlimit\|bwrap\|nsjail\|gvisor] [--agent-view]` | Scores one attempt against the task's hidden tests and prints one `tersa.result/0.9` JSON object (§22.3); `--agent-view` prints the agent's copy instead (§22.5). By default the attempt runs in a child process under the strongest isolation backend that can launch (§22.6); `--in-process` skips the child. A task that fails to load prints `error[CODE]` and exits 4. A scored episode exits 0. A candidate resource trap (`T6206`, `T6207`, `T6208`) exits 2. An infrastructure error exits 4 |
| `tersa harness validate TASK_DIR` | Mutation-checks the task's reference solution (§22.7) and prints `{ok, reference_reward, mutants, warnings}`. Exits 0 when the task is valid, 1 when it isn't |
| `tersa grammar --format ebnf\|lark\|gbnf [--profile full\|decoding]` | Prints the grammar, including generated GBNF (§24). `--kind` is a hidden deprecated alias and prints a deprecation warning on stderr |
| `tersa fmt [PATH...] [--check]` | Canonical formatter (§18.2). Files and directories are rewritten in place; no paths means stdin to stdout; `--check` exits 1 if a file would change; a file that doesn't parse exits 3; `# fmt: skip` files are left alone (§18.2.1) |
| `tersa version` | Prints the toolchain, language, diagnostic-schema, and result-schema versions, and the host's `unicodedata` version |

`--mode` picks the §17.4 mode: `dev` and `test` reject `foreign` (`E4012`); `rl` also rejects transcendental math (`E4011`) and refuses the four grants in §12.3 (`I9017`); `host` allows `foreign` Python calls and stands in for a manifest that says `host`.

- `tersa grammar --format ebnf|lark|gbnf` (§24) is built. `--kind` remains as a hidden deprecated alias, accepts the same three values, and prints a deprecation warning on stderr.
- `tersa fmt` (§18.2) is built.
- `tersa doc` (§29).
- `tersa migrate` (§30).
- A REPL is deferred (useful for humans, low value for RL).

---

## 19. Performance

Raw speed is a non-goal, but **check-and-run latency directly limits RL throughput.** No numeric targets are set until baselines exist.

| What | How measured | When the budget is set |
| :-- | :-- | :-- |
| Check latency per program | A fixed corpus of benchmark-sized programs, timed with `pyperf` | After a checker baseline |
| Run overhead per harness attempt | End-to-end harness time, including process start | After a harness baseline |
| Interpreter throughput | Fuel units per second on a micro-benchmark set | After an interpreter baseline |
| Integer arithmetic cost | Time for `Int` and `Int64` operations across operand sizes, used to calibrate the size-proportional fuel formula (§12.5) | After an interpreter baseline |
| Memory per attempt | Peak RSS (resident memory) | After a harness baseline |

- **Language-level guarantees:** the collection complexity bounds in §9.6, and stdlib complexity documented per function (§15).
- **Regression policy:** CI tracks these metrics, and a significant slowdown needs a justification in the PR. The threshold is set once noise levels are known.
- **Improvement path:** profile (`cProfile`), then optimize hot paths, then the bytecode VM, PyPy, or Wasm (§17.5).

---

## 20. Security and Sandbox Threat Model

### 20.1 Assets

Host machines, reward integrity, users' files and credentials, the package supply chain, and project accounts and release keys.

### 20.2 Adversaries

1. **Model-generated code under optimization pressure.** It isn't malicious, but RL will find any exploit that pays.
2. Malicious users of hosted playgrounds or services.
3. Malicious package authors.
4. Attackers going after maintainer accounts or the CI pipeline.

### 20.3 Threats and mitigations

| Threat | Mitigation |
| :-- | :-- |
| Escape from the interpreter to the host (an interpreter bug) | Layered isolation: **(1) the language sandbox plus the subprocess runner**, all platforms, **built**. **(2) `setrlimit` on the child** before it runs: address space and data, CPU seconds, file size, open files, and no core dumps, plus a process-count cap where the host can count processes. Linux and macOS. **Built.** Windows job objects are unsupported in this build (the child would start before a job could be assigned, and nested jobs are commonly denied), so Windows records `isolation` `"none"` and a warning. **(3–4) bubblewrap** on Linux when `bwrap` is installed: no network, a read-only root, a tmpfs workspace (`/tmp/tersalang-workspace`), separate PID, IPC, and UTS namespaces, and all capabilities dropped, with the layer-2 limits inherited. **Built** where bubblewrap is installed (Ubuntu CI installs it and relaxes the disposable runner's AppArmor userns sysctl so loopback setup is allowed). nsjail has no launcher. gVisor `runsc` is not launched: without host cgroup access it is denied, and with it this build hung. `--isolation none\|rlimit\|bwrap\|nsjail\|gvisor` selects a backend; the default is the strongest that can launch, and skipped stronger names are recorded in `isolation_warning`. A seccomp profile is not applied. The sandbox user namespace maps the calling user to uid 0 inside; it does not create a separate host account. This isolation is not meant for a public service that runs untrusted code. The harness child inherits only an allowlist of environment variables on every OS (`PATH`, `SYSTEMROOT`, `WINDIR`, `TEMP`, `TMP`, and fixed Python settings). Under bubblewrap the root is empty and read-only except for the Python install, the `tersalang` package, the shared libraries, `/etc/ld.so.cache`, the task directory, and the attempt. |
| Resource exhaustion (CPU, memory, disk, output), including huge-integer arithmetic | Fuel (size-proportional for `Int`), memory units, the integer-size cap (`T6204`), depth limits, and output caps (all deterministic), plus OS backstops |
| Reward tampering | §23 catalog. Harness tests in a separate process. Structured results only |
| Capability abuse | No ambient authority. Load-time and per-call checks. A manifest capability ceiling |
| Malicious dependency | Lockfile hashes, capability metadata, no install scripts (Tersalang packages are source only), and only vetted dependencies in RL mode |
| `foreign`/Python abuse | `foreign` only in host mode. Never in sandbox or RL modes, checked at load time |
| Supply-chain attack on releases | PyPI Trusted Publishing, signed releases and attestations, SBOMs, and 2FA everywhere |
| Unreported vulnerabilities | `SECURITY.md`, GitHub private vulnerability reporting, and coordinated disclosure |

Lesson from prior art: Java's in-language SecurityManager was deprecated for removal (JEP 411). Tersalang never relies on the language layer alone.

---
# Part IV: AI and RL Infrastructure

## 21. Testing and Verification

### 21.1 Levels of "checked"

| Level | Meaning | Tool | When |
| :-- | :-- | :-- | :-- |
| **L0 Parsed** | Conforms to the grammar (§7) | `tersa check --parse-only` | v1 |
| **L1 Typed** | Passes name, type, and effect checking, with exhaustive matches | `tersa check` | v1 |
| **L2 Tested** | Contracts and invariants hold, and tests pass, *on the inputs executed* | `tersa test`, `tersa harness` | v1 |
| **L3 Verified** | Contracts proven for all inputs (an SMT solver, as Dafny uses Z3) | Later | Deferred until the core is stable |

### 21.2 Kinds of tests

| Kind | Syntax | Author | Location | Counts for RL reward |
| :-- | :-- | :-- | :-- | :-- |
| Developer test | `test "name"` (newline) `do` … `end` | Program author | Same file or `tests/` | **No** |
| Property test | `test "name" for all a: Int` (newline) `do` … `end` | Either | Same | Only when task-provided |
| Doc example | `## Example: expr == value` | Program author | Doc comments | No |
| Harness test | Same syntax, in a harness-owned package | Task author | `hidden/` (never visible to the agent) | **Yes** |
| Task spec | Contracts in `interface.tersa` (a module such as `task_spec`), copied onto the solution's free function of the same name (§22.1) | Task author | Task folder | **Yes** |

### 21.3 Test semantics

- Each test runs in **fresh state**. Tests cannot share mutable state, and there are no ordering dependencies. Within a run, tests execute in source order.
- A trap fails only that test. The runner continues with the next one.
- **Property tests:** generators come from `std.testing`. The seed comes from the host. The default is **100 cases per property** (§12.6). On failure, the runner shrinks to a minimal counterexample (as Hypothesis and QuickCheck do) and reports it with the seed.
- **Built-in generators:**
  - Covered types: every built-in type except function types, resource types, and mutable collections, plus records and choices whose fields all have generators. Generic types must be instantiated.
  - `Int` values stay within the run's cap and are biased toward small values and boundaries (0, ±1, and the `Int64` limits).
  - `Float` includes NaN, ±infinity, and −0.0.
  - `Text` includes non-ASCII characters.
  - Generated record values that would violate an invariant are discarded and don't count as cases.
- Tests may declare effects only if the runner grants them. The default is none.

### 21.4 Conformance suite and fuzzing (for the implementation)

- See §28 for the conformance suite.
- Grammar-based fuzzing generates random valid programs from the EBNF, and the checker and interpreter must never crash on them (crash = bug).
- Differential testing compares backends against the reference interpreter (§17.5).
- **Mutation testing of harness test suites:** a task's hidden tests must reject mutated versions of its reference solution. This guards against weak tests (RH-17).

---

## 22. RL Harness and Reward Design

### 22.1 Task format

```
task_0001/
  task.toml                  # id, language version, allowed effects, limits, reward config, seed policy
  prompt.md                  # natural-language problem statement shown to the agent
  interface.tersa            # optional: required signatures + task-spec contracts (shown to the agent)
  visible_tests.tersa        # optional: examples shown to the agent
  hidden/                    # required, at least one .tersa file. NEVER shown to the agent
    tests.tersa
  reference/solution.tersa   # used for validation and mutation testing, never shown
```

```toml
# task.toml (examples/tasks/add_one)
id = "add_one"
language = "0.1"            # must equal the toolchain's language version
effects = []                # empty = pure. Unknown effect names, FileRead, FileWrite, Net, and Python are refused
[limits]
fuel = 100000               # required, > 0; set per task from the reference solution
memory_units = 100000       # required, > 0
max_int_bits = 65536        # default; allowed 64..65536 (a task may lower it, never raise it)
call_depth = 1000           # default; allowed 1..1000
output_bytes = 1048576      # default and maximum
wall_ms = 5000              # wall-clock backstop (default 5000)
cases = 4                   # property-test cases per property (default 100)
[reward]
check_credit = 0.0          # default; must be within 0..1
efficiency_weight = 0.1     # default; must be within 0..1
reference_fuel = 88         # optional; used only when the reference can't be measured; validate checks it against a real reference run
[seeds]
property_seed_policy = "per_episode"   # or "fixed"
fixed_seed = 0              # used when the policy is "fixed"
# [env]                     # optional fixed values; listing any grants Env with exactly these values
```

**Loading a task.** The harness refuses a task, before any attempt runs, when `task.toml` is missing (`I9014`), `language` doesn't match (`I9015`), `effects` names an unknown effect (`I9016`) or one RL mode can't grant (`FileRead`, `FileWrite`, `Net`, `Python`; `I9017`, also when it is written with a scope such as `FileRead=data`), `fuel` or `memory_units` is missing or not above 0 or another limit is outside its allowed range, or an entry gives a scope to an effect that takes none such as `Console=out` (`I9010`), a reward weight is a number outside 0..1 (`I9018`), the seed policy is unknown (`I9019`), `hidden/` is missing or has no `.tersa` file (`I9020`), a task field has the wrong type, including a limit that is present but not an integer and a reward weight that isn't a number (`I9022`), or any hidden file or a non-empty `interface.tersa` doesn't parse (`I9021`). `tersa harness` prints `error[CODE]: <reason>` and exits 4. `I9010` is an invalid limit or a scope on an unscoped effect. An `effects` entry is a bare effect name: every effect that takes a scope is one RL mode refuses, so no task grant carries a scope. The task hash is SHA-256 over every file in the task folder (path plus content, CRLF normalized to LF), excluding any `attempt` path. Only `prompt.md`, `interface.tersa`, and `visible_tests.tersa` are ever given to the agent.

**The interface file.** `interface` is a reserved keyword (§6.6), so the file's module uses another name, such as `task_spec`. It can declare the required functions inside an `interface` block or as free functions. For example (the shipped `add_one` task):

```
module task_spec

interface Solution
  function add_one(n: Int) returns Int
    ensures result == n + 1
end
```

**How the task spec binds.** The scored attempt is an ordinary module with a **free function** of the required name; it does **not** write `implements`. Before the hidden tests run, the harness builds one combined module:

- It keeps every declaration of the attempt except its `test` blocks and `main`: records, choices, constants, functions, interfaces, and `implements` blocks. The attempt's own interfaces and `implements` blocks stay, so an attempt may declare and implement a helper interface. An attempt that passes its own check therefore still type-checks inside the combined module.
- On each kept function named in the interface, it replaces that function's own `requires`/`ensures` with the interface's contracts. A function the interface does not name keeps its own contracts.
- It adds the hidden tests and the hidden functions (except `main`), constants, records, choices, and interfaces, and merges the imports. Every name a hidden file declares, top-level or local, including interface names and interface function names, is renamed to `name@hidden`, so the attempt can neither reach nor redefine it. A call written as a method, `x.helper()`, is renamed with the helper. Names that `interface.tersa` declares belong to the attempt and are not renamed; a hidden declaration of one of them is dropped.
- It adds a hidden `implements` block when its interface is a hidden interface, or when its interface is public (`Comparable` or one declared in `interface.tersa`) and its type is a hidden record or choice. It drops a hidden `implements` of a public interface for a type the attempt can name: kept, it could change which function the attempt's own calls dispatch to, and an attempt that implements the same pair would get `E3043` because of hidden code. Hidden `foreign` declarations are dropped.

Visible tests are merged the same way under `@visible`. The combined module is checked again in RL mode before it runs.

**Signatures.** Before the combined module is built, each function `interface.tersa` requires (a header in an `interface` block, with that block's type parameters first, or a top-level function) must be a top-level function of the attempt with the same name, the same type parameters by position (`T` and `U` match) and constraints, the same parameter count and types, and the same return type. Parameter names, `public`, contracts, and effects are not compared; the interface's contracts replace the attempt's, and the task's `effects` grant governs effects. A missing or different function is `E3047`: the episode stops at `stage_reached = "check"` with `C = 0` and reward 0, and the diagnostic names the difference and keeps full detail in the agent's view, because the interface is public. The same check runs on `reference/solution.tersa` when the task loads; a reference that does not match is `I9025` and the task does not load.

### 22.2 Reward computation (as implemented)

1. **Lex/parse failure** → `C = 0` and `E = 0` (`stage_reached = "parse"`). The candidate did not run, so it earns no efficiency. The reward is 0.
2. **Check failure** (L1, of the attempt or of the combined module) → `C = check_credit` (default 0) and `E = 0` (`stage_reached = "check"`). The candidate did not run. With `w = 0` the reward stays `check_credit`. With `w > 0` it is `(1 − w) × check_credit`. Hidden tests that didn't run are counted as failed. A function that does not match `interface.tersa` (`E3047`, §22.1) is the exception: `C = 0` and the reward is 0, even beside other check errors.
3. **Run:** every hidden test runs in a **fresh interpreter with the same seed**. A test **passes** only if it completes with all `expect`s true and no trap, *including* task-spec contract and invariant violations. `fail` (`T6030`) and a failed `expect` (`T6031`) count as *failed*; any other trap counts as *trapped*. `test_score = passed / total`. A task with **zero hidden tests scores 0** and `E = 0`.
4. **Correctness** `C` = `check_credit + (1 − check_credit) × test_score`. A parse failure and a task with zero hidden tests use `C = 0`. A check failure uses `C = check_credit` (tests did not run). Contract failures fail the hidden test, so they lower `C`.
5. **Efficiency** uses the reference basis only when the reference solution executes and passes every hidden test (`C_ref = 1`). `ref_fuel` is the fuel that run uses across the hidden tests, summed the same way as the candidate, under the same limits and seed. `E = min(1, max(ref_fuel, 1) / max(fuel_used, 1))`. A reference that used no fuel still counts as 1, so a correct reference scores `E = 1` and, with `C = 1`, reward 1. Matching or beating the reference is 1, twice the fuel is 0.5, and ten times the fuel is 0.1. The harness measures this by running the reference and caches it for that seed. A value of `[reward] reference_fuel` that is not an integer ≥ 0 is `I9022`. The floor applies only inside the formula: `breakdown.ref_fuel` reports the raw measured fuel, including 0.
6. **Limit fallback.** Otherwise `E = max(0, 1 − fuel_used / fuel)`, where `fuel` is the task's limit, `E_basis` is `"limit"`, and `E_basis_reason` is `"no_reference"`, `"reference_did_not_execute"`, or `"reference_failed_hidden_tests"`. `ref_fuel` is `null` on that fallback. A declared `reference_fuel` is trusted during a run only when the measurement is not available (no reference, or the reference did not execute). A reference that ran and failed hidden tests is not the yardstick, even when that field is set. `tersa harness validate` checks a declared number against the real run and fails the task when the reference does not pass every hidden test. `E` is in `[0, 1]`. A limit that isn't positive gives `E = 0` (the loader already refuses such a task with `I9010`). When a declared value stands in, `E_basis` is `"declared"`, `ref_fuel` is the declared number, and `E_basis_reason` is `"no_reference"` or `"reference_did_not_execute"`. The same formula applies, including the `max(ref_fuel, 1)` floor. The reference is still run first (once per seed), even when a value is declared.
7. **Reward** = `(1 − w) × C + w × C × E`, where `w` is `efficiency_weight`. Efficiency is gated by correctness, so a fast wrong program earns nothing extra. With every hidden test passing and the default `w` of 0.1, the reward is `0.9 + 0.1 × E`, between 0.9 and 1. There is no clip. `C`, `E`, `w`, and the reward are each in `[0, 1]`; a value outside that range is an assertion failure. Each is rounded to 10 decimal places. The `add_one` reference uses 88 fuel, so `E = 1` and the reward is 1.
   - **Worked example** (the `add_one` reference solution, from the build's determinism test): its two hidden tests use 16 (`h_forty_one`) and 72 (`h_property`) fuel, so `ref_fuel = 88` and `fuel_used = 88`. `C = 1`, `E = min(1, max(88, 1) / max(88, 1)) = 1`, `E_basis = "reference"`, `E_basis_reason = null`, `w = 0.1`, and the reward is `0.9 × 1 + 0.1 × 1 × 1 = 1.0`.
8. The model's own contracts and developer tests **never** change the reward.
9. Weights are per-task configuration. **Defaults (resolving OQ-1): `check_credit = 0.0` and `efficiency_weight = 0.1`.** A number outside 0..1 is `I9018`. A reward field that is not a number is `I9022`. `w = 0` leaves the reward equal to `C`.
10. `fuel` and `memory_units` MUST be set (> 0) in every task. The harness refuses a task without them (`I9010`). Example values in task files are illustrations only; each task sets its own from its reference solution.
11. Fuel, memory, depth, and integer-cap traps are **scored failures**. Truncated output (`W6205`) keeps the episode. A candidate OS memory kill (`T6206`), OS CPU kill (`T6207`), or wall-clock stop (`T6208`) scores reward 0 with `C = 0` and `E = 0` (§22.4). `I9013` stays infrastructure for sandbox and `tersa run` (exit 4). On the reference episode it stays `I9013` with a null reward; `tersa harness validate` exits 1, and `tersa harness run` uses `E_basis_reason` `"reference_did_not_execute"`.
12. Visible tests are run separately (with the same contract replacement) and reported as `visible_tests`. They never count toward the reward.

### 22.3 Result schema (reward output, `tersa.result/0.9`)

This is the `add_one` reference solution at seed 0. `toolchain.python` and `toolchain.platform` are the normalized `canonical_bytes` values. The hidden tests use 16 and 72 fuel, so `fuel_used` and `ref_fuel` are 88, `E` is 1, and the reward is 1.

```json
{
  "schema": "tersa.result/0.9",
  "task_id": "add_one",
  "attempt_id": "reference",
  "toolchain": {"tersalang": "0.1.0", "language": "0.1", "python": "python", "platform": "platform"},
  "stage_reached": "run",
  "diagnostics": [],
  "attempt_diagnostics": 0,
  "tests": {"total": 2, "passed": 2, "failed": 0, "trapped": 0,
            "cases": [{"id": "h_forty_one", "status": "passed", "fuel": 16},
                      {"id": "h_property", "status": "passed", "fuel": 72}]},
  "visible_tests": {"total": 1, "passed": 1},
  "contracts": {"task_spec_violations": 0},
  "resources": {"fuel_used": 88, "fuel_limit": 100000, "memory_units_used": 0, "memory_units_limit": 100000, "limit_hit": null},
  "breakdown": {"C": 1.0, "E": 1.0, "E_basis": "reference", "E_basis_reason": null, "ref_fuel": 88, "w": 0.1},
  "reward": 1.0,
  "infrastructure_error": null,
  "isolation": "none",
  "isolation_warning": null,
  "stdout": "",
  "replay": {"seed": 0, "source_hash": "sha256:424f33538027bb257be1ff798d1c5839b82cb1741c79752d2c503d940d3fe9d7", "task_hash": "sha256:6ee053ec7ef5f33b9767ee9e9539978f48ec5883b1825888efcb10cb24226098"},
  "crash": null
}
```

- `breakdown` is `C` (correctness), `E` (efficiency), `E_basis` (`"reference"`, `"declared"`, or `"limit"`), `E_basis_reason`, `ref_fuel`, and `w` (`efficiency_weight`). `E_basis_reason` is `null` on the reference basis. On the declared basis it is `"no_reference"` or `"reference_did_not_execute"`, and `ref_fuel` is the declared number. On the limit basis it is one of those two or `"reference_failed_hidden_tests"`, and `ref_fuel` is `null`. `reward` is `(1 − w) × C + w × C × E`. On an infrastructure error every breakdown field is `null` and `reward` is `null`. A process crash scores `0` with `C = 0` and `E = 0`, and lists every hidden test as failed. `tersa.result/0.2` added `breakdown` with `C`, `E`, and `w`. `tersa.result/0.3` adds `E_basis` and `ref_fuel`. `tersa.result/0.4` adds `E_basis_reason`. `tersa.result/0.5` adds `"declared"` to `E_basis`. `tersa.result/0.6` adds `isolation` and `isolation_warning`. `tersa.result/0.7` keeps that shape and scores a candidate OS memory kill, OS CPU kill, wall-clock stop, or unclassified child crash as reward 0 with `C = 0` and `E = 0` instead of a null discard. `tersa.result/0.8` makes every top-level field except `stdout` required, forbids unknown fields, and adds `crash.type` `"invalid_result"`. `tersa.result/0.9` adds `attempt_diagnostics`. `tersa.result/0.1` had `reward` only.
- `attempt_diagnostics` is how many of the leading `diagnostics` come from the attempt's own parse and check. The rest were raised while the attempt was checked together with the hidden tests or while they ran; `agent_view` withholds their detail (§22.5). It is never larger than the number of diagnostics. The combined check does not repeat the attempt's own warnings.
- `isolation` is the backend that actually ran: `"none"`, `"rlimit"`, or `"bwrap"`. An in-process run is `"none"`. `isolation_warning` is `null`, or a semicolon-separated list of stronger backends that were skipped (`gvisor is not available`, and so on). The field is deterministic for a given backend.
- `stage_reached` is `parse`, `check`, `run`, or `task` (`task` = the task itself failed while the attempt was being combined with it; an `I90xx` infrastructure error, reward `null`).
- `limit_hit` is `null`, `"fuel"`, `"memory"`, `"depth"`, or `"int"`. `fuel_used` is the sum over hidden tests; `memory_units_used` is the largest single test.
- `task_spec_violations` counts hidden tests that ended in a contract trap (`T61xx`).
- `crash` is `null`, or `{"type": "process", "message": "interpreter process exited N"}` when the child process died without a result (§22.6). `crash` is `null`, `{"type": "process", ...}`, or `{"type": "invalid_result", ...}` when the child's JSON fails `result.schema.json` or does not echo the attempt, task, and backend the parent sent. `tersa.result/0.8` adds `"invalid_result"`. Both crash types score 0 with `C = 0`.
- Keys are sorted and the JSON is UTF-8. `canonical_bytes` replaces `toolchain.python` and `toolchain.platform` with fixed strings so the same attempt can be compared byte for byte across operating systems. Reward, tests, diagnostics, and resource counts are deterministic for a fixed seed.
- **Seeds:** with `property_seed_policy = "per_episode"` the seed is the one passed to the run (`--seed`, default 0); with `"fixed"` it is `fixed_seed`.

### 22.4 Scored resource traps and infrastructure errors

**Scored resource traps (reward 0, exit 2).** These are the candidate's own failures. They are scored, never discarded: reward 0 with `C = 0` and `E = 0`, `infrastructure_error` null, and `tersa harness run` exits 2. They apply under every isolation backend, including `none`. Every hidden test is listed by its real name. A test that was running is trapped, tests that never started are failed, and the kill diagnostic is on the episode.
- **`T6206`** "OS memory limit exceeded": the candidate died from the address cap or a memory fault (`MemoryError`, `SIGKILL`, `SIGSEGV`, `SIGBUS`, `SIGABRT`).
- **`T6207`** "OS CPU limit exceeded": the OS CPU cap killed the candidate (`SIGXCPU`). A process-count cap stops new processes with an error; it is not this code.
- **`T6208`** "Wall-clock limit exceeded": the candidate hit its own clock. The message names it: `in-process wall-clock backstop reached (N ms)` or `child process wall-clock backstop reached (N s)`. The host cannot be told apart from a slow program, so this is scored 0 rather than discarded.

A child that exits without valid result JSON, and is not one of those OS kills, is also scored (RH-10): reward 0, `C = 0`, `E = 0`, a `crash` object, and every hidden test listed as failed. It has no trap code, so `tersa harness run` exits 0.

**Infrastructure errors (reward null, exit 4).** These are external faults or invalid inputs, not the program's own behavior. The episode is discarded: `reward` and every breakdown field are null, and the command exits 4.
- **`I9010`**: an invalid limit, from `task.toml` or a CLI flag, or a bad host grant (§12.3).
- **`I9013`**: a wall-clock backstop that is not the candidate's own failure: `tersa sandbox`, `tersa run`, and the reference solution while it is measured or validated. On the reference episode `tersa harness validate` fails its gate and exits 1. `tersa harness run` does not exit 4 there; it scores the candidate on the declared or limit basis with `E_basis_reason` `"reference_did_not_execute"`.
- **`I9014`–`I9022`**: other task-load failures. `I9017` is also the RL-mode refusal of an `--allow` for `FileRead`, `FileWrite`, `Net`, or `Python`.
- **`I9024`**: the requested isolation backend cannot be launched; the message names it.
- **`I9025`**: the reference solution does not match `interface.tersa` (§22.1); the task does not load.

`I9023` is reserved and is not emitted.

A crash of the interpreter *on a specific program* counts as a **failure** for that program and is filed as a bug: a child process that exits without valid result JSON scores **0** with a `crash` object. This stops agents from farming "discarded" outcomes (RH-10). OS memory and CPU kills and the candidate's own wall clock are scored traps too (`T6206`, `T6207`, `T6208`: reward 0, exit 2), not discards. The infrastructure-error rate is monitored per policy.

### 22.5 What the agent sees (`agent_view`)

The trainer gets the full result. The agent gets a filtered copy (`agent_view`, or `tersa harness run --agent-view`). `tests.cases` and `stdout` are removed. The first `attempt_diagnostics` diagnostics come from the attempt's own parse and check and keep full detail, because they describe only the attempt. Every later diagnostic was raised while the attempt was checked together with the hidden tests or while a hidden test ran, wherever its span points, so it can carry hidden inputs, expected values, or names (contract `values`, trap and `fail` messages, `related` spans, `old(...)` values). Each of those is reduced to its code (with its severity, category, and `docs_url`), one position, and the fixed message `raised while checking or running the hidden tests; details are withheld`. `related` is empty and `values`, `blame`, and `fix` are `null`. The position is the primary span when it is in public code (the attempt or `interface.tersa`), else the first public `related` span, else file `<hidden>` at line 1, column 1. An `infrastructure_error` keeps its code; its message becomes `infrastructure error; details are withheld`. Visible tests add no diagnostics to the episode: the agent has `visible_tests.tersa` and runs `tersa test` on it for full detail. The child's stderr is never copied into the episode, and `tersa harness validate` reports no diagnostics (it is a task-author tool, not part of the agent's view). Test counts, `visible_tests`, `resources`, the breakdown, the reward, and the replay hashes stay (the hashes don't reveal the hidden tests). In the agent's copy, `resources.fuel_used`, `resources.memory_units_used`, and `breakdown.ref_fuel` are rounded down to a power of two (0 stays 0), and `E` and `reward` are recomputed from the rounded numbers with the §22.3 formula; an `E` of 0 stays 0. The limits, `C`, and `w` stay exact, because they are task settings or follow from the test counts. The buckets are powers of two rather than two significant figures because an attempt can spend fuel or memory in proportion to a hidden input, so these numbers are a channel the attempt controls: a power-of-two bucket leaves 31 values up to 2³¹ (about 5 bits per number), where two significant figures leave 90 per decade, and it stays within a factor of two on the ratio scale `E` uses. The agent's `E` and `reward` are therefore approximate. The trainer's copy keeps the exact values, and training uses it. What still reaches the agent is bounded by the attempt's own choices: which code and which line fail, the test counts, and the rounded fuel and memory numbers (RH-20, RH-21).

### 22.6 Process isolation and crashes

`tersa harness run` runs each attempt in a fresh child process (`python -m tersalang.harness_worker`) with a 30-second timeout. A timeout is the candidate's own clock (`T6208`, reward 0, `C = 0`, `E = 0`). An empty or non-JSON child output scores 0 with `crash` set and `C = 0`, unless the OS killed the child: a memory kill is `T6206` and a CPU kill is `T6207`, both scored the same way. Each of those episodes lists every hidden test by its real name. Tests that never started are failed, and the kill or crash diagnostic is on the episode. A signal the harness does not attribute to those caps stays the RH-10 crash (reward 0, `C = 0`), because a null would let the candidate farm a discard. Child output that is JSON but fails `result.schema.json`, or does not echo the attempt, task, and backend the parent sent, is the same scored crash with `crash.type` `"invalid_result"` (§22.3). The parent process stays up. A reference killed by the wall clock during validation or measurement keeps `I9013` and a null reward on that reference episode. `tersa harness validate` exits 1. `tersa harness run` uses `E_basis_reason` `"reference_did_not_execute"`.

`--isolation` selects `none`, `rlimit`, `bwrap`, `nsjail`, or `gvisor`. Omit it and the harness uses the strongest backend that can launch, recording the skipped names in `isolation_warning`. `--in-process` does not start a child and records `isolation` `"none"`. `none` applies no OS caps. `rlimit` applies the layer-2 caps on Linux and macOS. `bwrap` is bubblewrap plus those caps. `nsjail` and `gvisor` fail the episode with `I9024` because this build does not launch them. On Windows the default is `none` with a warning, because job objects are unsupported.

The harness child inherits only an allowlist of environment variables on every OS (`PATH`, `SYSTEMROOT`, `WINDIR`, `TEMP`, `TMP`, and fixed Python settings). Under bubblewrap the root is empty and read-only except for the Python install, the `tersalang` package, the shared libraries, `/etc/ld.so.cache`, the task directory, and the attempt.

### 22.7 Task validation (`tersa harness validate`)

The reference solution must execute and pass every hidden test (`C = 1`, `passed = total`, at least one hidden test) with no infrastructure error. The validator then makes AST mutants of the reference bodies, and a mutant survives when its correctness is still 1, so a correct but less efficient mutant survives (and fails validation) even though its reward is lower. The reported `reference_reward` is the formula in §22.2. The reference matches its own fuel, including when that fuel is 0, so a correct reference has `E = 1` and reward 1. A `reference_fuel` value that does not match that run fails validation. A reference that fails hidden tests is not the efficiency yardstick. Each mutant is one edit inside a function, test, or `implements` body (contracts are never mutated): an operator swap (`+`↔`-`, `*`↔`/`, `div`↔`mod`, `==`↔`!=`, `<`↔`>`, `<=`↔`>=`, `and`↔`or`), a literal tweak (an `Int` becomes `0`, or `1` if it was `0`; a `Float` becomes `0.0` or `1.0`; a `Bool` is flipped), removing a `not` or a unary minus, or replacing a returned value with a literal of the function's **declared return type**: `Int` → `0` (or `1` if it was `0`), `Bool` → the other of `true`/`false`, `Float` → `0.0` (or `1.0` if it was `0.0`), `Text` → `""` (or `"mut"` if it was `""`). Other return types, including `Unit`, and returns inside `test` blocks get no return mutant.

**Sampling.** Sites are grouped by kind of edit (each operator swap direction such as `+`→`-` is its own kind; integer, boolean, and float literals, return replacements, `not` removal, and unary-minus removal are one kind each). Within a kind, the sites are visited in a spread order whose start and step come from the SHA-256 hash of the reference source (the step is made coprime with the number of sites, so each site is visited once). The kinds are then drawn **round-robin**, one site per kind per round, so a late site isn't dropped just because sixteen earlier ones came first. Drawing stops at **16 well-typed mutants** or when the sites run out. A mutant that repeats an earlier text, or that doesn't parse or type-check in RL mode, is **skipped and not counted**: it is neither killed nor surviving and doesn't use up the cap. The order depends only on the source text, so validation is reproducible. A task fails validation if the reference does not execute and pass every hidden test, or if any mutant's correctness is still 1. If no mutant can be made, the report's `warnings` says `no mutant could be generated` and the task is not failed for that alone (it is valid if the reference passes every hidden test). Output is `{ok, reference_reward, mutants: [{name, reward, survived}], warnings}`; exit code 0 or 1. Human review of task specs is still required (RH-17).

### 22.8 The sandbox (`tersa sandbox`)

`tersa sandbox FILE` runs one program's `main` in RL mode under host-set limits (§12.6, §18.4): no `foreign`, no transcendental math, and only the effects passed with `--allow`. If `main` declares an effect that was not granted, the run is refused before it starts (`E4010`). A call that actually runs without its grant, including inside a test, traps `T6302`. Fuel, memory units, output, and the wall clock start at finite defaults (100,000 fuel, 100,000 memory units, 1,048,576 output bytes, 5,000 ms) and each flag overrides its own default. Reaching the wall clock is `I9013` and exit code 4. `tersa sandbox` stays in-process. The OS caps and bubblewrap apply to `tersa harness run`, not to `tersa sandbox`.

---

## 23. Reward-Hacking Catalog

Every entry has a test in `conformance/reward_hacking/`, `tests/unit/test_harness.py`, or `tests/unit/test_isolation.py` that shows the exploit fails. The catalog grows after each red-team round. "Implemented defense" is what the build does at the code baseline; RH-09 is the isolation work in §20.3.

| ID | Exploit | Mitigation | Implemented defense |
| :-- | :-- | :-- | :-- |
| RH-01 | Read, modify, or import the hidden tests | Hidden tests live in a separate harness package, run in a separate process, and are never in the agent workspace. No `FileRead` in RL mode | Hidden files are never in the agent's files (`public_task_files`). A task can't grant `FileRead`; reading a file traps `T6302` and the test fails. Each attempt runs in a child process. Hidden code is renamed `name@hidden`, so an attempt can't reach or redefine a hidden helper (§22.1). |
| RH-02 | Hard-code the expected outputs for known inputs | Hidden and seeded randomized inputs, property tests, and held-out test instances | Hidden example tests plus property tests (`for all`). An attempt hard-coded to the visible example passes `visible_tests` but scores 0 |
| RH-03 | Print "PASS" or fake the test output | Reward comes only from the structured result (§22.3), never stdout | Reward is computed from test outcomes only. `stdout` is kept for the trainer and removed from the agent's view |
| RH-04 | Exit early with a "success" status | Exit codes are ignored. Tests with no result count as failed | `main` is dropped from the scored module, so exit status can't matter. Unrun tests count as failed, and zero hidden tests score 0 |
| RH-05 | Override equality so that every comparison passes | Users cannot implement `Equatable` (§8.6) | `implements Equatable` is a check failure (`E3041`); the attempt stops at `stage_reached = "check"` |
| RH-06 | Weaken own contracts (`ensures true`) | Model contracts never add reward. Task specs are fixed | Interface contracts replace the attempt's own contracts on every function the interface names (§22.1), so `ensures true` there has no effect. Helpers the interface doesn't name keep their own contracts. A violation is counted in `task_spec_violations` and fails the test |
| RH-07 | Catch failures or traps | Traps cannot be caught in v1 (§10.1) | A trap ends only that test, which is reported as `trapped` and doesn't pass |
| RH-08 | Exhaust resources to trigger a "timeout" that gets discarded | Fuel and memory exhaustion are deterministic **failures**. Only external faults are discarded | Fuel, memory, depth, and integer-cap traps are scored failures with `limit_hit` set and `infrastructure_error` null. `fuel` and `memory_units` are required in every task |
| RH-09 | Escape the sandbox | Layered isolation (§20.3) | Layer 1 on every platform. Layer 2 (`setrlimit`: memory, CPU, file size, open files, no core dumps, process count) on Linux and macOS. Bubblewrap on Linux when installed (no network, read-only root, tmpfs workspace, separate PID namespace, dropped capabilities). A memory bomb scores `T6206` and a CPU bomb scores `T6207`, both reward 0 with `C = 0`. macOS runs the CPU bomb but skips the memory bomb (the host doesn't enforce the address cap); Windows skips both. A fork bomb stops. A file write past the size cap is refused. Under bubblewrap, a network connect fails, writes to the repo and `/etc` fail on the read-only root, and a write to the tmpfs workspace succeeds without reaching the host. Tests: memory bomb, fork bomb, CPU bomb, oversize file, network, read-only writes, tmpfs. Tests skip where the backend is not installed. nsjail and gVisor are not launched (`I9024`). Windows has no OS cap in this build |
| RH-10 | Crash the interpreter to get an infrastructure-error discard | A program-induced interpreter crash = failure (§22.4) | A child that exits without result JSON scores 0 with a `crash` object and `C = 0`, not an infrastructure error (§22.6). An OS memory kill (`T6206`), an OS CPU kill (`T6207`), and the candidate's own wall clock (`T6208`) also score 0 with `C = 0` and `E = 0`. Each lists every hidden test by name and marks tests that never started as failed. A self-signal under backend `none` scores 0 too. A reference stopped during validation fails the gate (exit 1). A candidate run uses `E_basis_reason` `"reference_did_not_execute"`. Child output that fails the result schema or doesn't echo the attempt, task, and backend is the same scored crash (`crash.type` `"invalid_result"`). |
| RH-11 | Exploit nondeterminism (resample until lucky) | The determinism contract (§12.4). Reruns give identical rewards | Same seed gives the same reward and identical `canonical_bytes`, across operating systems |
| RH-12 | Leak state between tests, or depend on test order | Fresh state per test (§21.3) | Each hidden test gets a fresh interpreter with the same seed, so even random state doesn't carry over |
| RH-13 | Smuggle in a malicious dependency | RL mode only allows the task-provided or vetted dependencies listed in the task | An import of a user module the harness can't load is a check failure (`E2000`); in practice only `std.*` modules can be imported |
| RH-14 | Prompt-inject an LLM judge via output | No LLM judges in the reward in v1. If ever added, judge outputs are capped and audited | No judge exists. Output never reaches the reward or the agent's view |
| RH-15 | Exploit float tolerance | The tolerance is explicit per assertion (`std.testing.approx(a, b, tolerance)`) and set by the task | The tolerance is written in the hidden test by the task author; the attempt can't change it |
| RH-16 | Overfit to visible tests | Hidden tests come from the same distribution plus property tests. Track the gap between visible and hidden pass rates | `visible_tests` is reported separately from the reward, so the visible/hidden gap can be tracked. Hidden test names and inputs never reach the agent's view |
| RH-17 | Pass with trivial solutions because the tests are weak | Task validation: mutation testing against the reference solution (§21.4) and human review of task specs | `tersa harness validate` (§22.7): up to 16 well-typed AST mutants, sampled round-robin across edit kinds, must not stay fully correct (correctness below 1); ill-typed mutants are skipped rather than counted as killed. A reference with no mutable site only gets a warning, so human review of task specs is still required |
| RH-18 | Use `foreign`/Python to reach the host | `foreign` is rejected at load time in RL mode | `foreign` is a check failure in RL mode (`E4012`), and a task can't grant `Python` |
| RH-19 | Burn compute with huge integers (for example `pow(2, 10000000)`) so that wall-clock backstops fire | Integer-size cap (`T6204`) checked before computing where possible, size-proportional fuel, and memory units. All are deterministic failures | `pow(2, 10000000)` traps `T6204` before computing: a scored failure with `limit_hit = "int"` and no infrastructure error |
| RH-20 | Recover hidden inputs, expected values, or test names from what the agent sees: deliberately failing contracts, `old(...)` values, `fail` messages, trap text, prints | Diagnostics raised with hidden code in scope reach the agent without their detail (§22.5) | `agent_view` keeps full detail only for the attempt's own parse and check diagnostics (`attempt_diagnostics`). Every later one keeps its code, one public position, and a generic message, with no `values`, `related`, `blame`, or `fix`; stdout, cases, and infrastructure messages are withheld. The attack test leaks a hidden input through the attempt's own `requires`, an `ensures` with `old(...)`, the interface `ensures`, a `fail` message, a slice trap, `print`, and the hidden `expect`, and also breaks the combined check: the input, the expected value, and the hidden test names are in the trainer's copy and in none of the agent's, in process or through `tersa harness run --agent-view` |
| RH-21 | Read a hidden input from the resource numbers: spend fuel or memory in proportion to it, then read the exact count, `E`, or the reward | The agent sees fuel and memory only in power-of-two buckets (§22.5) | `agent_view` rounds `fuel_used`, `memory_units_used`, and `ref_fuel` down to a power of two and recomputes `E` and `reward` from them; the limits, `C`, and `w` stay exact. The attack test builds a list as long as the hidden input: inputs 4173 and 4174 give different exact numbers in the trainer's copy and identical agent views, under the reference and the limit basis, in process and through `tersa harness run --agent-view` |

---

## 24. Grammar-Constrained Decoding

- **Profiles:**
  1. **Full grammar:** everything the parser accepts, except two spellings with no space between a bracket or digit and a word (`(a)and b`, `7mod 2`) and comments over the caps (500 characters; 100 comment lines in the opening header, 30 in a row after code). Keywords are reserved, names follow the lexer, and the layout follows the lexer.
  2. **Decoding profile:** the full grammar with stricter separators and the formatter's blank-line rule. It rejects tabs, CR, runs of spaces, a blank line at the start of the file, and more than one blank line in a row. It does not enforce operator, comma, or bracket spacing, which allowed line break is used, indentation depth, whether one blank line or none separates declarations, import order, `W1103` parentheses, or the 100-column limit, so run `tersa fmt` on constrained output.
- **Exports** (generated by `tersa grammar` and checked in CI):
  - **Lark** (used by Outlines and by the reference grammar test).
  - **GBNF** (llama.cpp grammars).
  - A plain EBNF/regex-friendly form usable by tools such as XGrammar and llguidance.
- **Lexical constraints** (identifier classes, literal forms, `NL` handling) are expressed directly in the exported grammars. Because indentation isn't significant, no external state is needed.
- **Evaluation:** compare compile rate and pass@1 with and without constraints on the benchmark suite (§26).
- **Later:** type-aware constrained decoding, which only allows tokens that keep the program well-typed. It is deferred because it needs an incremental checker. Sketch: expose the checker's incremental scope and type state through an API that a decoding loop can query per candidate token.

**As built (`spec/tersa.gbnf`).** The GBNF file is **generated from `spec/tersa.lark`**, which is the single source; it is never edited by hand. `tersa grammar --format gbnf [--profile full|decoding]` prints a fresh generation (the committed file is the `full` profile). `--format ebnf` and `--format lark` print the committed spec files; the default is `ebnf`. `--kind` is a hidden, deprecated alias for `--format` (`--format` wins if both are given).

- **Standard llama.cpp GBNF.** Only literals, character classes, sequences, ordered choice, `?` `*` `+`, and bounded repetition `{m,n}`; **no lookahead**. Ordered choice tries the longer alternative first (`FLOAT` before `INT`, constructor patterns before bare identifiers, a named argument `name = expr` before a positional expression).
- **Keywords are reserved in both profiles.** `lower` is `[a-z][a-z0-9_]*` minus the 57 keywords, written out as a trie of rules because GBNF has no lookahead. A keyword can't be a name, and it can't run into the next word: `functions` is a name, never `function s`.
- **Names follow the lexer in both profiles.** A lower name has no `__`, no trailing `_`, and no leading `_` (`E0010`); an Upper name has no `_` (`E0011`); a name is at most 64 characters (`E0012`). Every case of those codes is encoded.
- **Layout follows the lexer.** Every statement and declaration ends in `nl`, the lexer's NL token (the end of a line, plus any blank or comment lines after it). Outside brackets a gap stays on the line. A line break may go inside `(` `[` `{` and after a continuation token (`+`, `,`, `=`, `and`, …); a lambda body counts as outside. A word after a word needs a space. Where a rule can end in either a name or a bracket, the grammar asks for the space, so `(a)and b` and `7mod 2` don't match even though the lexer splits them.
- **Literals match the lexer.** Floats are the dotted form (`1.0`, `1.0e10`, `1.0e-2`) or **exponent-only** (`1e10`, `1e+2`), lowercase `e` only. Text literals accept the **full escape list**: `\"`, `\\`, `\n`, `\t`, `\r`, `\{`, `\}`, and `\u{` + 1 to 6 hex digits + `}`. A raw newline or CR, or an unknown escape, doesn't match.
- **`full` profile:** accepts every layout the hand parser accepts except those two spellings. Like the parser, it rejects `do`, `uses`, `requires`, or `ensures` on the header line, two statements on a line, and a line break where the lexer would end the statement. Comments are capped as in `decoding` (500 characters; 100 full-line comments before the file's first token, 30 between two lines of code); blank lines aren't. The last line may lack a line break.
- **`decoding` profile: stricter separators.** A gap is empty or one space, plus one line break and its indent where `full` allows one. A line break is LF, an optional `  #` trailing comment (two spaces), **at most 30** full-line `#` comments with **at most one blank line in a row** (the formatter's rule), and an indent made of pairs of spaces. A comment is **at most 500 characters** from its `#`. No blank line may open the file, and at most 100 `#` banner lines may. Tabs, CR, and runs of spaces don't match. Every `tersa fmt` result in the corpus is accepted, except the three `# fmt: skip` files, which are exempt (§18.2.1).
- **Limits of the decoding profile** (`tersa fmt --check` remains the gate for these): the 100-column limit; **which gap must be a space and which must be empty** (`function(Int)` and `function (x: Int)` are both canonical, so that gap allows either); which of the allowed line breaks the formatter uses; indentation depth; whether one blank line or none separates declarations; import order; the `W1103` parentheses; and, in number literals, leading zeros, `__`, a trailing `_`, and out-of-range integers (the lexer reports those). **The comment caps are the one place a formatted file can fail:** `tersa fmt` keeps comments as written, so no finite cap accepts every formatted file, and a comment over 500 characters, an opening header of more than 100 comment lines, or more than 30 comment lines in a row after code is valid code that both profiles reject. The caps exist so a model can't loop in a comment; the header allowance is for license headers, and both sit far above the corpus (87 characters, 7 lines).
- **How it is checked.** CI runs `scripts/check_gbnf.py`, which fails if the committed file drifts from a fresh generation or contains `(!`. The unit tests load the file with `tersalang.gbnf.llama_gbnf_accepts`, a development recognizer that accepts a string when any derivation consumes it, as llama.cpp keeps every grammar stack. The `gbnf-llama` CI job builds llama.cpp's `test-gbnf-validator` from a pinned commit and runs `scripts/check_gbnf_llama.py`: every corpus program the parser accepts matches `full`, every `tersa fmt` result matches `decoding`, and llama.cpp gives the required verdict on each side of every comment cap and agrees with the recognizer on every corpus input and broken variant (755 for `full`, 913 for `decoding`; slowest 0.63 s). Neither `tersa check` nor `tersa run` depends on the recognizer, and nothing calls a paid service or downloads a model.
- **Run in llama.cpp.** Results at the code baseline, with llama.cpp pinned at commit `31288c9`, are in the table below. Four inputs over 4,096 characters aren't compared. A left-factored grammar keeps parsing fast; the slowest input takes 0.63 s.

**GBNF acceptance in llama.cpp** (llama.cpp's own validator):

| Profile | Comment-cap cases | Valid programs accepted | Agrees with our recognizer | Broken variants rejected |
| :-- | :-- | :-- | :-- | :-- |
| `full` | 11/11 | 161/161 | 755/755 | 517 |
| `decoding` | 11/11 | 158/158 | 913/913 | 536 |

The 11 cap cases sit on each side of each cap: the 100-line header, 30 lines after code, a 30-line run between declarations, and 499 versus 500 characters.

---

## 25. Tokenizer-Efficiency Measurement Method

**Question:** does word-based syntax cost more or fewer tokens than symbols, and does it change generation accuracy? Accuracy is the primary metric. Token count is secondary.

1. **Corpus:** a parallel set of solutions to the same tasks (from the benchmark port, §26), in canonical Tersalang and in formatted Python (for example via Ruff's or Black's formatter). Measured with comments stripped and with comments kept.
2. **Tokenizers:**
   - OpenAI's `tiktoken` encodings (for example `cl100k_base` and `o200k_base`).
   - Several open-weights model tokenizers loaded through Hugging Face `tokenizers`/`transformers`, with families chosen at measurement time and recorded.
3. **Measures:**
   - Total tokens per solution (median and distribution).
   - Tokens per non-blank line.
   - A **per-keyword cost table:** tokens for each keyword at line start and after a space.
   - A **variant table** for contested choices: `returns` vs. `->`, `do…end` vs. braces vs. indentation, `and/or/not` vs. `&&/||/!`, `div/mod` vs. `//`/`%`, plain `end` vs. labeled `end function`.
4. **Accuracy A/B:** for each contested choice, generate syntax variants of the compact reference and examples. Prompt the same models in-context on the same tasks, and compare L1 check rate and pass@1.
5. **Decision rule:** a keyword or syntax change is adopted only if it improves accuracy, or matches accuracy at materially lower token cost. The "material" threshold is recorded before the results are seen, to avoid bias.
6. **Freeze:** the keyword list, `returns`, and plain `end` are **decided now** for language 0.1 (§5.3). This study still runs in Roadmap phase 4, but its results can change syntax only through a TEP that meets the decision rule above.

---

## 26. Benchmarks and Evaluation Plan

### 26.1 Suites

| Suite | Content | Purpose |
| :-- | :-- | :-- |
| **Tersalang-HumanEval / Tersalang-MBPP** | Ported prompts and tests following the MultiPL-E approach (which translated these benchmarks into many languages) | Comparable to existing results for other languages |
| **Tersalang-RL tasks** | Native tasks in the §22.1 format, with task specs and hidden tests | Measures RL suitability |
| **Tersalang-Repair** | Broken programs plus diagnostics. The goal is a fix within k attempts | Measures diagnostic quality |
| **Held-out split** | Never used for training, prompt tuning, or examples | Honest final numbers |

### 26.2 Metrics

L1 check rate (first attempt), pass@1 and pass@k (computed with the unbiased estimator from the Codex paper, Chen et al. 2021), repair iterations to pass, tokens per solution, check latency, rerun reward variance (must be 0), reward-hacking incidents per red-team round, and human review time.

### 26.3 Protocol

- Fixed prompt templates, including the compact reference (§29.3), versioned in the repo.
- Models: a mix of API and open-weights models, with exact versions recorded.
- Sampling settings recorded (greedy for pass@1, or a stated temperature with n samples for pass@k).
- **The same tasks in Python** as the baseline, with identical prompts minus the language reference.
- **Contamination controls:** benchmark files carry a canary string (a unique identifier, as BIG-bench did) so later training contamination can be detected. Hidden tests are never published in plain text. Only their hashes are published.
- Results are published with the harness version, prompts, and raw per-task outcomes.

---

## 27. Training-Data Pipeline

The biggest challenge: models have seen almost no Tersalang code. In order of cost:
1. **In-context reference** (cheapest, no training).
2. **Grammar-constrained decoding** (§24).
3. **Translation:** Python and other code translated into Tersalang, keeping only versions that pass checks and differential tests.
4. **Synthetic tasks** with specs and tests.
5. **Self-play with RL,** scored by the harness.
6. **Fine-tuning** an open-weights model.

### 27.1 Stages

1. **Source:** permissively licensed code and tasks with tests. Record the license and origin per item.
2. **Translate:** LLM-assisted plus rule-based passes.
3. **Format** with `tersa fmt` (the canonical form).
4. **Check** at L0–L2.
5. **Differential test:** the translated program must match the source program's behavior on the source tests plus generated inputs.
6. **Dedupe:** exact matches (hash) and near duplicates (for example MinHash over tokens).
7. **Decontaminate** against every benchmark split (§26): n-gram overlap checks plus canary-string checks.
8. **Tag** with language version, toolchain version, license, and provenance.
9. **Split and version** the dataset alongside the language version, and publish it with a dataset card.

**Dataset licensing is DEFERRED** (§32). It is decided before the first dataset release, because it depends on the licenses of the sources actually used. Every record keeps its upstream license (§27.2) so the decision can be made later.

### 27.2 Record schema (JSONL)

```json
{"id": "tersa-ex-000001", "language": "0.1", "toolchain": "0.1.0a1",
 "source": {"origin": "translated", "upstream": "<repo or dataset>", "license": "MIT", "upstream_hash": "sha256:..."},
 "task": {"prompt": "...", "interface": "...", "visible_tests": "..."},
 "code": "module ...", "check_level": "L2",
 "diff_test": {"cases": 50, "agree": 50}, "split": "train", "canary_clean": true}
```

---
# Part V: Specification Process and Project Governance

## 28. Specification Formality and Conformance Suite

### 28.1 Layers

| Layer | Form | Status |
| :-- | :-- | :-- |
| Syntax | Normative EBNF (§7), plus a Lark grammar validated in CI and generated GBNF | Draft |
| Static semantics | Prose with RFC 2119 wording, plus typing rules in inference-rule notation (§8.9) | Partial; complete for the core alongside the checker |
| Dynamic semantics | Prose, plus the **reference interpreter as the executable definition** | Written alongside the interpreter |
| Conformance | A test suite with expected outputs and diagnostics | Grows with every feature |
| Mechanized semantics | For example in Lean or the K framework. Precedents for formal definitions: *The Definition of Standard ML* and the WebAssembly spec | Deferred until after 1.0 (reason: the core must stop changing first) |

### 28.2 Specification document outline

Modeled on the chapter structure of the JLS and the Python Language Reference:
1. Introduction and notation
2. Lexical structure
3. Types and values
4. Names, modules, and packages
5. Declarations
6. Statements
7. Expressions
8. Contracts and invariants
9. Effects and capabilities
10. Errors and traps
11. Execution, limits, and determinism
12. Standard library (normative signatures and contracts)

Annex A: Grammar. Annex B: Diagnostic catalog. Annex C: Fuel and memory-unit tables. Annex D: Pinned Unicode version.

### 28.3 Stable paragraph IDs

Every normative paragraph gets a stable ID (for example `[lex.ident.2]`, `[expr.try.1]`), following the C++ standard's practice of stable section names such as `[basic.life]`. Conformance tests cite the IDs they cover. CI reports which IDs have no test.

### 28.4 Conformance suite format

```
conformance/
  lex/ident_ok_01.tersa
  lex/ident_bad_double_underscore.tersa
  types/match_not_exhaustive.tersa
  runtime/int64_overflow_traps.tersa
  runtime/int_size_cap_traps.tersa
  determinism/map_order.tersa
  reward_hacking/rh05_equality_override.tersa
```

Each case starts with a header comment naming its spec IDs and its expectation. For example:

```
# spec: [types.match.exhaustive.1]
# expect: check-error E3030 at 7:3
```

Other expectations are `run-output <file>`, `trap T6001`, and `harness-result <file.json>`. The runner compares the JSON output exactly.

### 28.5 Rules

- If the prose and the interpreter disagree, one of them has a bug. Decide which, fix it, and add a conformance test.
- No undefined behavior (Principle 9).
- Every spec change goes through a TEP (§31) and updates the conformance suite in the same change.

---

## 29. Documentation

### 29.1 Doc comments

`##` lines attach to the next declaration. Supported sections, each starting a line:
- Free text (the summary is the first sentence).
- `Example:` followed by an expression that must evaluate to `true` (it runs as a test).
- `Param name:` and `Returns:`.
- `Errors:` (for `Result`-returning functions).
- `Complexity:` (required for the stdlib).

### 29.2 Generated docs

`tersa doc` produces HTML or Markdown API docs from signatures, contracts, effects, and doc comments. The docs site is versioned per language version.

### 29.3 LLM-facing compact reference

A single Markdown file sized to fit easily in a prompt. It covers the keywords, the grammar summary, core types and their rules, the top diagnostics with fixes, and 10–20 canonical examples. Published with each language version, and used for in-context evaluation (§26). An `llms.txt` file on the docs site points to it.

### 29.4 Documentation set

Getting Started, Syntax Guide (with the word-based rationale), the Language Specification (§28), the Standard Library reference, the Diagnostics reference (one page per code), the RL Harness guide, the Contributing guide, and the TEP index.

---

## 30. Versioning, Editions, and Deprecation

| Thing | Scheme |
| :-- | :-- |
| **Language version** | `MAJOR.MINOR` (for example `0.1`). Declared per package in `tersa.toml`. Defines grammar, semantics, stdlib signatures, fuel tables, and the Unicode version |
| **Toolchain version** | Semantic versioning, `MAJOR.MINOR.PATCH`, written in PEP 440 form on PyPI (for example `0.1.0a1`). One toolchain supports a documented range of language versions |
| **Schema versions** | `tersa.diagnostic/x.y` and `tersa.result/x.y`, versioned separately. Additive changes bump the minor version |
| **Design doc version** | Independent of the above (this document is v0.6.0) |

### 30.1 Before 1.0 (unstable)

- Any language version can make breaking changes.
- Each change is listed in the changelog with a migration note.
- **Deprecation:** a feature is deprecated with a warning code for at least one language minor version before it is removed, where practical.
- `tersa migrate` provides automatic rewrites when possible.
- **CLI deprecations are not language diagnostics.** A deprecated `tersa` flag or option, such as `tersa grammar --kind`, prints a plain one-line warning on stderr (``warning: `--kind` is deprecated; use `--format` ``) and gets no `W` code: it is not in `diagnostics.yaml`, is never emitted as a diagnostic object, and does not change the exit code. Warning codes are for source programs.

### 30.2 From 1.0 (stable)

- Breaking changes happen only through **editions** declared in the manifest, following Rust's edition model. Old editions keep compiling with the new toolchain, and packages of different editions interoperate.
- Deprecations warn in the current edition and are removed only in a later edition. `tersa migrate --edition N` performs the upgrade.
- Patch releases MUST NOT change program behavior except to fix bugs against the spec.

### 30.3 Training-data impact

All datasets, benchmarks, and prompts are tagged with the language version (§27), so models never train on unlabeled mixed syntax.

---

## 31. Governance and the Proposal Process

- **Initial model:** one maintainer leads the project with final say, similar to Python's original "BDFL" model before its Steering Council (PEP 13) took over in 2019.
- **Later:** once there are several active maintainers, move to a small elected or appointed steering group with written rules. This is deferred because a single maintainer makes it moot today.
- **TEP (Tersalang Enhancement Proposal) process**, modeled on PEPs:
  - **When needed:** any change to the language, stdlib API, diagnostic or result schemas, the reward rules, or governance itself. Bug fixes against the spec don't need one.
  - **Template:** Summary, Motivation, Specification (with grammar and conformance test changes), Effect on LLM generation (expected effect on tokens and accuracy, and how it will be measured), Effect on RL and determinism, Backwards compatibility and migration, Alternatives, Open issues.
  - **States:** Draft → Review → Accepted / Rejected / Withdrawn → Final (implemented and in the spec).
  - **Location:** a `teps/` directory in the main repo.
- **Contributor terms:** Developer Certificate of Origin (DCO) sign-off on commits. **Code of Conduct:** Contributor Covenant. **Security policy:** `SECURITY.md`.

---

## 32. Licensing and Name

**Licenses:**

| Component | License | Why |
| :-- | :-- | :-- |
| Code: interpreter, checker, stdlib, CLI, LSP, harness, grammars, examples | **Apache-2.0** | Wide adoption, an explicit patent grant, enterprise-friendly, and compatible with the permissive-license filters used by code datasets |
| Specification and docs | **CC BY 4.0** | Free reuse with attribution |
| Datasets | **DEFERRED** | Depends on the licenses of the sources used. Decided before the first dataset release (§27) |
| Benchmark hidden tests | Not published (hashes only) | Benchmark integrity |

- **Repository:** https://github.com/kevindm-design/tersalang (default branch `main`). `LICENSE` holds the Apache-2.0 text and `LICENSE-docs` the CC BY 4.0 text; `NOTICE` says which files each covers.
- **Name: Tersalang** ("terse language"), formerly AIOWL. CLI `tersa`, extension `.tersa`, Python package `tersalang`.

---

# Part VI: Context, Decisions, and Plan

## 33. Prior Art to Study

- **Mojo:** a Python-like language aimed at fast AI code.
- **Triton:** a language and compiler for writing GPU kernels.
- **DSPy and LMQL:** frameworks for programming *with* LLMs. This is a different problem from Tersalang's (a language *for* LLMs to write), but relevant for tooling.
- **Dafny and Lean:** programs with machine-checked specs and proofs.
- **Eiffel and Ada/SPARK:** design by contract and static verification.
- **Koka:** effect types and Perceus reference counting.
- **Rust:** strict compiler, helpful errors, editions, `Result` and `?`, and the orphan rule.
- **Elm:** a friendly compiler error style.
- **Go:** minimal syntax and `gofmt`.
- **Unison:** content-addressed code.
- **Standard ML** (*The Definition of Standard ML*) and the **K framework:** formal language definitions.
- **WebAssembly, WASI, and the Component Model:** a sandboxed target with capability-style host interfaces.
- **Hypothesis and QuickCheck:** property-based testing with shrinking.
- **Constrained decoding tools:** Outlines, XGrammar, llguidance, and llama.cpp grammars (GBNF).
- **Code benchmarks:** HumanEval, MBPP, and MultiPL-E.

---

## 34. Known Limitations

These are not built yet. The rest of this document describes the code as it is.

- **Agent view:** the agent can still see which code and which line fail, and the test counts (§22.5).
- **GBNF:** the `full` profile allows unlimited trailing blank lines, like `tersa check`. A comment over 500 characters, an opening header of more than 100 comment lines, or more than 30 comment lines in a row after code is valid code that both profiles reject, because `tersa fmt` never wraps or merges comments. The number-literal lexer rules (leading zeros, `__`, a trailing `_`, out-of-range integers) aren't encoded (§24).
- **Diagnostic examples:** not every code in `docs/diagnostics.md` has both a wrong and a fixed example.
- **Not implemented:** `E2101` (nothing reads `tersa.lock`) and `I9011` (no Unicode version is pinned).
- **Isolation:** macOS doesn't enforce the address cap, so its memory-bomb test is skipped. Windows job objects are unsupported. nsjail has no launcher, gVisor is not launched, no seccomp profile is applied, and the sandbox doesn't create a separate host account (§20.3).

---

## 35. Resolved Design Questions

Each question below was resolved with the most explicit option that has the fewest special cases, or the most conservative option. Each can change later only through a TEP (§31).

### 35.1 Former prototype questions

| Question | Decision |
| :-- | :-- |
| Final keyword list, `returns` vs. `->`, plain vs. labeled `end` | Keep the §5.3 keyword list, `returns`, and plain `end`. The tokenizer study (§25) can propose changes only by TEP |
| Text interpolation syntax | **Not in v1.** Build text with `concat` or `+`. `\{` and `\}` stay reserved |
| Multi-line text literal | **Not in v1.** Use `\n` escapes or `Text.join_lines` |
| `if` as an expression | **Not in v1.** `if` is a statement only |
| Keep both `get` (Option) and `at` (trap) on lists | **Keep both** (§9.6) |
| Transcendental math in RL mode | **Unavailable** in RL mode (`E4011`). Platform math library in dev, test, and host modes (§9.2) |
| Default reward weights | `check_credit = 0.0` and `efficiency_weight = 0.1` (§22.2) |
| Wasm memory strategy | Reference counting (§11.6) |
| Fixed-width set and default integer cap | Only `Int64`. Default cap 65,536 bits (§9.1, §9.1a) |
| File extension | `.tersa` (§6.1) |

### 35.2 Former Language Reference items to confirm

| # | Item | Decision |
| :-- | :-- | :-- |
| 1 | `do` placement | `do` always on its own line. No same-line form (§7.4, §18.2) |
| 2 | Shadowing | Not allowed. Re-declaring a name in scope is `E2020` (§7.4) |
| 3 | Top-level order | Order doesn't matter. Duplicate top-level names are `E2021`. Constant cycles are `E2003` (§7.4, §14.1) |
| 4 | Ordering operators | `< <= > >=` only on `Int`, `Int64`, `Float`, `Text`. Others use `compare` (§8.6) |
| 5 | `Float` inside records | IEEE equality; a record holding NaN isn't equal to itself and isn't `Hashable` (§8.6) |
| 6 | Iteration helpers | `keys()` and `entries()` (`Entry` record) on maps; `for` over List, Set, and MutableList (snapshot); `List.range` end-exclusive (§9.6) |
| 7 | Stdlib names | `length`, `is_empty`, `show`, `MutableList.new`, `MutableMap.new`, `push`, `Set.from_list`, `entries`, `contains` confirmed. Immutable changes are `with_…`/`without_…` (`Map.with_entry`); only mutable collections have `insert`/`remove`/`push`/`set_at` (§9.6, §15) |
| 8 | `set r.field = v` | Allowed only when `r` is a `var` (`E2030` otherwise). Means `set r = r with (field = v)`, nesting included (§7.4) |
| 9 | Standalone files | Module name = file name; must match the `module` line (`E2001`); may import only `std.*` (§14.1) |
| 10 | Import qualifier | Last path segment. Clashes are `E2004`; fix with `as` (§14.1) |
| 11 | Missing codes | `fail` = `T6030`, failed `expect` = `T6031`, unnamed record arguments = `E3080`/`E3081`/`E3082`, shadowing = `E2020` |
| 12 | Diagnostic details | Human layout, `values`, and `blame` defined in §18.1 (`"constructor"` covers invariants on construction and `with`) |
| 13 | Property-test generators | All built-in types except functions, resources, and mutable collections, plus records and choices built from them; default 100 cases (§21.3) |
| 14 | Bitwise operators | None in v1: no operators and no `std.math` functions (§6.8, §15) |
| 15 | `main`'s `Error` | `error: ` + `show(e)` to stderr, exit 1 (§17.3) |
| 16 | Integer details | Cap in bits, default 65,536; only `Int64`; literals are always `Int` (`E3023` where `Int64` is expected); mixing is `E3024`; `Int`→`Float` overflow traps `T6003`; codes `T6204`, `E3023`, `E3024`, `T6402` confirmed; no wrapping or saturating functions (§9.1, §9.1a, §9.2) |

---

## 36. Roadmap (draft; relative phases, no dates)

| Phase | Goal | Output | Exit criteria |
| :-- | :-- | :-- | :-- |
| 0 | Vision and principles | v0.1 (done) | — |
| 1 | Freeze the tiny-core spec for language 0.1-draft | Validated Lark grammar, typing rules for the core, diagnostic catalog v0.1 (`spec/diagnostics.yaml`), fuel and memory tables v0.1 | Grammar conflict-free in CI |
| 2 | Python reference interpreter and checker | Lexer, parser, checker, and interpreter | Conformance suite passes. Determinism reruns identical across operating systems |
| 3 | Test runner and RL harness | §22 schema. §23 tests. Harness, sandbox, isolation layers 1 and 2, and bubblewrap are built at the code baseline. nsjail, gVisor, a seccomp profile, and Windows job objects are not launched | Every RH entry has a passing test (21 of 21; RH-09 skips where bubblewrap or `setrlimit` is absent). Red-team round 1 done |
| 4 | Baseline evaluation and tokenizer study | Benchmark port. In-context results vs. Python. Tokenizer study | Study reviewed. Any keyword change goes through a TEP (§25) |
| 5 | Training data | §27 pipeline, first HF dataset | Decontamination clean. Dataset card published |
| 6 | Faster backend and sandbox hardening | Bytecode VM or Wasm (§17.5) | 100% conformance, identical results |
| 7 | Publish results | Benchmark report | Reproducible from the published harness |

---

## 37. Notes and Ideas

- Content-addressed definitions (Unison-style) could make RL replays and dataset provenance exact.
- "Explain this diagnostic" training pairs: broken code, diagnostic, fix.
- Curriculum tasks ordered by the language features they use, for RL.
- A labeled `end function` style could help models track long blocks. The §25 study measures it; adopting it would need a TEP.
