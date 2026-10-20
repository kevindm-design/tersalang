# SPDX-License-Identifier: Apache-2.0
"""`JsonNull` is unknown to `check` and `run` alike."""

from __future__ import annotations

import json

import pytest

from tersalang.driver import check_text, run_text

JSON_NULL = """module jn

function main() returns Unit
do
  let _ = JsonNull
  return
end
"""


def test_check_and_run_report_json_null_identically() -> None:
    checked = check_text("jn.tersa", JSON_NULL, as_json=True)
    ran = run_text("jn.tersa", JSON_NULL, as_json=True)
    assert checked.exit_code == ran.exit_code == 3
    assert checked.stdout == ran.stdout
    (diagnostic,) = json.loads(checked.stdout)
    assert diagnostic["code"] == "E2000"
    assert diagnostic["message"] == "unknown name `JsonNull`"
    assert diagnostic["span"]["start"] == {"line": 5, "column": 11}


@pytest.mark.parametrize("spelling", ["Null", "Json.Null"])
def test_the_json_null_spellings_check_and_run(spelling: str) -> None:
    src = JSON_NULL.replace("JsonNull", spelling)
    assert check_text("jn.tersa", src).exit_code == 0
    assert run_text("jn.tersa", src).exit_code == 0
