# SPDX-License-Identifier: Apache-2.0
"""The front end must not crash on arbitrary text."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from tersalang.lexer import lex_text
from tersalang.parser import parse_module


@given(st.text(max_size=200))
@settings(max_examples=40)
def test_lex_and_parse(text: str) -> None:
    source, tokens, diagnostics = lex_text("fuzz.tersa", text)
    parse_module(source, tokens, diagnostics)
