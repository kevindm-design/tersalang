# SPDX-License-Identifier: Apache-2.0
"""`T6204` names its limit `max_int_bits`, whichever operation hits the cap."""

from __future__ import annotations

import json

import pytest

from tersalang.driver import run_text
from tersalang.limits import LimitConfig


@pytest.mark.parametrize(
    "expr",
    [
        "1180591620717411303424",
        "9223372036854775807 * 9223372036854775807",
        'Int.parse("1180591620717411303424").unwrap_or(0)',
    ],
    ids=["literal", "multiply", "parse"],
)
def test_int_cap_trap_values_use_the_limit_name(expr: str) -> None:
    src = f"""module cap

function main() returns Unit
do
  let _ = {expr}
  return
end
"""
    outcome = run_text("cap.tersa", src, limits=LimitConfig(max_int_bits=64), as_json=True)
    assert outcome.exit_code == 2, outcome.stdout
    (trap,) = json.loads(outcome.stdout)
    assert trap["code"] == "T6204"
    assert trap["values"] == {"max_int_bits": "64"}
