# Contributing

Small, tested changes are welcome.

- Open a pull request against `main`.
- Every commit needs a `Signed-off-by` trailer (`git commit -s`), the Developer Certificate of Origin.
- Run `uv sync`, then `uv run ruff format`, `uv run ruff check`, `uv run mypy`, and `uv run pytest`. CI fails when `ruff format --check` would change a file.
- Behavior that the specs do not settle goes in `docs/spec-notes.md`. When a change alters something `spec/*.md` describes, say so in the pull request.
- Record user-visible changes in `CHANGELOG.md`.
- Language changes are TEPs. Copy `teps/0000-template.md`.
- A contribution is licensed like the file it changes: Apache-2.0 for code, grammar files, and examples, CC BY 4.0 for `spec/*.md` and `docs/` (`NOTICE`).
- The code of conduct is `CODE_OF_CONDUCT.md`. Report security issues as described in `SECURITY.md`.
