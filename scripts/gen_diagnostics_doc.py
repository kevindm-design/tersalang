# SPDX-License-Identifier: Apache-2.0
r"""Write docs/diagnostics.md from spec/diagnostics.yaml and conformance/.

Every diagnostic's `docs_url` points at a `### CODE` heading in that file.
GitHub anchors a heading by its lowercased text, so `E3045` is `#e3045`.

A code's wrong example is a conformance program that expects it. A program
with `# fixed: OLD => NEW` header lines also has a fixed example: each edit
replaces the first occurrence of OLD, in order, where `\n` is a line break
and `\\` a backslash. `tests/test_conformance.py` checks that every fixed
program is clean. `# no-fix: REASON` says why a program has no fixed form.
A `harness-error` program names its task interface in an `# interface: FILE`
header, and the doc shows that file too.
`--check` exits 1 when the committed file is stale.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

from tersalang.diagnostics import category_for, severity_for

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "spec" / "diagnostics.yaml"
TARGET = ROOT / "docs" / "diagnostics.md"
CONFORMANCE = ROOT / "conformance"

EXPECT = re.compile(r"# expect: (\S+) ([EWTI][0-9]{4})\s*$")
HIDDEN_KEYS = ("# spec:", "# expect:", "# fixed:", "# no-fix:", "# interface:")
KINDS = {
    "check-error": "`tersa check` reports it",
    "check-warn": "`tersa check` warns",
    "harness-error": "`tersa harness run` reports it against the task interface below",
    "run-error": "`tersa run` refuses to start",
    "trap": "`tersa run` traps",
    "run-note": "`tersa run` reports it",
    "test-fail": "`tersa test` fails",
}
BYTE_LEVEL = {"\ufeff": "a byte-order mark", "\t": "a tab", "\r": "a carriage return"}
INLINE_LIMIT = 2000
NO_PROGRAM = {
    "I": "It comes from the host, the harness, or the task loader, not from a program, "
    "so there is no program example. Unit tests under `tests/unit/` raise it.",
    "T620": "It comes from an OS limit or the wall clock on the harness child, not from the "
    "program text, so there is no program example. See `docs/harness.md`.",
}


@dataclass
class Example:
    """A conformance program that expects a code, with its fix edits and no-fix reason."""

    path: Path
    kind: str
    text: str
    fixes: list[tuple[str, str]]
    no_fix: str | None
    utf8: bool = True


def decode_edit(text: str) -> str:
    """One side of a `# fixed:` edit with its two escapes decoded."""
    out: list[str] = []
    index = 0
    while index < len(text):
        pair = text[index : index + 2]
        if pair == "\\\\":
            out.append("\\")
            index += 2
        elif pair == "\\n":
            out.append("\n")
            index += 2
        else:
            out.append(text[index])
            index += 1
    return "".join(out)


def fix_edits(text: str) -> list[tuple[str, str]]:
    """The `(old, new)` pairs of every `# fixed: OLD => NEW` line, in order."""
    edits: list[tuple[str, str]] = []
    for line in text.splitlines():
        if not line.startswith("# fixed: "):
            continue
        old, sep, new = line[len("# fixed: ") :].partition(" =>")
        assert sep, f"`# fixed:` needs ` => `: {line}"
        edits.append((decode_edit(old), decode_edit(new[1:] if new.startswith(" ") else new)))
    return edits


def apply_fixes(text: str, edits: list[tuple[str, str]]) -> str:
    """The fixed program: header edit lines removed, then each edit applied once."""
    kept = [line for line in text.splitlines(keepends=True) if not line.startswith("# fixed: ")]
    fixed = "".join(kept)
    for old, new in edits:
        assert old in fixed, f"`# fixed:` text not found: {old!r}"
        fixed = fixed.replace(old, new, 1)
    return fixed


def shown(text: str) -> str:
    """The program as the doc shows it, without the header lines in `HIDDEN_KEYS`."""
    lines = [line for line in text.splitlines() if not line.startswith(HIDDEN_KEYS)]
    return "\n".join(lines).strip("\n")


def examples(root: Path = CONFORMANCE) -> dict[str, Example]:
    """The example program for each code that some program under `root` expects.

    Only the first 12 lines are read as headers. A program with a fix is
    preferred, then one with a `# no-fix:` reason, then one named after the
    code, then the shortest.
    """
    found: dict[str, list[Example]] = {}
    for path in sorted(root.rglob("*.tersa")):
        raw = path.read_bytes()
        utf8 = True
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text, utf8 = raw.decode("latin-1"), False
        head = text.lstrip("\ufeff").replace("\r", "\n").splitlines()[:12]
        for line in head:
            match = EXPECT.match(line)
            if match is None or match.group(1) not in KINDS:
                continue
            no_fix = next(
                (item[len("# no-fix: ") :] for item in head if item.startswith("# no-fix: ")), None
            )
            found.setdefault(match.group(2), []).append(
                Example(path, match.group(1), text, fix_edits(text), no_fix, utf8)
            )
    chosen: dict[str, Example] = {}
    for code, items in found.items():

        def rank(item: Example, code: str = code) -> tuple[int, int, int, str]:
            stem = item.path.stem.lower()
            return (
                0 if item.fixes else 1 if item.no_fix else 2,
                0 if stem == code.lower() else 1 if stem.startswith(code.lower()) else 2,
                len(item.text),
                item.path.as_posix(),
            )

        chosen[code] = min(items, key=rank)
    return chosen


def _example_lines(code: str, entry: dict[str, object], example: Example | None) -> list[str]:
    if example is None:
        if entry.get("reserved"):
            return []
        for prefix, reason in NO_PROGRAM.items():
            if code.startswith(prefix):
                return [f"No wrong or fixed example. {reason}", ""]
        return ["No wrong or fixed example: no conformance program produces it.", ""]
    rel = example.path.relative_to(ROOT).as_posix()
    lines = [f"Wrong ([`{rel}`](../{rel}), {KINDS[example.kind]}):", ""]
    special = next((name for char, name in BYTE_LEVEL.items() if char in example.text), None)
    if not example.utf8:
        special = "bytes that are not UTF-8"
    if special is not None:
        lines += [f"The program contains {special}, so it is not shown here. Open the file.", ""]
    elif len(example.text) > INLINE_LIMIT:
        lines += [
            f"The program is {len(example.text)} bytes, so it is not shown here. Open the file.",
            "",
        ]
    else:
        lines += ["```tersa", shown(example.text), "```", ""]
    interface = next(
        (
            line[len("# interface: ") :].strip()
            for line in example.text.splitlines()
            if line.startswith("# interface: ")
        ),
        None,
    )
    if interface is not None:
        path = (example.path.parent / interface).relative_to(ROOT).as_posix()
        text = (ROOT / path).read_text(encoding="utf-8")
        lines += [
            f"Task interface ([`{path}`](../{path})):",
            "",
            "```tersa",
            shown(text),
            "```",
            "",
        ]
    if example.fixes and special is None:
        lines += [
            "Fixed:",
            "",
            "```tersa",
            shown(apply_fixes(example.text, example.fixes)),
            "```",
            "",
        ]
    elif example.no_fix:
        lines += [f"No fixed example: {example.no_fix}", ""]
    else:
        lines += ["No fixed example.", ""]
    return lines


def render(catalog: dict[str, object], found: dict[str, Example] | None = None) -> str:
    """The text of docs/diagnostics.md for the parsed `catalog`."""
    codes = catalog["codes"]
    assert isinstance(codes, dict)
    found = examples() if found is None else found
    fixed = sum(1 for code in codes if code in found and found[code].fixes)
    lines = [
        "# Diagnostic codes",
        "",
        "<!-- Generated from spec/diagnostics.yaml and conformance/ by scripts/gen_diagnostics_doc.py. Do not edit. -->",
        "",
        f"Schema `{catalog['schema']}`. {len(codes)} codes. The `docs_url` of every diagnostic points at its heading here.",
        "",
        f"A wrong example is a conformance program that produces the code ({sum(1 for code in codes if code in found)} codes). "
        f"A fixed example is that program after the edits in its `# fixed:` header lines ({fixed} codes); "
        "`tests/test_conformance.py` checks that each one is clean. Codes with neither say why.",
        "",
    ]
    for code in sorted(codes):
        entry = codes[code]
        assert isinstance(entry, dict)
        lines += [f"### {code}", "", str(entry["message"]), ""]
        facts = f"Severity `{severity_for(code)}`, category `{category_for(code)}`."
        if entry.get("reserved"):
            facts += " Reserved: never emitted."
        lines += [facts, ""]
        if entry.get("note"):
            lines += [str(entry["note"]), ""]
        lines += _example_lines(code, entry, found.get(code))
    return "\n".join(lines).rstrip("\n") + "\n"


def main(argv: list[str]) -> int:
    """Write docs/diagnostics.md, or with `--check` exit 1 when it is stale."""
    text = render(yaml.safe_load(SOURCE.read_text(encoding="utf-8")))
    if "--check" in argv:
        if TARGET.read_text(encoding="utf-8") != text:
            print(
                "docs/diagnostics.md is stale: run scripts/gen_diagnostics_doc.py", file=sys.stderr
            )
            return 1
        return 0
    TARGET.write_bytes(text.encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
