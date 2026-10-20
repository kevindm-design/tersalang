# SPDX-License-Identifier: Apache-2.0
"""Every diagnostic code is either exercised or listed as a real gap."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import yaml

from tersalang.diagnostics import EXTRA_CODES
from tersalang.driver import validate_limits
from tersalang.limits import LimitConfig
from tersalang.source import decode_source_bytes

ROOT = Path(__file__).resolve().parents[2]
CODE = re.compile(r"\b([EWTI][0-9]{4})\b")

# These codes are defined, but a conformance program cannot produce them yet.
GAPS = {
    "E2101": "No lockfile reader. tests/unit/test_deferred_diagnostics.py skips it.",
    "T6012": (
        "Safety net. Checked programs cannot reach a closed resource "
        "(E3072, and using closes the file after the body). "
        "tests/unit/test_deferred_diagnostics.py calls file.read_line on a "
        "closed resource and expects T6012. No .tersa expect."
    ),
    "I9011": (
        "The catalog and the language reference agree: the Unicode version "
        "does not match the language pin. No pin is implemented "
        "(version.UNICODE_NOTE is host-unicodedata), so nothing emits I9011."
    ),
}


def _catalog() -> dict[str, dict[str, object]]:
    loaded = yaml.safe_load((ROOT / "spec" / "diagnostics.yaml").read_text(encoding="utf-8"))
    codes = loaded["codes"]
    assert isinstance(codes, dict)
    return codes


def _suite_codes() -> set[str]:
    found: set[str] = set()
    for path in (ROOT / "conformance").rglob("*.tersa"):
        text = decode_source_bytes(path.read_bytes()).lstrip("\ufeff")
        for line in text.splitlines():
            if not line.startswith("#"):
                continue
            body = line[1:].strip()
            if body.startswith("expect:"):
                found.update(CODE.findall(body))
    return found


def _emitted_codes() -> set[str]:
    found: set[str] = set()
    for path in (ROOT / "src" / "tersalang").rglob("*.py"):
        found.update(CODE.findall(path.read_text(encoding="utf-8")))
    return found


def test_catalog_codes_are_covered_or_listed() -> None:
    catalog = _catalog()
    reserved = {code for code, entry in catalog.items() if entry.get("reserved") is True}
    for code in reserved:
        note = catalog[code].get("note")
        assert isinstance(note, str) and note.strip(), code
    codes = set(catalog)
    # Host and task-load codes. A .tersa program cannot produce them.
    covered = _suite_codes() | {
        "I9010",
        "I9013",
        "I9014",
        "I9015",
        "I9016",
        "I9017",
        "I9018",
        "I9019",
        "I9020",
        "I9021",
        "I9022",
        "I9024",
        "I9025",
        # OS and candidate wall-clock traps. A .tersa program cannot raise them.
        "T6206",
        "T6207",
        "T6208",
    }
    missing = sorted(codes - reserved - covered - set(GAPS))
    assert missing == []
    stale = sorted(set(GAPS) - codes)
    assert stale == []
    now_covered = sorted(set(GAPS) & covered)
    assert now_covered == []
    retired = sorted(reserved & (covered | set(GAPS)))
    assert retired == []


def test_emitted_codes_are_listed_and_live() -> None:
    """An emitted code must be in the catalog, and a reserved code must not be emitted."""
    catalog = _catalog()
    reserved = {code for code, entry in catalog.items() if entry.get("reserved") is True}
    emitted = _emitted_codes()
    unknown = sorted(emitted - set(catalog))
    assert unknown == []
    retired = sorted(emitted & reserved)
    assert retired == []


def _literal_codes() -> set[str]:
    """Codes that appear as a whole string literal in source, not in comments or docstrings."""
    found: set[str] = set()
    for path in (ROOT / "src" / "tersalang").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if re.fullmatch(r"[EWTI][0-9]{4}", node.value):
                    found.add(node.value)
    return found


def test_live_codes_are_emitted_or_marked_not_implemented() -> None:
    catalog = _catalog()
    literals = _literal_codes()
    for code, entry in catalog.items():
        if entry.get("reserved") is True:
            continue
        note = str(entry.get("note") or "")
        if code not in literals:
            assert note.startswith("Not implemented."), code
    for code in ("I9011", "E2101"):
        assert str(catalog[code].get("note", "")).startswith("Not implemented."), code


def test_extra_code_titles_match_the_catalog() -> None:
    catalog = _catalog()
    for code, title in EXTRA_CODES.items():
        assert catalog[code]["message"] == title, code


def test_i9010_rejects_a_zero_fuel_limit() -> None:
    diagnostic = validate_limits(LimitConfig(fuel=0))
    assert diagnostic is not None
    assert diagnostic.code == "I9010"


def test_docs_url_points_at_a_heading_of_the_generated_catalog() -> None:
    import importlib.util

    from tersalang.diagnostics import DOCS_BASE, docs_url

    path = ROOT / "scripts" / "gen_diagnostics_doc.py"
    spec = importlib.util.spec_from_file_location("gen_diagnostics_doc", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    committed = (ROOT / "docs" / "diagnostics.md").read_text(encoding="utf-8")
    assert committed == module.render(
        yaml.safe_load((ROOT / "spec" / "diagnostics.yaml").read_text(encoding="utf-8"))
    )
    assert DOCS_BASE.endswith("/docs/diagnostics.md")
    headings = {line[4:] for line in committed.splitlines() if line.startswith("### ")}
    assert headings == set(_catalog())
    for code in _catalog():
        assert docs_url(code) == f"{DOCS_BASE}#{code.lower()}"


def test_language_reference_appendix_b_mirrors_the_catalog() -> None:
    rows: dict[str, tuple[str, str]] = {}
    text = (ROOT / "spec" / "language-reference.md").read_text(encoding="utf-8")
    for line in text.splitlines():
        match = re.match(r"\| ([EWTI][0-9]{4}) \| ([^|]*) \| ([^|]*) \|", line)
        if match:
            rows.setdefault(match.group(1), (match.group(2).strip(), match.group(3).strip()))
    catalog = _catalog()
    assert set(rows) == set(catalog)
    for code, entry in catalog.items():
        status, message = rows[code]
        assert message == entry["message"], code
        assert ("RESERVED" in status) == bool(entry.get("reserved")), code
