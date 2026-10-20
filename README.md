# Tersalang

Tersalang is a small, word-based programming language designed to be written by language models and scored by reinforcement-learning harnesses. Blocks open with `do` and close with `end`, every effect a function uses is declared with `uses`, contracts (`requires`, `ensures`, `invariant`) are checked at run time, and every diagnostic has a stable code and a JSON form.

This repository holds `tersa`, the reference interpreter, and an exported copy of the language specification.

```tersa
module hello

import std.console exposing print

public function main() returns Unit
  uses Console
do
  print("Hello, world!")
end
```

The language version is **0.1-draft** and the tool version is **0.1.0**. Both can still change in incompatible ways.

## Install

You need CPython 3.12 or newer and [uv](https://docs.astral.sh/uv/). The interpreter has no runtime dependencies.

```bash
git clone https://github.com/kevindm-design/tersalang.git
cd tersalang
uv sync
uv run tersa version
```

`pip install -e .` also works and puts `tersa` on your `PATH`. The examples below write `tersa` for `uv run tersa`.

## Quickstart

Save this as `area.tersa`:

```tersa
module area

import std.console exposing print

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

test "a 3 by 4 rectangle has area 12"
do
  expect area(Rect(width = 3, height = 4)) == 12
end

public function main() returns Unit
  uses Console
do
  print(show(area(Rect(width = 3, height = 4))))
end
```

**Check** parses and type-checks the file. It prints nothing and exits 0 when the file is clean:

```console
$ tersa check area.tersa
```

**Run** calls `main`. Effects are granted by the host, so `Console` must be allowed:

```console
$ tersa run area.tersa --allow Console
12
$ tersa run area.tersa
error[E4010]: main uses Console, but Console was not granted
  --> area.tersa:23:8
  = fix: run with --allow Console
```

**Test** runs the `test` blocks and doc examples and ends with a summary line:

```console
$ tersa test area.tersa
1 test passed, 0 doc examples passed
```

**Format** rewrites files into the one canonical layout. `--check` only reports, prints a diff, and exits 1 when a file would change:

```console
$ tersa fmt --check messy.tersa
would reformat messy.tersa
...
-      return r.width*r.height
+  return r.width * r.height
$ tersa fmt messy.tersa
```

`check`, `run`, `test`, and `sandbox` accept `--json`, which ends stdout with one line holding the diagnostics as a `tersa.diagnostic/0.1` array:

```console
$ tersa check --json bad.tersa
[{"schema": "tersa.diagnostic/0.1", "code": "E3033", "severity": "error", "category": "type", "message": "expected Int, found Text", ...}]
```

Each code links to a page in [docs/diagnostics.md](docs/diagnostics.md) with a wrong and a fixed example. Exit codes, execution modes, limits, and every flag are in [docs/cli.md](docs/cli.md).

## Harness

`tersa harness` scores one program against a task. That is the loop an RL trainer runs. A task is a directory:

```
examples/tasks/add_one/
  task.toml              limits, effect grants, reward settings
  prompt.md              what the agent is asked to do
  interface.tersa        the functions the attempt must define, with contracts
  visible_tests.tersa    tests the agent may see
  hidden/tests.tersa     tests that score the attempt
  reference/solution.tersa
```

```bash
uv run tersa harness run examples/tasks/add_one --attempt my_attempt.tersa
uv run tersa harness run examples/tasks/add_one --attempt my_attempt.tersa --agent-view
uv run tersa harness validate examples/tasks/add_one
```

`harness run` prints one `tersa.result/0.9` episode as JSON. The harness:

- Checks that the attempt defines the functions `interface.tersa` requires, with the same signatures.
- Merges the attempt with the hidden tests in a private namespace, so the attempt cannot reach or redefine hidden code.
- Runs each hidden test in a fresh interpreter under fixed fuel and memory limits, in a child process with OS isolation where the host supports it.
- Scores the episode as `reward = (1 - w) * C + w * C * E`. `C` is the fraction of hidden tests passed (with the default `check_credit` of 0), `E` compares fuel used with the reference solution, and `w` defaults to 0.1.

`--agent-view` prints the copy an agent may see. That copy withholds hidden-test detail and rounds the resource counts. `harness validate` checks a task before training: the reference must pass, and sampled mutants of it must not.

The full rules are in [docs/harness.md](docs/harness.md). They cover the reward, isolation backends, scored traps versus discarded episodes, and the reward-hacking defenses.

## Grammars

`tersa grammar` prints the grammar as EBNF (the default), Lark, or GBNF. The GBNF export works with stock llama.cpp, so a model can be constrained to write only Tersalang that parses:

```bash
uv run tersa grammar --format gbnf                      # every layout the parser accepts
uv run tersa grammar --format gbnf --profile decoding   # the formatter's whitespace, for generation
```

See [docs/gbnf.md](docs/gbnf.md).

## Documentation

| Document | Contents |
| --- | --- |
| [spec/](spec/) | The Design Doc and the Language Reference, plus the grammars and catalogs |
| [docs/cli.md](docs/cli.md) | Every `tersa` command, flag, execution mode, and exit code |
| [docs/harness.md](docs/harness.md) | Task layout, reward formula, agent view, isolation, and reward-hacking defenses |
| [docs/gbnf.md](docs/gbnf.md) | The GBNF export, its two profiles, and how it is checked against llama.cpp |
| [docs/diagnostics.md](docs/diagnostics.md) | Every diagnostic code with examples (generated from `spec/diagnostics.yaml`) |
| [docs/spec-notes.md](docs/spec-notes.md) | Where this interpreter settles a point the specs leave open |
| [CHANGELOG.md](CHANGELOG.md) | What changed in each release |

## Repository layout

| Path | Contents |
| --- | --- |
| `src/tersalang/` | The interpreter. The package docstring in `__init__.py` lists each module |
| `spec/` | Specification exports, `tersa.ebnf`, `tersa.lark` (the grammar oracle and source of `tersa.gbnf`), the diagnostic, fuel, and limit catalogs, and JSON schemas |
| `conformance/` | `.tersa` programs whose header says what each must produce, such as `# expect: check-error E3033` |
| `examples/` | A hello-world program and the `add_one` harness task |
| `tests/` | Unit, conformance, property, and fuzz tests |
| `scripts/` | CI checks: formatting, GBNF drift, llama.cpp agreement, determinism bytes, and the generated diagnostics page |
| `teps/` | The template for Tersalang Enhancement Proposals |

## What this version runs

The interpreter lexes, parses, type-checks, and evaluates one file plus the built-in standard library: `List`, `Map`, `Set`, `Text`, `Bytes`, `Option`, `Result`, math, console, files, clock, random, and JSON. `Int` is arbitrary precision with a 65,536-bit cap, and `Int64` traps on overflow. Not yet included: multi-file packages, the language server, `Net`, and container isolation beyond bubblewrap.

The language was formerly called AIOWL.

## Contributing and license

See [CONTRIBUTING.md](CONTRIBUTING.md). Every commit needs a `Signed-off-by` trailer. Language changes go through a TEP.

The code is Apache-2.0. The specification and docs are CC BY 4.0. See `LICENSE` and `NOTICE`.
