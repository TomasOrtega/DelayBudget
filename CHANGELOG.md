# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and releases use
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-07-23

### Added

- Integration-ready `OnlineScheduler` with explicit missed-deadline detection.
- Transactional validation and exact same-timestamp arrival semantics for the
  online state machine.
- Atomic CLI file replacement, UTF-8 validation, and input record-size limits.
- Strict rejection of duplicate JSON keys and non-standard JSON numbers.
- Python 3.14 support, static analysis, branch-coverage enforcement, and a
  tag-triggered release workflow with checksums and provenance attestations.

### Changed

- `Batch` normalizes its notifications to an immutable tuple.
- Both offline APIs require globally unique notification IDs.
- Package metadata identifies the public repository and maintainer.
- CI covers Python 3.10 through 3.14 on Linux, macOS, and Windows.

## [0.1.0] - 2026-07-23

### Added

- Optimal greedy scheduler for arbitrary-order traces.
- Linear-time iterator for arrival-sorted traces.
- Strict JSON Lines command-line interface.
- Correctness proof, exhaustive small-instance tests, and benchmark.

[Unreleased]: https://github.com/TomasOrtega/DelayBudget/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/TomasOrtega/DelayBudget/compare/v0.1.0...v1.0.0
[0.1.0]: https://github.com/TomasOrtega/DelayBudget/releases/tag/v0.1.0
