# RL harness and sandbox

`tersa harness` scores one Tersalang program against a task. `tersa sandbox` runs one program under host-set limits. Both use RL mode: no `foreign`, no transcendental math, and no effect that the host did not grant.

## Sandbox

```bash
uv run tersa sandbox program.tersa --allow Console --fuel 100000 --memory-units 100000 --wall-ms 2000
```

| Limit | Default | Result |
| --- | --- | --- |
| `max_int_bits` | 65,536 | `T6204` |
| `--fuel` | 100,000 | `T6201` |
| `--memory-units` | 100,000 | `T6202` |
| `--max-depth` | 1,000 | `T6203` |
| `--output-bytes` | 1,048,576 | `W6205`, and the run continues |
| `--wall-ms` | 5,000 | `I9013`, and the process exits 4 |

Each flag overrides its own default. `tersa run` stays unlimited until you set a flag. RL mode never grants `FileRead`, `FileWrite`, `Net`, or `Python`. A task that lists one fails to load, and `tersa sandbox --allow` for one is refused with `I9017` (exit 4) before anything runs. `Env` is available only when `task.toml` lists fixed values. If `main` declares an effect that was not granted, the run is refused before it starts (`E4010`). A call that actually runs without its grant, including inside a test, traps `T6302`.

The child process used by `tersa harness run` contains a crash. Language limits and the wall clock are enforced in-process. The child also runs under OS isolation, described below. `tersa sandbox` stays in-process.

## Task layout

```
examples/tasks/add_one/
  task.toml
  prompt.md
  interface.tersa
  visible_tests.tersa
  hidden/tests.tersa
  reference/solution.tersa
```

`fuel` and `memory_units` are required and must be greater than 0. A task may lower `max_int_bits`, `call_depth`, and `output_bytes`. It cannot raise them past the language defaults. A limit that is missing, not positive, or out of range is `I9010`. A limit that is present but not an integer is `I9022`, and so is a reward weight that is not a number. A reward weight that is a number outside 0..1 stays `I9018`. Other load failures have their own codes: missing `task.toml` is `I9014`, a language mismatch is `I9015`, an unknown effect is `I9016`, an effect RL mode cannot grant is `I9017` (also when written with a scope, such as `FileRead=data`, because every scoped effect is one RL mode refuses), a scope on an effect that takes none (`Console=out`) is `I9010`, an unknown seed policy is `I9019`, a missing or empty `hidden/` is `I9020`, a task source that does not parse is `I9021`, any other `task.toml` field of the wrong type is `I9022`, and a reference solution that does not match `interface.tersa` (see [Signatures](#signatures)) is `I9025`. `tersa harness` prints `error[CODE]` and exits 4. The episode is discarded. `tersa harness validate` exits 1 when the task fails its gate.

Hidden tests are not returned by `public_task_files`. Replay hashes can contain any hex digit; they are not the hidden tests.

## Signatures

Each function `interface.tersa` requires (a header in an `interface` block, with that block's type parameters first, or a top-level function) must be a top-level function of the attempt with the same name, the same type parameters by position (`T` and `U` match) and constraints, the same parameter count and types, and the same return type. Parameter names, `public`, contracts, and effects are not compared: the interface's contracts replace the attempt's, and the task's `effects` grant governs effects (design §22.1).

A missing or different function is `E3047`, checked right after the attempt's own parse and check. The episode stops at the check stage with `C = 0` and reward 0, whatever `check_credit` is, and every hidden test counts as failed. The diagnostic is one of the attempt's own (`attempt_diagnostics`), so the agent sees it in full:

```
error[E3047]: `add_one` does not match interface.tersa: it returns `Text`, the interface says `Int`
  --> attempt.tersa:3:1
  = interface.tersa requires `function add_one(n: Int) returns Int` (interface.tersa:4:3)
```

`load_task` runs the same check on `reference/solution.tersa`; a reference that does not match is `I9025` and the task does not load.

## What the agent sees

`agent_view(episode)` in Python, or `tersa harness run --agent-view`, gives the agent's copy (design §22.5). The exit code is still computed from the full episode. The rule (RH-20):

- `tests.cases` and `stdout` are removed. The child's stderr is never in the episode.
- The first `attempt_diagnostics` diagnostics come from the attempt's own parse and check. They describe only the attempt and keep full detail.
- Every later diagnostic was raised while the attempt was checked together with the hidden tests or while a hidden test ran. Wherever its span points, it keeps only its code (with severity, category, and `docs_url`), one position, and the message `raised while checking or running the hidden tests; details are withheld`. `related` is empty, and `values`, `blame`, and `fix` are null. The position is the primary span when it is in the attempt or `interface.tersa`, otherwise the first such `related` span, otherwise file `<hidden>` at 1:1.
- `infrastructure_error` keeps its code. Its message becomes `infrastructure error; details are withheld`.
- Visible tests add nothing to the episode except the `visible_tests` counts; run `tersa test` on `visible_tests.tersa` for their full detail. `tersa harness validate` reports no diagnostics; it is for task authors.
- `resources.fuel_used`, `resources.memory_units_used`, and `breakdown.ref_fuel` are rounded down to a power of two (`coarse_count`; 0 stays 0), and `E` and `reward` are recomputed from them; an `E` of 0 stays 0. The limits, `C`, and `w` stay exact. So the agent's `E` and `reward` are approximate; the trainer's copy keeps the exact numbers (RH-21).

Power-of-two buckets rather than two significant figures: an attempt can spend fuel or memory in proportion to a hidden input, so these numbers are a channel it controls. A power-of-two bucket leaves 31 values up to 2³¹, about 5 bits per number, where two significant figures leave 90 per decade. It keeps the order and stays within a factor of two, the ratio scale `E` uses.

What the agent can still learn about a hidden test is limited to what the attempt chose to do with it: which code and which line failed, the test counts, and the rounded fuel and memory numbers. The combined check drops repeats of the attempt's own warnings.

## Combined module

The harness checks and runs one module built from the attempt and the task's hidden files.

The merge keeps every candidate declaration except `test` blocks and `main`: functions, constants, records, choices, and the attempt's own interfaces and `implements` blocks (design §22.1). It adds every hidden function (except `main`), constant, record, choice, interface, and test. Hidden code is namespaced: every name a hidden file declares, top-level or local, and every hidden import qualifier is renamed to `name@hidden` before the check. `@` cannot be written in Tersalang, so an attempt can neither reach nor redefine a hidden helper, constant, record, choice, case, interface, or interface function, and a candidate name that happens to match one does not clash. Names that `interface.tersa` declares belong to the candidate and are not renamed; a hidden declaration of one of them is dropped. Without an interface, a hidden test reaches the candidate only through names the hidden files do not declare. A hidden import keeps its own exposed names: a lower-case one is rewritten to a qualified call, and std types and cases stay exposed. A hidden helper called as a method (`x.helper()`) is renamed with the helper, and a builtin method of the same name still wins, as it does outside the harness. A hidden `implements` block is kept when its interface is hidden, or when the interface is public (`Comparable` or declared in `interface.tersa`) and the type is a hidden record or choice. A hidden `implements` of a public interface for a type the candidate can name is dropped: it could change what the candidate's own calls dispatch to, and a candidate implementing the same pair would get `E3043` from hidden code. Hidden `foreign` declarations are dropped. `tersa harness validate` redefines hidden interfaces in its override attack too. Values of hidden records and choices show under the names the task wrote. Visible tests are merged the same way under `@visible`.

Contracts on `interface.tersa` replace the contracts of the functions that file names. A helper the interface does not name keeps its own contracts. The candidate's `test` blocks and `main` are dropped. A candidate cannot weaken a named task function (RH-06).

## Reward

`C` is the correctness score. `E` is the efficiency score. `w` is `efficiency_weight`.

```
reward = (1 - w) * C + w * C * E
```

1. Parse failure: `C = 0` and `E = 0`. The candidate did not run, so it earns no efficiency. The reward is 0.
2. Check failure: `C = check_credit` (default `0`) and `E = 0`. The candidate did not run. With `w = 0` the reward stays `check_credit`. With `w > 0` it is `(1 - w) * check_credit`. A function that does not match `interface.tersa` (`E3047`) scores `C = 0` and reward 0 instead.
3. Otherwise `C = check_credit + (1 - check_credit) * passed / total`.
4. Tests that do not run count as failed. Zero hidden tests use `C = 0` and `E = 0`.
5. The reference basis is used only when the reference solution executes and passes every hidden test (`C_ref = 1`). `ref_fuel` is the fuel that run uses, summed the same way as the candidate, under the same limits and seed. `E = min(1, max(ref_fuel, 1) / max(fuel_used, 1))`. A reference that used no fuel still counts as 1, so a correct reference scores `E = 1` and reward 1. Matching or beating the reference is 1, twice the fuel is 0.5, and ten times the fuel is 0.1. The harness measures this by running the reference and caches it for that seed.
6. Otherwise `E` falls back to `max(0, 1 - fuel_used / fuel)`. `E_basis` is `"limit"` and `E_basis_reason` is `"no_reference"`, `"reference_did_not_execute"`, or `"reference_failed_hidden_tests"`. `ref_fuel` is null on that fallback. A declared `[reward] reference_fuel` stands in only when the measurement is not available (no reference, or it did not execute). That case reports `E_basis` `"declared"`, `ref_fuel` as the declared number, and `E_basis_reason` as `"no_reference"` or `"reference_did_not_execute"`. The same formula applies, including the `max(ref_fuel, 1)` floor. A reference that ran and failed hidden tests is not the yardstick, even when that field is set. `tersa harness validate` still checks a declared number against the real run, and it fails the task when the reference does not pass every hidden test. A `reference_fuel` that is not an integer greater than or equal to 0 is `I9022`.
7. `w` defaults to `0.1` when `task.toml` omits it. A task may set it in `[reward]`, inside 0..1. Outside that range is `I9018`. A non-number is `I9022`. `w = 0` makes the reward equal `C`.
8. Efficiency is multiplied by `C`. A fast wrong program (`C = 0`) scores 0 whatever `E` is. With every hidden test passing and the default weight, the reward is `0.9 + 0.1 * E`, between 0.9 and 1. Nothing is clipped to 1. `C`, `E`, `w`, and the reward are each in `[0, 1]`.
9. Each hidden test starts from a fresh interpreter and the same seed. `fuel_used` is the sum of those runs.
10. Fuel, memory, depth, and the integer cap are ordinary scored failures (`T6201`–`T6204`, exit 0). `W6205` keeps the episode. A candidate killed by the OS or stopped by its own wall clock is a scored resource trap: reward 0 and exit 2 (see [Scored resource traps](#scored-resource-traps-reward-0-exit-2)). Only an external fault is discarded with a null reward and exit 4 (see [Infrastructure errors](#infrastructure-errors-reward-null-exit-4)).

```bash
uv run tersa harness run examples/tasks/add_one \
  --attempt examples/tasks/add_one/reference/solution.tersa
uv run tersa harness validate examples/tasks/add_one
```

`validate` runs the reference solution and AST mutants of its function and test bodies (operator swaps, constant tweaks, `not` removal, return-value changes). Sites are grouped by kind and drawn round-robin after a seeded spread, so a late site is not dropped because sixteen earlier ones came first. At most 16 well-typed texts are kept. A splice that does not parse or does not type-check is skipped and is not counted as killed. A returned value is replaced with a literal of the declared type (`0`/`1` for `Int`, `true`/`false` for `Bool`, `0.0`/`1.0` for `Float`, `""`/`"mut"` for `Text`). Other return types, including `Unit`, are not replaced with `0`. Contracts are not mutated. It fails if the reference does not execute and pass every hidden test, a mutant's correctness is still 1, or `reference_fuel` does not match the fuel that run used. The reference matches its own fuel, so a correct reference has `E = 1`. The `add_one` reference uses 88 fuel (`h_forty_one` 16, `h_property` 72), so `ref_fuel` is 88, `E` is 1, and the reward is 1. If no mutant can be made, the report's `warnings` list says so and the task is not failed for that alone. `validate` exits 1 when the task fails.

`validate` also runs an override attack. It appends a hostile redefinition of every hidden name the reference does not already define: a `Bool` helper returns `true`, any other helper fails, an `Int`, `Float`, `Bool`, or `Text` constant is changed, a record or choice gets a different shape, and a hidden local becomes a top-level `Int` constant. A hostile declaration that does not type-check next to the reference is listed in `override_attack.skipped`. The attacked reference must score the reference's reward with the same status for every hidden test, and every mutant with the same block appended must still fail a hidden test. Otherwise `override_attack.held` is false and the task fails. The report's `override_attack` object has `declarations`, `skipped`, `reward`, `held`, and `mutants_survived`. A task with nothing to redefine reports `held` true with empty lists.

`tersa harness run` exits 0 for a scored episode, including reward 0 from a wrong answer, a fuel trap, or an unclassified crash. It exits 2 for a scored resource trap (`T6206`, `T6207`, or `T6208`). It exits 4 for an infrastructure error (`infrastructure_error.code` starts with `I`). A reference wall-clock stop does not do that: validation exits 1, and a candidate run uses the fallback basis. That matches Design Doc §17.3: 0 success, 1 `main` returns Error, 2 trap, 3 check failure, 4 infrastructure or toolchain error.

## Scored resource traps (reward 0, exit 2)

These are the candidate's own failures. They are scored, never discarded: reward 0 with `C = 0` and `E = 0`, `infrastructure_error` null, and `tersa harness run` exits 2. They apply under every isolation backend, including `none`.

| Code | Message | Cause |
| --- | --- | --- |
| `T6206` | `OS memory limit exceeded` | The candidate died from the address cap or a memory fault: `MemoryError`, `SIGKILL`, `SIGSEGV`, `SIGBUS`, or `SIGABRT` |
| `T6207` | `OS CPU limit exceeded` | The OS CPU cap killed the candidate (`SIGXCPU`). A process-count cap stops new processes with an error instead |
| `T6208` | `Wall-clock limit exceeded` | The candidate hit its own clock. The message names it: `in-process wall-clock backstop reached (N ms)` or `child process wall-clock backstop reached (N s)` |

The host cannot be told apart from a slow program, so the candidate's own clock is scored 0 rather than left null. Every hidden test is listed by its real name. A test that was running is trapped; tests that never started are failed. The kill diagnostic is on the episode.

A child that exits without JSON, and is not one of those OS kills, is also scored rather than discarded (RH-10): reward 0 with `C = 0`, `E = 0`, a `crash` object with `type` `"process"`, and every hidden test listed as failed. It has no trap code, so `tersa harness run` exits 0. Treating that crash as a discard would let an agent farm nulls.

The parent does not pass the child's output through on trust. It must be one JSON object that passes `spec/schemas/result.schema.json` (shipped in the package), whose `reward` is null exactly when `infrastructure_error` is set and otherwise equals the formula from its own breakdown, whose test counts add up, whose `replay.source_hash` and `replay.task_hash` match the attempt and task the parent sent, and whose `isolation` is the backend the parent launched. Output that fails any of these is scored the same way as a crash, with `crash.type` `"invalid_result"` and the first problem in `crash.message`. It is not discarded: a discard would reward an agent that found a way to garble the result, and the safe reading of an untrustworthy result is that the attempt earned nothing. A harness bug that produced invalid output would show up as `invalid_result` crashes, not as silent nulls.

## Infrastructure errors (reward null, exit 4)

These are external faults or invalid inputs, not the program's own behavior. The episode is discarded: `reward` and every breakdown field are null, and the command exits 4.

| Code | When |
| --- | --- |
| `I9010` | An invalid limit (missing, not positive, or out of range), from `task.toml` or a CLI flag, or an invalid `--allow` grant (unknown effect, or a scoped effect without its scope) |
| `I9013` | A wall-clock backstop that is not the candidate's own failure: `tersa sandbox`, `tersa run`, and the reference solution while it is measured or validated |
| `I9014`–`I9022`, `I9025` | Other task-load failures (listed under [Task layout](#task-layout)) |
| `I9024` | The requested isolation backend cannot be launched. The message names the backend |

`I9013` on the reference episode does not end a candidate run with exit 4: `tersa harness validate` fails its gate and exits 1, and `tersa harness run` scores the candidate on the declared or limit basis with `E_basis_reason` `"reference_did_not_execute"`. `I9023` is reserved and is not emitted; a candidate OS CPU kill is `T6207`.

## Python

```python
from pathlib import Path
from tersalang.harness import load_task, run_episode

task = load_task(Path("examples/tasks/add_one"))
episode = run_episode(task, task.reference_text, filename="reference/solution.tersa")
print(episode.to_json())
```

The episode schema is `tersa.result/0.9`. `breakdown` is `C`, `E`, `E_basis`, `E_basis_reason`, `ref_fuel`, and `w`, and `reward` is the formula. `E_basis` is `"reference"` for a measured passing reference (`E_basis_reason` null), `"declared"` when a declared `reference_fuel` stands in, and `"limit"` for the fuel-limit fallback. `E_basis_reason` `"reference_did_not_execute"` covers a reference that did not finish, including a wall-clock stop. `isolation` is the backend that ran, and `isolation_warning` is null or the stronger backends that were skipped. An infrastructure error sets `reward` and the breakdown fields to null. A candidate OS or wall-clock trap, and an unclassified child crash, set `C` and `E` to 0 and `reward` to 0. A child that never started the tests lists every hidden test by name with status failed. `spec/schemas/result.schema.json` describes the whole episode: every top-level field is required except `stdout`, and no unknown field is allowed. `attempt_diagnostics` is the number of leading diagnostics that come from the attempt's own parse and check. The agent view omits `tests.cases` and `stdout`, withholds the detail of the other diagnostics, and still passes the schema. [CHANGELOG.md](../CHANGELOG.md) lists what each schema version changed.

## Isolation

`tersa harness run` accepts `--isolation none|rlimit|bwrap|nsjail|gvisor`. Omit the flag and the child uses the strongest backend this host can launch.

| Backend | Where it runs | What it does |
| --- | --- | --- |
| `none` | Everywhere, and the in-process path | No OS caps |
| `rlimit` | Linux and macOS | Address space and data, CPU seconds, file size, open files, no core dumps, and a process-count cap when the host can count processes |
| `bwrap` | Linux, when bubblewrap is installed | Those caps, plus no network, a filesystem that holds only the read-only paths listed below and a tmpfs workspace at `/tmp/tersalang-workspace` (also the working directory), separate PID, IPC, and UTS namespaces, a user namespace, and all capabilities dropped |
| `nsjail`, `gvisor` | Not launched | The episode is `I9024` and `reward` is null |

Under every backend, on every OS, the child gets only these environment variables: `PATH`, `SYSTEMROOT`, `WINDIR`, `TEMP`, and `TMP` when the parent has them (Windows cannot start Python without `SYSTEMROOT`), the test hooks `TERSALANG_HARNESS_CRASH`, `TERSALANG_HARNESS_FORGE`, and `TERSALANG_HARNESS_SIGNAL`, and fixed Python settings: `PYTHONPATH` set to the directory holding the `tersalang` package the parent imported, `PYTHONNOUSERSITE=1`, `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8`, and `PYTHONDONTWRITEBYTECODE=1`. Nothing else from the parent's environment reaches the child. Python adds `LC_CTYPE` and bubblewrap adds `PWD`.

Under bubblewrap the child's root is empty and read-only. It binds, read-only and at the same paths: the Python install (`sys.prefix`, `sys.base_prefix`, `sys.exec_prefix`, `sys.base_exec_prefix`, and the directory above the real interpreter binary), the `tersalang` package directory, the shared libraries (`/usr/lib`, `/usr/lib32`, `/usr/lib64`, `/usr/libx32`, and `/lib`, `/lib32`, `/lib64`, `/libx32` when they are real directories), `/etc/ld.so.cache`, the task directory, and the attempt file. A path nested in another bound path is not bound twice. Each symlink met on the way to one of those paths, such as a merged-`/usr` `/lib64` or a venv `python` that points through a versioned directory, is recreated as the same symlink. Everything else, including the repository outside the package, home directories, the rest of `/etc`, and the rest of `/tmp`, does not exist inside the sandbox. The parent passes absolute task and attempt paths, so a relative `TASK_DIR` or `--attempt` still works.

Windows job objects are unsupported: a child started by the standard library is already running before a job could be assigned, and nested jobs are commonly denied. The default there is `none`, with a warning. nsjail is not packaged for the Ubuntu runner and has no launcher here. gVisor `runsc` is not launched, because it needs host cgroup access that a normal user does not have.

An OS memory kill of the candidate is `T6206`. An OS CPU kill is `T6207`. Both score reward 0 with `C = 0` and `E = 0` under every backend, including `none`, and the harness exits 2. The harness process stays up. A process-count cap stops new processes with an error instead of a kill code. A backend that cannot launch is `I9024`, reward null, exit 4. `rlimit` does not block the network or writes outside the workspace; bubblewrap does. Ubuntu CI installs bubblewrap from apt and runs those tests. macOS runs the CPU cap when the host delivers `SIGXCPU` and skips it when `RLIMIT_CPU` is not enforced. The address cap is skipped on a host that does not enforce it. Windows has no `setrlimit`, so those bomb tests skip; a POSIX self-signal under `none` skips there too. macOS and Windows skip bubblewrap.

The reward formula and the efficiency formula do not change. An in-process episode records `isolation` `"none"` and a null warning, which is what the cross-OS determinism dump uses. A normal program under `rlimit` or `bwrap` keeps the same score; only `isolation` changes, and that value is stable for the backend.

`canonical_bytes(episode)` replaces `toolchain.python` and `toolchain.platform` so the same attempt can be compared across operating systems. The reward, the breakdown, tests, diagnostics, and resource counts are deterministic for a fixed seed.

## Reward-hacking rows

| Row | What the harness does |
| --- | --- |
| RH-09 | Layer 2 caps memory, CPU, file size, open files, and process count on Linux and macOS. Bubblewrap, when installed, also blocks the network and writes outside the workspace. A memory bomb scores `T6206` and a CPU bomb scores `T6207`, both with reward 0 and `C = 0`. A missing backend is `I9024` (reward null, exit 4). Tests skip where the backend is absent. |
| RH-10 | A program-induced crash or resource kill is a failure, so an agent cannot farm a discard. OS memory is `T6206`, OS CPU is `T6207`, and the candidate's own wall clock is `T6208`. Each scores reward 0 with `C = 0` and `E = 0` and exits 2, and lists every hidden test by name. A child that exits without JSON, or with output that fails the result schema or does not match its attempt, task, or backend, and is not one of those kills, scores 0 with `C = 0` and a `crash` object (`process` or `invalid_result`), and the same test list. `I9024` and a harness bug stay reward null and exit 4. A reference stopped during validation fails the gate (exit 1). A candidate run uses `E_basis_reason` `"reference_did_not_execute"`. |
| RH-20 | A candidate cannot read hidden inputs, expected values, or test names from its view. Its own parse and check diagnostics keep full detail; every diagnostic raised with the hidden tests in scope keeps only its code, one public position, and a generic message. The attack test tries the attempt's own `requires`, an `ensures` with `old(...)`, the interface `ensures`, a `fail` message, a slice trap, `print`, the hidden `expect`, and a combined-check error, in process and through `tersa harness run --agent-view`. |
| RH-21 | A candidate cannot read a hidden input from its fuel or memory numbers. The agent view rounds `fuel_used`, `memory_units_used`, and `ref_fuel` down to a power of two and recomputes `E` and `reward`; the trainer's copy is exact. The attack test spends fuel and memory in proportion to the hidden input: inputs 4173 and 4174 give identical agent views, under both the reference and the limit basis, in process and through `tersa harness run --agent-view`. |
