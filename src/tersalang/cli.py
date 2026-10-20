# SPDX-License-Identifier: Apache-2.0
"""Command line for the Tersalang reference interpreter."""

from __future__ import annotations

import argparse
import difflib
import json
import sys
import unicodedata
from pathlib import Path
from typing import NoReturn

from tersalang.diagnostics import render_all
from tersalang.driver import (
    check_text,
    default_limits,
    diagnostics_outcome,
    parse_allows,
    run_tests,
    run_text,
    validate_limits,
)
from tersalang.source import decode_source_bytes
from tersalang.version import (
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_INT_BITS,
    DEFAULT_PROPERTY_CASES,
    DEFAULT_SANDBOX_FUEL,
    DEFAULT_SANDBOX_MEMORY,
    DEFAULT_SANDBOX_WALL_MS,
    DEFAULT_TEST_OUTPUT_BYTES,
    DIAGNOSTIC_SCHEMA,
    LANGUAGE_VERSION,
    RESULT_SCHEMA,
    TOOL_VERSION,
)


class _Parser(argparse.ArgumentParser):
    """An argument parser whose usage errors exit 4.

    argparse exits 2 on a usage error, but exit 2 means a trap; a bad flag is a
    toolchain error.
    """

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(4, f"{self.prog}: error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    """The `tersa` argument parser with every subcommand."""
    parser = _Parser(prog="tersa")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="parse and type-check a file")
    _add_file(check)
    check.add_argument("--json", action="store_true", help=_JSON_HELP)
    _add_mode(check, "dev")
    check.add_argument("--parse-only", action="store_true", help="stop after parsing")

    run = sub.add_parser("run", help="run main")
    _add_file(run)
    _add_run_flags(run, fuel="unlimited", memory="unlimited", output="unlimited", wall="none")
    _add_mode(run, "dev")

    sandbox = sub.add_parser("sandbox", help="run main in RL mode with only the grants you pass")
    _add_file(sandbox)
    _add_run_flags(
        sandbox,
        fuel=str(DEFAULT_SANDBOX_FUEL),
        memory=str(DEFAULT_SANDBOX_MEMORY),
        output=str(DEFAULT_TEST_OUTPUT_BYTES),
        wall=f"{DEFAULT_SANDBOX_WALL_MS} ms",
    )

    test = sub.add_parser("test", help="run tests and doc examples and print a summary line")
    _add_file(test)
    _add_run_flags(
        test, fuel="unlimited, per test", memory="unlimited, per test", output=None, wall="none"
    )
    test.add_argument(
        "--cases",
        type=int,
        default=DEFAULT_PROPERTY_CASES,
        help="generated cases per property test (default: %(default)s)",
    )
    _add_mode(test, "test")

    sub.add_parser("version", help="print toolchain versions")
    grammar = sub.add_parser("grammar", help="print a grammar export")
    grammar.add_argument(
        "--format",
        choices=("ebnf", "lark", "gbnf"),
        help="export format (default: ebnf)",
    )
    grammar.add_argument(
        "--kind",
        choices=("ebnf", "lark", "gbnf"),
        help=argparse.SUPPRESS,
    )
    grammar.add_argument(
        "--profile",
        default="full",
        choices=("full", "decoding"),
        help="GBNF profile (default: %(default)s)",
    )

    fmt = sub.add_parser("fmt", help="rewrite files in the canonical layout")
    fmt.add_argument(
        "files", nargs="*", help="files or directories to rewrite; none means stdin to stdout"
    )
    fmt.add_argument("--check", action="store_true", help="exit 1 if a file would change")

    harness = sub.add_parser("harness", help="score an attempt against a task's hidden tests")
    harness_sub = harness.add_subparsers(dest="harness_command", required=True)
    harness_run = harness_sub.add_parser("run", help="run one attempt and print episode JSON")
    harness_run.add_argument("task", help="task directory containing task.toml")
    harness_run.add_argument("--attempt", required=True, help="the candidate .tersa file")
    harness_run.add_argument(
        "--seed", type=int, default=0, help="seed for property tests (default: %(default)s)"
    )
    harness_run.add_argument("--attempt-id", default="", help="copied into the episode JSON")
    harness_run.add_argument(
        "--in-process",
        action="store_true",
        help="run inside this process instead of a child process",
    )
    harness_run.add_argument(
        "--isolation",
        default=None,
        choices=("none", "rlimit", "bwrap", "nsjail", "gvisor"),
        help="child sandbox (default: the strongest backend this host can launch)",
    )
    harness_run.add_argument(
        "--agent-view",
        action="store_true",
        help="print the agent's copy (design 22.5): no cases or stdout, and diagnostics "
        "raised with the hidden tests in scope reduced to code, position, and a generic message",
    )
    harness_validate = harness_sub.add_parser("validate", help="mutation-check a task")
    harness_validate.add_argument("task", help="task directory containing task.toml")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one `tersa` command and return its exit status.

    0 is success. 1 is a `main` that returned `Error`, a failed or trapped
    test, a file `fmt --check` would change, or a task that failed
    `harness validate`. 2 is a trap under `run` or `sandbox`, or an OS kill or
    timeout of a `harness run` candidate. 3 is a compile or format error, and
    4 a toolchain, configuration, or infrastructure error.
    """
    args = build_parser().parse_args(argv)
    if args.command == "version":
        _print_version()
        return 0
    if args.command == "grammar":
        if args.kind is not None:
            print("warning: `--kind` is deprecated; use `--format`", file=sys.stderr)
        chosen = args.format or args.kind or "ebnf"
        return _print_grammar(chosen, args.profile)
    if args.command == "fmt":
        return _fmt(args.files, args.check)
    if args.command == "harness":
        return _harness(args)

    path = Path(args.file)
    try:
        text = decode_source_bytes(path.read_bytes())
    except OSError as exc:
        print(f"error: cannot read {path}: {exc}", file=sys.stderr)
        return 4

    if args.command == "check" and args.parse_only:
        from tersalang.fmt import fmt_skip_warnings
        from tersalang.lexer import lex_text
        from tersalang.parser import parse_module

        _source, tokens, diagnostics = lex_text(str(path), text)
        parse_module(_source, tokens, diagnostics)
        diagnostics.extend(fmt_skip_warnings(str(path), text))
        code = 3 if any(item.severity == "error" for item in diagnostics) else 0
        return _emit(diagnostics_outcome(code, diagnostics, as_json=args.json))

    if args.command == "check":
        outcome = check_text(str(path), text, mode=args.mode, as_json=args.json)
        return _emit(outcome)

    fuel = args.fuel
    memory = args.memory_units
    output = getattr(args, "output_bytes", None)
    wall_ms = getattr(args, "wall_ms", None)
    if args.command == "sandbox":
        if fuel is None:
            fuel = DEFAULT_SANDBOX_FUEL
        if memory is None:
            memory = DEFAULT_SANDBOX_MEMORY
        if output is None:
            output = DEFAULT_TEST_OUTPUT_BYTES
        if wall_ms is None:
            wall_ms = DEFAULT_SANDBOX_WALL_MS
    limits = default_limits(
        test=args.command == "test",
        fuel=fuel,
        memory=memory,
        bits=args.max_int_bits,
        depth=args.max_depth,
        output=output,
        wall_ms=wall_ms,
    )
    invalid = validate_limits(limits)
    if invalid is not None:
        return _emit(diagnostics_outcome(4, [invalid], as_json=args.json))
    grants, bad_grant = parse_allows(args.allow)
    if bad_grant is not None:
        return _emit(diagnostics_outcome(4, [bad_grant], as_json=args.json))
    if args.command in {"run", "sandbox"}:
        outcome = run_text(
            str(path),
            text,
            mode="rl" if args.command == "sandbox" else args.mode,
            grants=grants,
            seed=args.seed,
            limits=limits,
            as_json=args.json,
        )
        return _emit(outcome)
    outcome = run_tests(
        str(path),
        text,
        mode=args.mode,
        grants=grants,
        seed=args.seed,
        cases=args.cases,
        limits=limits,
        as_json=args.json,
    )
    return _emit(outcome)


def _add_file(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("file", help="the .tersa source file")


_JSON_HELP = "end stdout with one line holding the tersa.diagnostic JSON array"


def _add_mode(parser: argparse.ArgumentParser, default: str) -> None:
    parser.add_argument(
        "--mode",
        default=default,
        choices=("dev", "test", "rl", "host"),
        help=(
            "execution mode (design 17.4): dev and test allow everything but `foreign`; rl also "
            "refuses transcendental math and FileRead, FileWrite, Net, and Python grants; "
            "host allows `foreign` Python calls (default: %(default)s)"
        ),
    )


def _add_run_flags(
    parser: argparse.ArgumentParser, *, fuel: str, memory: str, output: str | None, wall: str
) -> None:
    parser.add_argument(
        "--allow",
        action="append",
        default=[],
        metavar="EFFECT[=SCOPE]",
        help=(
            "grant an effect; FileRead and FileWrite need =FOLDER and Net needs =HOST; repeatable"
        ),
    )
    parser.add_argument("--seed", type=int, default=0, help="random seed (default: %(default)s)")
    parser.add_argument("--fuel", type=int, help=f"fuel limit (default: {fuel})")
    parser.add_argument("--memory-units", type=int, help=f"memory-unit limit (default: {memory})")
    parser.add_argument(
        "--max-int-bits",
        type=int,
        default=DEFAULT_MAX_INT_BITS,
        help="largest Int in bits (default: %(default)s)",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=DEFAULT_MAX_DEPTH,
        help="call depth limit (default: %(default)s)",
    )
    if output is not None:
        parser.add_argument(
            "--output-bytes", type=int, help=f"console output limit (default: {output})"
        )
    parser.add_argument(
        "--wall-ms", type=int, help=f"wall-clock backstop in milliseconds (default: {wall})"
    )
    parser.add_argument("--json", action="store_true", help=_JSON_HELP)


def _emit(outcome: object) -> int:
    stdout = getattr(outcome, "stdout", "")
    stderr = getattr(outcome, "stderr", "")
    if stdout:
        print(stdout, end="")
    if stderr:
        print(stderr, file=sys.stderr, end="")
    return int(getattr(outcome, "exit_code", 1))


def _print_version() -> None:
    print(f"tersalang {TOOL_VERSION}")
    print(f"language {LANGUAGE_VERSION}")
    print(f"diagnostic schema {DIAGNOSTIC_SCHEMA}")
    print(f"result schema {RESULT_SCHEMA}")
    print(f"unicode {unicodedata.unidata_version} (host unicodedata)")


def _harness(args: argparse.Namespace) -> int:
    from tersalang.harness import (
        TaskLoadError,
        agent_view,
        load_task,
        run_episode,
        run_episode_isolated,
        validate_task,
    )

    task_dir = Path(args.task)
    try:
        task = load_task(task_dir)
    except TaskLoadError as exc:
        print(f"error[{exc.code}]: {exc.message}", file=sys.stderr)
        return 4
    if args.harness_command == "validate":
        report = validate_task(task)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0 if report.get("ok") else 1
    attempt = Path(args.attempt)
    try:
        source = decode_source_bytes(attempt.read_bytes())
    except OSError as exc:
        print(f"error: cannot read {attempt}: {exc}", file=sys.stderr)
        return 4
    if args.in_process:
        episode = run_episode(
            task,
            source,
            attempt_id=args.attempt_id,
            seed=args.seed,
            filename=str(attempt),
        )
        full = episode.to_dict()
        shown = agent_view(full) if args.agent_view else full
        sys.stdout.write(json.dumps(shown, ensure_ascii=False, sort_keys=True) + "\n")
        return episode_exit(full)
    text = run_episode_isolated(
        task_dir,
        attempt,
        seed=args.seed,
        attempt_id=args.attempt_id,
        isolation=args.isolation,
    )
    try:
        body = json.loads(text)
    except json.JSONDecodeError:
        if not args.agent_view:
            sys.stdout.write(text)
        return 4
    full = body if isinstance(body, dict) else {}
    if args.agent_view:
        sys.stdout.write(json.dumps(agent_view(full), ensure_ascii=False, sort_keys=True) + "\n")
    else:
        sys.stdout.write(text)
    return episode_exit(full)


def episode_exit(body: dict[str, object]) -> int:
    """Exit status for one harness episode.

    An infrastructure error exits 4. A candidate OS memory kill, OS CPU kill,
    or wall-clock trap exits 2. Any other scored episode, including reward 0,
    exits 0.
    """
    infrastructure = body.get("infrastructure_error")
    if isinstance(infrastructure, dict) and str(infrastructure.get("code", "")).startswith("I"):
        return 4
    codes: set[str] = set()
    diagnostics = body.get("diagnostics")
    if isinstance(diagnostics, list):
        for item in diagnostics:
            if isinstance(item, dict) and isinstance(item.get("code"), str):
                codes.add(item["code"])
    tests = body.get("tests")
    if isinstance(tests, dict):
        cases = tests.get("cases")
        if isinstance(cases, list):
            for case in cases:
                if isinstance(case, dict) and isinstance(case.get("trap"), str):
                    codes.add(case["trap"])
    if codes & {"T6206", "T6207", "T6208"}:
        return 2
    return 0


def _infrastructure_exit(infrastructure: dict[str, str] | None) -> int:
    """Exit 4 is an infrastructure or toolchain error (design §17.3).

    A scored episode, including reward 0, stays exit 0. The harness does not
    encode the reward in the process status.
    """
    if infrastructure and str(infrastructure.get("code", "")).startswith("I"):
        return 4
    return 0


def _print_grammar(kind: str, profile: str) -> int:
    if kind == "gbnf":
        from tersalang.gbnf import generate_gbnf

        try:
            sys.stdout.write(generate_gbnf(profile))
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 4
        except FileNotFoundError as exc:
            print(f"error: {exc} was not found", file=sys.stderr)
            return 4
        return 0
    from tersalang.gbnf import grammar_text

    name = "tersa.lark" if kind == "lark" else "tersa.ebnf"
    try:
        print(grammar_text(name), end="")
    except FileNotFoundError:
        print(f"error: spec/{name} was not found", file=sys.stderr)
        return 4
    return 0


def _warn_fmt_skip(filename: str, text: str) -> None:
    from tersalang.fmt import fmt_skip_warnings

    notes = fmt_skip_warnings(filename, text)
    if notes:
        print(render_all(notes), file=sys.stderr, end="")


def _fmt(files: list[str], check: bool) -> int:
    from tersalang.fmt import FormatError, format_source

    if not files:
        text = sys.stdin.read()
        _warn_fmt_skip("<stdin>", text)
        try:
            formatted = format_source("<stdin>", text)
        except FormatError as exc:
            print(render_all(exc.diagnostics), file=sys.stderr, end="")
            return 3
        if check:
            if formatted != text:
                print("error: input is not formatted", file=sys.stderr)
                return 1
            return 0
        sys.stdout.write(formatted)
        return 0

    status = 0
    for raw in files:
        path = Path(raw)
        if path.is_dir():
            paths = sorted(item for item in path.rglob("*.tersa") if item.is_file())
            for item in paths:
                code = _fmt_one(item, check)
                status = max(status, code)
            continue
        code = _fmt_one(path, check)
        status = max(status, code)
    return status


def _fmt_one(path: Path, check: bool) -> int:
    from tersalang.fmt import FormatError, format_source

    try:
        text = decode_source_bytes(path.read_bytes())
    except OSError as exc:
        print(f"error: cannot read {path}: {exc}", file=sys.stderr)
        return 4
    _warn_fmt_skip(str(path), text)
    try:
        formatted = format_source(str(path), text)
    except FormatError as exc:
        if exc.diagnostics:
            print(render_all(exc.diagnostics), file=sys.stderr, end="")
        else:
            print(f"error: cannot format {path}", file=sys.stderr)
        return 3
    if formatted == text:
        return 0
    if check:
        print(f"would reformat {path}", file=sys.stderr)
        diff = difflib.unified_diff(
            text.splitlines(keepends=True),
            formatted.splitlines(keepends=True),
            fromfile=str(path),
            tofile=str(path),
        )
        shown = 0
        for line in diff:
            if shown >= 40:
                print("...", file=sys.stderr)
                break
            sys.stderr.write(line if line.endswith("\n") else line + "\n")
            shown += 1
        return 1
    try:
        path.write_bytes(formatted.encode("utf-8"))
    except OSError as exc:
        print(f"error: cannot write {path}: {exc}", file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
