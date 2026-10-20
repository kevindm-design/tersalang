# SPDX-License-Identifier: Apache-2.0
"""Source files and spans. Columns count Unicode code points and are 1-based."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Span:
    """A source region. The end position is exclusive, matching LSP ranges."""

    file: str
    start: int
    end: int
    start_line: int
    start_col: int
    end_line: int
    end_col: int

    def to_json(self) -> dict[str, dict[str, int]]:
        """The start and end as `{"line": ..., "column": ...}` objects, both 1-based."""
        return {
            "start": {"line": self.start_line, "column": self.start_col},
            "end": {"line": self.end_line, "column": self.end_col},
        }


def merge_spans(left: Span, right: Span) -> Span:
    """The span from the start of `left` to the end of `right`, in `left`'s file."""
    return Span(
        file=left.file,
        start=left.start,
        end=right.end,
        start_line=left.start_line,
        start_col=left.start_col,
        end_line=right.end_line,
        end_col=right.end_col,
    )


def decode_source_bytes(data: bytes) -> str:
    """Decode source bytes. Invalid UTF-8 becomes lone surrogates for the lexer."""
    return data.decode("utf-8", errors="surrogateescape")


class Source:
    """A source file's text, indexed by line so offsets convert to line and column."""

    def __init__(self, filename: str, text: str) -> None:
        self.filename = filename
        self.text = text
        self.line_starts = [0]
        for index, char in enumerate(text):
            if char == "\n":
                self.line_starts.append(index + 1)

    def span(self, start: int, end: int) -> Span:
        """The span from offset `start` up to, but not including, offset `end`."""
        start_line, start_col = self.position(start)
        end_line, end_col = self.position(end)
        return Span(self.filename, start, end, start_line, start_col, end_line, end_col)

    def position(self, offset: int) -> tuple[int, int]:
        """The 1-based `(line, column)` of `offset`, clamped to the text."""
        if offset < 0:
            offset = 0
        if offset > len(self.text):
            offset = len(self.text)
        starts = self.line_starts
        # Binary search for the last line that starts at or before `offset`.
        lo = 0
        hi = len(starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if starts[mid] <= offset:
                lo = mid
            else:
                hi = mid - 1
        line = lo + 1
        col = offset - starts[lo] + 1
        return line, col

    def slice(self, span: Span) -> str:
        """The text that `span` covers."""
        return self.text[span.start : span.end]
