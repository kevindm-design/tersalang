# SPDX-License-Identifier: Apache-2.0
"""Run both GBNF profiles through llama.cpp's own grammar engine.

Usage: uv run python scripts/check_gbnf_llama.py PATH/TO/test-gbnf-validator

`test-gbnf-validator` is built from llama.cpp's `tests/` directory. It parses
the grammar with llama.cpp's GBNF parser and feeds the input one code point at
a time through `llama_grammar_accept`, the same matcher the sampler uses. It
needs no model.

Checks, for each profile:

- the grammar loads;
- every corpus program the hand parser accepts is valid (`full`), and every
  `tersa fmt` result is valid (`decoding`, except `# fmt: skip` files);
- on the corpus and on broken variants of it, llama.cpp and
  `tersalang.gbnf.gbnf_accepts` give the same verdict (inputs up to 4,096
  characters);
- llama.cpp gives the required verdict on each side of the comment caps
  (`tersalang.gbnf.cap_cases`: the 100-line header, 30 lines after code,
  500 characters per comment);
- no input takes longer than the timeout.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from tersalang.fmt import FormatError, format_source
from tersalang.gbnf import cap_cases, gbnf_accepts, generate_gbnf, repo_root
from tersalang.lexer import lex_text
from tersalang.parser import parse_module
from tersalang.source import decode_source_bytes

VALID = "Input string is valid according to the grammar."
INVALID = "Input string is invalid according to the grammar."
# The Python recognizer memoizes end positions per (rule, offset), which is
# quadratic in memory on a single very long token (conformance/lex/int_cap).
RECOGNIZER_MAX_CHARS = 4096


def _parses(name: str, text: str) -> bool:
    source, tokens, diagnostics = lex_text(name, text)
    module = parse_module(source, tokens, diagnostics)
    return module is not None and not any(item.severity == "error" for item in diagnostics)


def _broken(text: str) -> list[str]:
    """Damage `text` three deterministic ways.

    The variants drop the last `end`, unbalance a parenthesis, and cut the
    file in half.
    """
    variants = []
    cut = text.rfind("end")
    if cut >= 0:
        variants.append(text[:cut] + text[cut + 3 :])
    paren = text.find("(")
    if paren >= 0:
        variants.append(text[:paren] + text[paren + 1 :])
    variants.append(text[: len(text) // 2])
    return variants


class Validator:
    """Runs llama.cpp's `test-gbnf-validator` on files in `workdir` and keeps the slowest."""

    def __init__(self, binary: Path, workdir: Path, timeout: float, *, verbose: bool) -> None:
        self.verbose = verbose
        self.binary = binary
        self.workdir = workdir
        self.timeout = timeout
        self.slowest = (0.0, "")

    def load(self, grammar: str, name: str) -> Path:
        """Write `grammar` to `workdir` as `name.gbnf` and return its path."""
        path = self.workdir / f"{name}.gbnf"
        path.write_text(grammar, encoding="utf-8", newline="\n")
        return path

    def accepts(self, grammar: Path, text: str, label: str) -> bool:
        """The validator's verdict on `text`; any other output raises `RuntimeError`.

        A run over the timeout raises `subprocess.TimeoutExpired`.
        """
        if self.verbose:
            print(label, flush=True)
        source = self.workdir / "input.tersa"
        source.write_bytes(text.encode("utf-8", errors="surrogateescape"))
        started = time.monotonic()
        result = subprocess.run(
            [str(self.binary), str(grammar), str(source)],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=self.timeout,
            check=False,
        )
        elapsed = time.monotonic() - started
        if elapsed > self.slowest[0]:
            self.slowest = (elapsed, label)
        first = result.stdout.splitlines()[0] if result.stdout else ""
        if first == VALID:
            return True
        if first == INVALID:
            return False
        raise RuntimeError(
            f"{label}: validator said {result.stdout[:200]!r} (exit {result.returncode})"
        )


def main() -> int:
    """Run every check in the module docstring; 1 when any of them fails."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("validator", type=Path, help="path to llama.cpp's test-gbnf-validator")
    parser.add_argument("--timeout", type=float, default=20.0, help="seconds per input")
    parser.add_argument(
        "--verbose", action="store_true", help="print each input before checking it"
    )
    args = parser.parse_args()

    root = repo_root()
    programs = sorted((root / "conformance").rglob("*.tersa")) + sorted(
        (root / "examples").rglob("*.tersa")
    )
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        validator = Validator(args.validator, Path(tmp), args.timeout, verbose=args.verbose)
        for profile in ("full", "decoding"):
            grammar_text = generate_gbnf(profile)
            grammar = validator.load(grammar_text, profile)
            required = accepted = agreed = compared = skipped = rejected = 0
            for path in programs:
                rel = path.relative_to(root).as_posix()
                text = decode_source_bytes(path.read_bytes())
                if profile == "full":
                    must_accept = text if _parses(rel, text) else None
                    samples = [text]
                elif any(line.strip() == "# fmt: skip" for line in text.splitlines()):
                    must_accept = None
                    samples = [text]
                else:
                    try:
                        must_accept = format_source(rel, text)
                    except FormatError:
                        must_accept = None
                    samples = [text] + ([must_accept] if must_accept is not None else [])
                if must_accept is not None:
                    required += 1
                    if validator.accepts(grammar, must_accept, f"{profile} {rel}"):
                        accepted += 1
                    else:
                        failures.append(f"{profile}: llama.cpp rejects valid {rel}")
                for index, sample in enumerate(samples + _broken(samples[-1])):
                    label = f"{profile} {rel} sample {index}"
                    if len(sample) > RECOGNIZER_MAX_CHARS:
                        skipped += 1
                        continue
                    try:
                        native = validator.accepts(grammar, sample, label)
                    except subprocess.TimeoutExpired:
                        failures.append(f"{label}: llama.cpp took longer than {args.timeout}s")
                        continue
                    compared += 1
                    rejected += not native
                    if native == gbnf_accepts(grammar_text, sample):
                        agreed += 1
                    else:
                        failures.append(
                            f"{label}: llama.cpp says {native}, the Python recognizer disagrees"
                        )
            caps = cap_cases()
            caps_right = 0
            for label, text, expected in caps:
                native = validator.accepts(grammar, text, f"{profile} cap: {label}")
                if native is not expected:
                    failures.append(
                        f"{profile}: llama.cpp says {native} on the cap case {label!r}, expected {expected}"
                    )
                elif gbnf_accepts(grammar_text, text) is not expected:
                    failures.append(
                        f"{profile}: the Python recognizer is wrong on the cap case {label!r}"
                    )
                else:
                    caps_right += 1
            print(
                f"{profile}: {caps_right}/{len(caps)} comment-cap cases right; "
                f"{accepted}/{required} valid programs accepted; "
                f"llama.cpp and the Python recognizer agree on {agreed}/{compared} inputs, "
                f"{rejected} of them rejected "
                f"({skipped} over {RECOGNIZER_MAX_CHARS} characters not compared)"
            )
        seconds, label = validator.slowest
        print(f"slowest input: {seconds:.2f}s ({label})")
    for failure in failures:
        print(failure, file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
