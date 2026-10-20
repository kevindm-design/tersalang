# Changelog

## 0.1.0 (unreleased)

The first release of `tersa`, the reference interpreter for Tersalang 0.1-draft.

- **Language.** A lexer, parser, type and effect checker, and tree-walking evaluator for one file plus the built-in standard library: `List`, `Map`, `Set`, `Text`, `Bytes`, `Option`, `Result`, math, console, files, clock, random, and JSON. `Int` is arbitrary precision with a 65,536-bit cap, `Int64` traps on overflow, and `requires`, `ensures`, and `invariant` are checked at run time.
- **Commands.** `tersa check`, `run`, `test`, `sandbox`, `fmt`, `grammar`, `harness run`, `harness validate`, and `version` ([docs/cli.md](docs/cli.md)).
- **Diagnostics.** 128 codes, each with a stable id and a JSON form (`tersa.diagnostic/0.1`), listed with examples in [docs/diagnostics.md](docs/diagnostics.md).
- **RL harness.** The reward is `(1 - w) * C + w * C * E`, with `E` measured against the task's reference solution. Episodes follow `tersa.result/0.9`. The agent's copy withholds hidden-test detail. The child process runs under `setrlimit` on Linux and macOS and under bubblewrap on Linux when it is installed. All 21 reward-hacking defenses have tests ([docs/harness.md](docs/harness.md)).
- **Grammars.** `spec/tersa.ebnf`, the Lark grammar `spec/tersa.lark`, and the generated `spec/tersa.gbnf` with `full` and `decoding` profiles, checked against llama.cpp ([docs/gbnf.md](docs/gbnf.md)).
- **Packaging.** The `tersalang` sdist and wheel for CPython 3.12 to 3.14, with no runtime dependencies.

Known limitations are listed in Design Doc §34 and in [docs/spec-notes.md](docs/spec-notes.md).
