# Command line

`tersa` is the reference interpreter's command. Each subcommand prints its flags with `--help`.

| Command | What it does |
| --- | --- |
| `tersa check FILE` | Parse and type-check. `--parse-only` stops after parsing |
| `tersa run FILE` | Check, then run `main` |
| `tersa test FILE` | Check, then run `test` blocks and doc examples |
| `tersa sandbox FILE` | Run `main` in RL mode with finite default limits and only the grants you pass |
| `tersa fmt [PATH ...]` | Rewrite files into the canonical layout |
| `tersa grammar` | Print a grammar export |
| `tersa harness run TASK --attempt FILE` | Score one attempt against a task (see [harness.md](harness.md)) |
| `tersa harness validate TASK` | Check that a task's reference passes and its mutants fail |
| `tersa version` | Print the tool, language, schema, and Unicode versions |

## check, run, and test

```bash
uv run tersa check examples/hello.tersa
uv run tersa run examples/hello.tersa --allow Console
uv run tersa test examples/hello.tersa
```

`tersa check` prints its diagnostics and exits 0 when there is no error. `tersa run` and `tersa test` check first and do not run a file with a check error.

`tersa test` runs every `test` block and doc example in source order and reports every failure. It ends with a summary line such as `4 tests passed, 1 doc example passed`. Failed counts are added only when nonzero (`3 tests passed, 1 test failed, 0 doc examples passed, 1 doc example failed`). Each test gets its own fuel, memory-unit, and output budget, so running out fails only that test. Property tests (`for all x: Int`) generate `--cases` inputs (default 100) from `--seed` (default 0).

`run`, `sandbox`, and `test` print warnings only alongside a check error or trap that stops the run. `check` and `fmt` always print them.

### JSON output

With `--json`, `check`, `run`, `test`, and `sandbox` end stdout with exactly one line holding the diagnostics as a `tersa.diagnostic/0.1` JSON array, `[]` when there is nothing to report. For `run`, `test`, and `sandbox`, the program's own console output comes first, so a tool reads the last line. Human-readable diagnostics are not printed in this mode, and `tersa test` leaves out its summary line. stderr carries only the program's `print_error` output and the `error: ...` line of a `main` that returns `Error`.

### Effects and grants

A program can use only the effects the host grants. `--allow EFFECT` grants one and can be repeated. `FileRead` and `FileWrite` need a folder (`--allow FileRead=data`), and `Net` needs a host. A missing scope, a scope on an effect that takes none (`--allow Console=x`), and an unknown or mis-cased effect name are `I9010`, exit 4, before anything runs. If `main` declares an effect that was not granted, the run is refused before it starts (`E4010`, exit 3). A call that reaches an ungranted effect at run time traps `T6302`.

### Execution modes

`--mode` on `check`, `run`, and `test` picks the execution mode of design §17.4.

| Mode | Default for | Rules |
| --- | --- | --- |
| `dev` | `check`, `run` | Everything except `foreign` (`E4012`) |
| `test` | `test` | Same as `dev` |
| `rl` | `sandbox` and the harness | Also rejects transcendental math (`E4011`), `foreign` and `uses Python` (`E4012`), and refuses an `--allow` for `FileRead`, `FileWrite`, `Net`, or `Python` (`I9017`, exit 4) |
| `host` | none | Allows `foreign "python:..."` calls, which still need `--allow Python` |

There is no package manifest yet, so `--mode host` stands in for a manifest that says `host`.

### Limits

| Flag | `run` and `test` | `sandbox` | Result when exceeded |
| --- | --- | --- | --- |
| `--fuel` | unlimited (per test for `test`) | 100,000 | `T6201` |
| `--memory-units` | unlimited (per test for `test`) | 100,000 | `T6202` |
| `--max-depth` | 1,000 | 1,000 | `T6203` |
| `--max-int-bits` | 65,536 | 65,536 | `T6204` |
| `--output-bytes` | unlimited | 1,048,576 | `W6205`, and the run continues |
| `--wall-ms` | none | 5,000 | `I9013`, exit 4 |

Each flag overrides its own default. `--fuel` and `--max-depth` must be at least 1, and `--output-bytes` may be 0. An invalid limit is `I9010`, exit 4. Fuel, memory, depth, and the integer cap are deterministic: the same program, input, and seed trap at the same point on every OS.

## sandbox

```bash
uv run tersa sandbox program.tersa --allow Console --fuel 100000 --wall-ms 2000
```

`tersa sandbox` runs `main` in RL mode in-process with only the grants and limits the host passes. There is no ambient file, console, clock, random, or environment access. The clock is virtual, and `Env` is empty unless a harness task lists fixed values. OS isolation applies to the harness child, not to `tersa sandbox`; see [harness.md](harness.md#isolation).

## fmt

```bash
uv run tersa fmt src/                # rewrite in place
uv run tersa fmt --check examples    # report only
uv run tersa fmt < in.tersa > out.tersa
```

`tersa fmt` applies the canonical layout of design §18.2. It has no configuration. With no paths it reads stdin and writes stdout. A directory is walked for `*.tersa` files. `--check` prints a diff and exits 1 when a parseable file would change. A file that does not parse is reported with its diagnostic and not written, and the command exits 3, also when the path is a directory. The Python API is `tersalang.fmt.format_source`.

The formatter keeps every parenthesis you wrote. It adds one pair only around an `and` that sits directly under an `or`, which clears `W1103`. It keeps comments as written. It also sorts imports and `exposing` lists. Formatting twice gives the same result as formatting once.

A line that is exactly `# fmt: skip` leaves that file's bytes unchanged, but only after the file parses. A full-line near miss such as `#fmt:skip` warns `W1104` and the file is formatted.

## grammar

```bash
uv run tersa grammar                                    # spec/tersa.ebnf
uv run tersa grammar --format lark                      # spec/tersa.lark
uv run tersa grammar --format gbnf                      # generated from the Lark file
uv run tersa grammar --format gbnf --profile decoding
```

`--format` is `ebnf` (the default), `lark`, or `gbnf`. The EBNF and Lark exports print the committed spec files. `gbnf` prints a fresh generation, and `--profile` picks `full` (the default) or `decoding`; see [gbnf.md](gbnf.md). The older `--kind` spelling still works and prints a deprecation warning on stderr.

## Exit codes

`tersa run` and `tersa sandbox` follow Design Doc §17.3:

| Code | Meaning |
| --- | --- |
| 0 | Success |
| 1 | `main` returned `Error` |
| 2 | A trap stopped the run |
| 3 | The check failed |
| 4 | The host rejected the invocation or an infrastructure error occurred |

Three commands use 1 for a different failure, because none of 2, 3, or 4 fits: `tersa test` when a test fails or traps, `tersa fmt --check` when a file would change, and `tersa harness validate` when the task fails its gate. A parse error from `tersa fmt` stays 3. `tersa harness run` exits 0 for every scored episode (including reward 0), 2 for a scored resource trap (`T6206`, `T6207`, `T6208`), and 4 when the episode is discarded for an infrastructure error.
