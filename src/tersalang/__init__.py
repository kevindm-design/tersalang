# SPDX-License-Identifier: Apache-2.0
"""Reference interpreter for the Tersalang language.

Modules, roughly in pipeline order:

- `source`: source files, spans, and decoding of source bytes.
- `lexer`: tokens and lexical diagnostics (`E00xx`).
- `ast`: the syntax tree.
- `parser`: recursive-descent parser from tokens to the syntax tree (`E1xxx`).
- `typesys`: types and the effect names, shared by the checker and the evaluator.
- `builtins`: standard-library signatures.
- `checker`: name resolution, type checking, and effect checking.
- `eval`: the tree-walking evaluator and its traps (`T6xxx`).
- `values`, `show`: runtime values and their canonical text form.
- `integers`: integer arithmetic under the size cap.
- `limits`: fuel, memory units, call depth, the integer cap, and the wall clock.
- `diagnostics`: the diagnostic record, its JSON form, and its human text.
- `driver`: check, run, and test one file; the exit codes the CLI uses.
- `sandbox`: RL-mode runs with host-chosen grants and limits.
- `cli`: the `tersa` command line.
- `fmt`: the canonical formatter behind `tersa fmt`.
- `gbnf`: GBNF grammar generation from spec/tersa.lark, and a recognizer for it.
- `harness`: RL task loading, hidden-test runs, and the reward formula.
- `harness_worker`, `isolation`: the harness child process and its OS sandbox.
- `namespacing`, `task_interface`: renaming task code apart from the candidate's,
  and the signatures `interface.tersa` requires.
- `result_schema`: the episode JSON schema check.
- `version`: toolchain, language, and schema versions and default limits.
"""

from __future__ import annotations

import sys

from tersalang.version import LANGUAGE_VERSION, TOOL_VERSION

# Tersalang Int values may contain up to 65,536 bits (about 19,729 decimal
# digits). CPython refuses int/str conversions above 4,300 digits unless this
# limit is raised. The interpreter does its own digit pre-check before converting.
sys.set_int_max_str_digits(0)

# A tree-walking evaluator uses several Python frames per Tersalang call.
# Call depth is enforced by the interpreter (T6203); this only keeps the host
# stack from failing first at the default limit of 1,000.
sys.setrecursionlimit(20000)

__all__ = ["LANGUAGE_VERSION", "TOOL_VERSION"]
__version__ = TOOL_VERSION
