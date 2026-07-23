# Contributing

Thank you for improving DelayBudget.

## Principles

Changes should preserve the project's narrow purpose:

- deterministic scheduling without AI or content inspection;
- a dependency-free runtime core;
- exact, documented semantics;
- explicit errors rather than silent guesses; and
- portable logic separated from operating-system integrations.

Large platform integrations should normally live in separate repositories and
consume or port the core algorithm.

## Local workflow

```bash
uv sync
uv run coverage run -m unittest discover -s tests -v
uv run coverage report
uv run prek -a --quiet
uv run mypy
uv build
uv run twine check dist/*
```

Run `uv run prek install` once to check staged Python files with Ruff before
each commit. The repository's `uv.lock` keeps development and CI tools aligned.

Add tests for every behavior change. Algorithmic changes must include either a
proof argument or a counterexample to the current rule. Keep public APIs typed
and document compatibility-impacting changes in `CHANGELOG.md`.

## Pull requests

Keep pull requests focused, explain the user-visible effect, include tests, and
avoid unrelated formatting changes. The CI matrix covers Python 3.10 through
3.14 and Linux, macOS, and Windows.

By submitting a contribution, you agree that it may be distributed under the
Apache License 2.0. The project follows [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
