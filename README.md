# DelayBudget

[![CI](https://github.com/TomasOrtega/DelayBudget/actions/workflows/ci.yml/badge.svg)](https://github.com/TomasOrtega/DelayBudget/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%E2%80%933.14-blue.svg)](pyproject.toml)

DelayBudget computes the **minimum possible number of notification batches**
when each notification has its own maximum allowed delay.

It is a small deterministic scheduling core. It uses no AI, makes no network
requests, inspects no notification content, and has no runtime dependencies.

## Guarantee

A notification arriving at time `a` with delay budget `d` may be delivered at
any time in the closed interval `[a, a + d]`.

DelayBudget waits until the earliest pending deadline and then delivers every
pending notification together. No valid schedule can use fewer batches. The
proof and exact boundary semantics are in [ALGORITHM.md](ALGORITHM.md).

## Install

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then
install the command from a checkout:

```bash
uv tool install .
```

For development:

```bash
uv sync
uv run prek install
```

Python 3.10 or newer is required.

## Command line

The CLI consumes one JSON object per line. Time is an integer in any consistent
unit, such as seconds, milliseconds, or synthetic trace ticks.

```json
{"id":"email-1","source":"email","arrival":0,"max_delay":1200}
{"id":"message-1","source":"messages","arrival":300,"max_delay":0}
```

Run:

```bash
delaybudget schedule examples/notifications.jsonl
```

Output is also JSON Lines:

```json
{"deliver_at":300,"notifications":[{"id":"email-1","source":"email","arrival":0,"max_delay":1200},{"id":"news-1","source":"news","arrival":180,"max_delay":7200},{"id":"message-1","source":"messages","arrival":300,"max_delay":0}]}
{"deliver_at":2700,"notifications":[{"id":"email-2","source":"email","arrival":1500,"max_delay":1200}]}
```

Use `-` for standard input or output:

```bash
cat trace.jsonl | delaybudget schedule - -o schedule.jsonl
```

Input is intentionally strict. The CLI rejects unknown fields, duplicate JSON
keys, duplicate IDs, non-standard JSON numbers, negative budgets, booleans used
as integers, malformed Unicode, invalid UTF-8, and records over one million
characters.

By default, the complete trace is validated before output begins. File output
is written to a sibling temporary file, flushed to disk, and atomically replaces
the destination only after success. Existing file permissions are preserved;
new files use owner-only permissions on POSIX systems.

For a large trace that is already ordered by nondecreasing arrival time, use:

```bash
delaybudget schedule --assume-sorted trace.jsonl -o schedule.jsonl
```

This streams parsing and scheduling. File output remains atomic, but standard
output can contain complete early batches before a later invalid record is
reported.

## Online integration

`OnlineScheduler` is the state machine intended for platform adapters:

```python
from delaybudget import Notification, OnlineScheduler

scheduler = OnlineScheduler()

batch = scheduler.advance(
    1_000,
    [Notification("email-1", arrival=1_000, max_delay=20_000, source="email")],
)
assert batch is None
assert scheduler.next_deadline == 21_000

batch = scheduler.advance(
    5_000,
    [Notification("message-1", arrival=5_000, max_delay=0, source="messages")],
)
assert batch is not None
assert batch.deliver_at == 5_000
```

An adapter must:

1. use one monotonic integer clock;
2. serialize calls to `advance()`;
3. provide every arrival for a timestamp in one call; and
4. arm its timer for `next_deadline` whenever that value changes.

Times passed to `advance()` must be strictly increasing. If an adapter advances
past a pending deadline, `DeadlineMissedError` is raised instead of silently
claiming the delay guarantee still held. Validation failures do not mutate
scheduler state.

Notification IDs must be unique while pending. An ID may be reused after its
batch has been emitted.

## Offline API

```python
from delaybudget import Notification, schedule

events = [
    Notification("email", arrival=0, max_delay=20, source="email"),
    Notification("message", arrival=5, max_delay=0, source="messages"),
]

for batch in schedule(events):
    print(batch.deliver_at, [item.id for item in batch.notifications])
```

`schedule()` accepts arbitrary input order in `O(n log n)` time.
`schedule_sorted()` accepts an arrival-sorted iterable in `O(n)` time. Both
require globally unique IDs and use `O(n)` memory; the sorted API streams batch
results without first storing and sorting the whole trace.

## Scope

This repository contains only the portable scheduler, trace CLI, proof, tests,
and release tooling. It does not intercept operating-system notifications,
infer importance, maintain user profiles, or ship a platform service. Platform
integrations should keep permissions and policy decisions outside this core.

## Development

```bash
uv run python -m unittest discover -s tests -v
uv run coverage run -m unittest discover -s tests
uv run coverage report
uv run prek -a --quiet
uv run mypy
uv build
uv run twine check dist/*
```

The prek hooks run Ruff's linter and formatter checks using the versions pinned
in `uv.lock`.

The suite includes exhaustive comparison with brute force for every multiset of
up to four integer intervals in a small horizon, plus randomized agreement
between the online and offline implementations. See
[CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), and
[RELEASING.md](RELEASING.md).

## License

Apache License 2.0. See [LICENSE](LICENSE).
