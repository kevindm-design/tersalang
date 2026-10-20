# SPDX-License-Identifier: Apache-2.0
"""Fail when spec/tersa.gbnf differs from a fresh generation."""

from __future__ import annotations

import sys

from tersalang.gbnf import generate_gbnf, repo_root


def main() -> int:
    """0 when `spec/tersa.gbnf` is current and has no lookahead, else 1 with a hint."""
    path = repo_root() / "spec" / "tersa.gbnf"
    expected = generate_gbnf("full").replace("\r\n", "\n")
    actual = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    if "(!" in actual or "(!" in expected:
        print("spec/tersa.gbnf uses lookahead. Stock llama.cpp GBNF does not.", file=sys.stderr)
        return 1
    if actual == expected:
        return 0
    print("spec/tersa.gbnf does not match `tersa grammar --format gbnf`.", file=sys.stderr)
    print("Regenerate it with:", file=sys.stderr)
    print(
        "  uv run python -c \"from tersalang.gbnf import generate_gbnf; open('spec/tersa.gbnf','w',encoding='utf-8',newline='\\n').write(generate_gbnf('full'))\"",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
