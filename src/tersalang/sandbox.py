# SPDX-License-Identifier: Apache-2.0
"""Language-level sandbox. The host decides every limit and every grant."""

from __future__ import annotations

from tersalang.driver import RL_DENIED_EFFECTS, Outcome, run_text, validate_limits
from tersalang.limits import LimitConfig
from tersalang.version import (
    DEFAULT_SANDBOX_FUEL,
    DEFAULT_SANDBOX_MEMORY,
    DEFAULT_SANDBOX_WALL_MS,
    DEFAULT_TEST_OUTPUT_BYTES,
)

__all__ = ["RL_DENIED_EFFECTS", "run_sandboxed", "sandbox_limits"]


def sandbox_limits() -> LimitConfig:
    """Finite defaults for `tersa sandbox`. Flags override these one at a time."""
    return LimitConfig(
        fuel=DEFAULT_SANDBOX_FUEL,
        memory_units=DEFAULT_SANDBOX_MEMORY,
        output_bytes=DEFAULT_TEST_OUTPUT_BYTES,
        wall_ms=DEFAULT_SANDBOX_WALL_MS,
    )


def run_sandboxed(
    filename: str,
    text: str,
    *,
    limits: LimitConfig | None = None,
    grants: dict[str, list[str]] | None = None,
    seed: int = 0,
    stdin: str = "",
    args: tuple[str, ...] = (),
    env: dict[str, str] | None = None,
) -> Outcome:
    """Run one program in RL mode with only the grants and limits given here.

    There is no ambient file, clock, random, env, or console access. With no
    `limits` argument the sandbox uses `sandbox_limits`. A wall-clock limit is
    `I9013` and stops the run. Fuel, memory, depth, and the integer cap stay
    ordinary deterministic traps.
    """
    config = sandbox_limits() if limits is None else limits
    invalid = validate_limits(config)
    if invalid is not None:
        return Outcome(4, diagnostics=[invalid])
    return run_text(
        filename,
        text,
        mode="rl",
        grants=grants or {},
        seed=seed,
        limits=config,
        args=args,
        env=env or {},
        stdin=stdin,
    )
