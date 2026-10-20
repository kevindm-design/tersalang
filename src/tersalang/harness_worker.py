# SPDX-License-Identifier: Apache-2.0
"""Child process for one harness attempt. A crash here does not kill the parent."""

from __future__ import annotations

from tersalang.harness import worker_main

if __name__ == "__main__":
    raise SystemExit(worker_main())
