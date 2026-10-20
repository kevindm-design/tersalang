# SPDX-License-Identifier: Apache-2.0
r"""Write one LF byte string for every program in conformance/determinism/.

CI compares this file across Linux, macOS, and Windows. Print uses `\n` inside
the evaluator, and this script writes bytes, so the host newline does not leak in.
"""

from __future__ import annotations

import sys
from pathlib import Path

from tersalang.driver import run_text
from tersalang.harness import canonical_bytes, load_task, run_episode

ROOT = Path(__file__).resolve().parents[1]


def _grants(text: str) -> dict[str, list[str]]:
    grants: dict[str, list[str]] = {}
    for line in text.splitlines():
        if not line.startswith("#"):
            continue
        body = line[1:].strip()
        if not body.startswith("allow:"):
            continue
        item = body.split(":", 1)[1].strip()
        if "=" in item:
            effect, scope = item.split("=", 1)
            grants.setdefault(effect, []).append(scope)
        else:
            grants.setdefault(item, [])
    return grants


def dump_bytes() -> bytes:
    """Each determinism program's name and stdout, then the `add_one` reference episode.

    The episode is `canonical_bytes`, so the host's Python version and platform
    do not appear. Any program that does not exit 0 stops the dump.
    """
    chunks: list[bytes] = []
    paths = sorted((ROOT / "conformance" / "determinism").glob("*.tersa"))
    if not paths:
        raise SystemExit("no determinism programs")
    for path in paths:
        text = path.read_bytes().decode("utf-8")
        outcome = run_text(path.name, text, grants=_grants(text), seed=0)
        if outcome.exit_code != 0:
            raise SystemExit(f"{path.name} exited {outcome.exit_code}\n{outcome.stderr}")
        stdout = outcome.stdout.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
        if stdout and not stdout.endswith(b"\n"):
            stdout += b"\n"
        chunks.append(path.name.encode("ascii") + b"\n" + stdout)
    task = load_task(ROOT / "examples" / "tasks" / "add_one")
    episode = run_episode(
        task,
        task.reference_text,
        attempt_id="reference",
        seed=0,
        filename="reference/solution.tersa",
    )
    if episode.correctness != 1.0 or episode.reward is None:
        raise SystemExit(
            f"add_one reference reward {episode.reward} correctness {episode.correctness}"
        )
    chunks.append(b"harness:add_one\n" + canonical_bytes(episode))
    return b"".join(chunks)


def main() -> None:
    """Write `dump_bytes` to the path given as the only argument."""
    if len(sys.argv) != 2:
        raise SystemExit("usage: determinism_dump.py OUTPUT")
    Path(sys.argv[1]).write_bytes(dump_bytes())


if __name__ == "__main__":
    main()
