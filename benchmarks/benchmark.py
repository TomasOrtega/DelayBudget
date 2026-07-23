"""Small, dependency-free throughput benchmark."""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from time import perf_counter

from delaybudget import Notification, schedule_sorted


def notifications(count: int) -> Iterator[Notification]:
    for index in range(count):
        # Arrival-sorted synthetic traffic with varied delay budgets.
        yield Notification(
            id=str(index),
            arrival=index,
            max_delay=(index * 17) % 300,
            source=f"source-{index % 16}",
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=100_000)
    args = parser.parse_args()
    if args.count < 0:
        parser.error("--count must be non-negative")

    started = perf_counter()
    batch_count = sum(1 for _ in schedule_sorted(notifications(args.count)))
    elapsed = perf_counter() - started
    rate = args.count / elapsed if elapsed else float("inf")

    print(f"notifications: {args.count:,}")
    print(f"batches:       {batch_count:,}")
    print(f"elapsed:       {elapsed:.3f}s")
    print(f"throughput:    {rate:,.0f} notifications/s")


if __name__ == "__main__":
    main()
