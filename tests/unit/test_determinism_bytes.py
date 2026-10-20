# SPDX-License-Identifier: Apache-2.0
"""Determinism output is stable in one process and uses LF only."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _dump():
    path = ROOT / "scripts" / "determinism_dump.py"
    spec = importlib.util.spec_from_file_location("determinism_dump", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.dump_bytes()


def test_determinism_dump_is_stable_lf_bytes() -> None:
    first = _dump()
    second = _dump()
    assert first == second
    assert b"\r" not in first
    assert first == (
        b"det_clock.tersa\n0\n0\n1\n"
        b"det_div.tersa\n-3\n2\n0.5\n"
        b"det_random.tersa\n5\n0\n"
        b"harness:add_one\n"
        b'{"attempt_diagnostics":0,"attempt_id":"reference","breakdown":{"C":1.0,"E":1.0,"E_basis":"reference","E_basis_reason":null,"ref_fuel":88,"w":0.1},'
        b'"contracts":{"task_spec_violations":0},"crash":null,'
        b'"diagnostics":[],"infrastructure_error":null,"isolation":"none","isolation_warning":null,"replay":{"seed":0,'
        b'"source_hash":"sha256:424f33538027bb257be1ff798d1c5839b82cb1741c79752d2c503d940d3fe9d7",'
        b'"task_hash":"sha256:6ee053ec7ef5f33b9767ee9e9539978f48ec5883b1825888efcb10cb24226098"},'
        b'"resources":{"fuel_limit":100000,"fuel_used":88,"limit_hit":null,'
        b'"memory_units_limit":100000,"memory_units_used":0},"reward":1.0,'
        b'"schema":"tersa.result/0.9","stage_reached":"run","stdout":"","task_id":"add_one",'
        b'"tests":{"cases":[{"fuel":16,"id":"h_forty_one","status":"passed"},'
        b'{"fuel":72,"id":"h_property","status":"passed"}],"failed":0,"passed":2,"total":2,'
        b'"trapped":0},"toolchain":{"language":"0.1","platform":"platform","python":"python",'
        b'"tersalang":"0.1.0"},"visible_tests":{"passed":1,"total":1}}\n'
    )
