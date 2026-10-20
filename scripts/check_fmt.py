# SPDX-License-Identifier: Apache-2.0
"""Check layout for every corpus file the formatter can read.

`tersa fmt conformance` exits 3. That tree holds fixtures that are supposed
to fail lexing or parsing, and a directory reports each of them. This gate
passes the other files to `tersa fmt --check`. A `# fmt: skip` file is
still parsed: if that parse fails, the diagnostic is printed and the gate
exits 3.
"""

from __future__ import annotations

import sys
from pathlib import Path

from tersalang.cli import main
from tersalang.diagnostics import render_all
from tersalang.fmt import FormatError, format_source, is_fmt_skip
from tersalang.source import decode_source_bytes


def corpus_files(root: Path) -> tuple[list[str], int]:
    """The conformance and example files that parse, and the exit status so far.

    A file that does not parse is left out. When it is a `# fmt: skip` file its
    diagnostic is printed and the status is 3.
    """
    found: list[str] = []
    status = 0
    for directory in (root / "conformance", root / "examples"):
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.tersa")):
            text = decode_source_bytes(path.read_bytes())
            try:
                format_source(str(path), text)
            except FormatError as exc:
                if is_fmt_skip(text):
                    if exc.diagnostics:
                        print(render_all(exc.diagnostics), file=sys.stderr, end="")
                    else:
                        print(f"error: cannot format {path}", file=sys.stderr)
                    status = 3
                continue
            found.append(str(path))
    return found, status


def main_script() -> int:
    """Run `tersa fmt --check` on the formattable corpus; 4 when there is nothing to check."""
    root = Path(__file__).resolve().parents[1]
    files, status = corpus_files(root)
    if not files and status == 0:
        print("no formattable corpus files", file=sys.stderr)
        return 4
    check = main(["fmt", "--check", *files]) if files else 0
    return max(status, check)


if __name__ == "__main__":
    raise SystemExit(main_script())
