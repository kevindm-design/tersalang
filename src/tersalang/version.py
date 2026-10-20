# SPDX-License-Identifier: Apache-2.0
"""Toolchain, language, and schema versions."""

from __future__ import annotations

TOOL_VERSION = "0.1.0"
LANGUAGE_VERSION = "0.1"
DIAGNOSTIC_SCHEMA = "tersa.diagnostic/0.1"
RESULT_SCHEMA = "tersa.result/0.9"
DEFAULT_MAX_INT_BITS = 65536
MIN_INT_BITS = 64
DEFAULT_MAX_DEPTH = 1000
DEFAULT_TEST_OUTPUT_BYTES = 1_048_576
DEFAULT_PROPERTY_CASES = 100
# tersa sandbox starts finite. These match the harness sample task and the
# in-process wall clock. Flags override them one at a time.
DEFAULT_SANDBOX_FUEL = 100_000
DEFAULT_SANDBOX_MEMORY = 100_000
DEFAULT_SANDBOX_WALL_MS = 5_000

# Where the Unicode tables come from: the host's `unicodedata`, whose version
# `tersa version` prints. No Unicode version is pinned, so nothing emits I9011.
UNICODE_NOTE = "host-unicodedata"
