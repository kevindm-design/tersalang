# SPDX-License-Identifier: Apache-2.0
"""Diagnostics. JSON is the stable form; human text is rendered from it."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from tersalang.source import Span
from tersalang.version import DIAGNOSTIC_SCHEMA

DOCS_BASE = "https://github.com/kevindm-design/tersalang/blob/main/docs/diagnostics.md"


def docs_url(code: str) -> str:
    """The `### CODE` heading of docs/diagnostics.md; GitHub lowercases heading anchors."""
    return f"{DOCS_BASE}#{code.lower()}"


def category_for(code: str) -> str:
    """The category a code's prefix selects, such as `type` for `E3...`; unknown is `syntax`."""
    if code.startswith(("E00", "W00")):
        return "lexical"
    if code.startswith(("E1", "W1")):
        return "syntax"
    if code.startswith(("E2", "W2")):
        return "name"
    if code.startswith(("E3", "W3")):
        return "type"
    if code.startswith(("E4", "W4")):
        return "effect"
    if code.startswith(("E5", "W5")):
        return "contract"
    if code.startswith("T61"):
        return "contract"
    if code.startswith(("T62", "W62")):
        return "limit"
    if code.startswith("T63"):
        return "capability"
    if code.startswith("T64"):
        return "interop"
    if code.startswith("T"):
        return "runtime"
    if code.startswith("I"):
        return "infrastructure"
    return "syntax"


def severity_for(code: str) -> str:
    """`warning` for a `W` code, `info` for an `I` code, and `error` for `E` and `T` codes."""
    if code.startswith("W"):
        return "warning"
    if code.startswith("I"):
        return "info"
    return "error"


@dataclass
class Related:
    """A second location that explains a diagnostic, such as an earlier declaration."""

    message: str
    file: str
    span: Span

    def to_json(self) -> dict[str, object]:
        """The JSON object for one entry of a diagnostic's `related` list."""
        return {"message": self.message, "file": self.file, "span": self.span.to_json()}


@dataclass
class FixEdit:
    """One machine-applicable edit: `insert` replaces the text in `span`."""

    span: Span
    insert: str

    def to_json(self) -> dict[str, object]:
        """The JSON object for one entry of a fix's `edits` list."""
        return {"span": self.span.to_json(), "insert": self.insert}


@dataclass
class Fix:
    """A suggested fix: a description and optional edits."""

    description: str
    edits: list[FixEdit] = field(default_factory=list)

    def to_json(self) -> dict[str, object]:
        """The JSON object for a diagnostic's `fix`; `edits` is omitted when empty."""
        payload: dict[str, object] = {"description": self.description}
        if self.edits:
            payload["edits"] = [edit.to_json() for edit in self.edits]
        return payload


@dataclass
class Diagnostic:
    """One reported problem, trap, or note.

    `severity` and `category` default to what the code's prefix implies.
    """

    code: str
    message: str
    file: str
    span: Span
    related: list[Related] = field(default_factory=list)
    blame: str | None = None
    values: dict[str, str] | None = None
    fix: Fix | None = None
    severity: str | None = None
    category: str | None = None

    def __post_init__(self) -> None:
        if self.severity is None:
            self.severity = severity_for(self.code)
        if self.category is None:
            self.category = category_for(self.code)

    def to_json(self) -> dict[str, object]:
        """The stable JSON form, tagged with `DIAGNOSTIC_SCHEMA`."""
        return {
            "schema": DIAGNOSTIC_SCHEMA,
            "code": self.code,
            "severity": self.severity,
            "category": self.category,
            "message": self.message,
            "file": self.file,
            "span": self.span.to_json(),
            "related": [item.to_json() for item in self.related],
            "blame": self.blame,
            "values": self.values,
            "fix": None if self.fix is None else self.fix.to_json(),
            "docs_url": docs_url(self.code),
        }

    def to_json_text(self) -> str:
        """`to_json` as compact JSON text on one line."""
        return json.dumps(self.to_json(), ensure_ascii=False, separators=(",", ":"))

    def render(self) -> str:
        """The human-readable text, headed `trap[...]` for a `T` code; no trailing newline."""
        kind = "trap" if self.code.startswith("T") else self.severity
        lines = [
            f"{kind}[{self.code}]: {self.message}",
            f"  --> {self.file}:{self.span.start_line}:{self.span.start_col}",
        ]
        for item in self.related:
            location = f"{item.file}:{item.span.start_line}:{item.span.start_col}"
            lines.append(f"  = {item.message} ({location})")
        if self.blame is not None:
            lines.append(f"  = blame: {self.blame}")
        if self.values:
            for name, value in self.values.items():
                lines.append(f"  = {name} = {value}")
        if self.fix is not None:
            lines.append(f"  = fix: {self.fix.description}")
        return "\n".join(lines)


def render_all(diagnostics: list[Diagnostic]) -> str:
    """Every diagnostic rendered, separated by a blank line and ending in a newline.

    No diagnostics render as the empty string.
    """
    if not diagnostics:
        return ""
    return "\n\n".join(item.render() for item in diagnostics) + "\n"


def json_all(diagnostics: list[Diagnostic]) -> str:
    """One line holding the JSON array. `--json` ends stdout with this line."""
    payload = [item.to_json() for item in diagnostics]
    return json.dumps(payload, ensure_ascii=False) + "\n"


# Codes assigned in this interpreter in addition to the language reference.
# The normative catalog is spec/diagnostics.yaml. A unit test keeps them in sync.
EXTRA_CODES: dict[str, str] = {
    "E0025": "Hex or binary literal is malformed",
    "E0026": "Unterminated text literal",
    "E0027": "Unknown text escape",
    "E1000": "Syntax error",
    "E2000": "Unknown name",
    "E2022": "Ambiguous name",
    "E3000": "Type mismatch",
    "E3003": "Wrong number of arguments",
    "E3007": "Wrong number of type arguments",
    "E3008": "Unknown type",
    "E3013": "No property-test generator for this type",
    "E3044": "Interface implementation is missing a function",
    "E3045": "Type is not Showable",
    "E3046": "Type does not implement the interface",
    "E3004": "Unknown field or method",
    "E3005": "Expression statement must be a function call",
    "E3006": "Case constructor is missing its arguments",
    "E3025": "Ordering operator is not defined for this type",
    "E3026": "Type cannot be compared with ==",
    "E3027": "Builtin numeric function does not accept this type",
    "E3033": "Return value does not match the function return type",
    "E3034": "main must return Unit or Result[Unit, E]",
    "E3041": "This interface cannot be implemented by user code",
    "E3042": "Type is not Hashable",
    "E3043": "Duplicate interface implementation",
    "E4003": "Unknown effect",
    "E4012": "foreign declarations are only allowed in host mode",
    "E2005": "Unknown module member",
    "E4013": "Unknown standard-library module",
    "E4020": "Value is not convertible at the Python boundary",
    "T6012": "Use of a closed resource",
    "T6013": "Invalid byte data",
    "I9011": "Unicode version does not match the language pin",
    "I9013": "Wall-clock timeout stopped the run",
    "T6206": "OS memory limit exceeded",
    "T6207": "OS CPU limit exceeded",
    "T6208": "Wall-clock limit exceeded",
    "W6205": "Console output was truncated",
}
