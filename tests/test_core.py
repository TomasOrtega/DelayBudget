from __future__ import annotations

import itertools
import random
import unittest
from collections import defaultdict
from collections.abc import Iterator

from delaybudget import (
    ArrivalTimeError,
    Batch,
    DeadlineMissedError,
    DuplicateNotificationError,
    Notification,
    OnlineScheduler,
    TimeOrderError,
    UnsortedInputError,
    schedule,
    schedule_sorted,
)


class NotificationTests(unittest.TestCase):
    def test_rejects_non_string_id(self) -> None:
        with self.assertRaisesRegex(TypeError, "id must be a string"):
            Notification(1, arrival=0, max_delay=0)  # type: ignore[arg-type]

    def test_rejects_empty_id(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-empty"):
            Notification("", arrival=0, max_delay=0)

    def test_rejects_non_string_source(self) -> None:
        with self.assertRaisesRegex(TypeError, "source must be a string"):
            Notification(  # type: ignore[arg-type]
                "n", arrival=0, max_delay=0, source=1
            )

    def test_rejects_unpaired_unicode_surrogates(self) -> None:
        with self.assertRaisesRegex(ValueError, "valid Unicode scalar values"):
            Notification("\ud800", arrival=0, max_delay=0)
        with self.assertRaisesRegex(ValueError, "valid Unicode scalar values"):
            Notification("n", arrival=0, max_delay=0, source="\udfff")

    def test_rejects_negative_delay(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-negative"):
            Notification("n", arrival=0, max_delay=-1)

    def test_rejects_boolean_and_non_integer_times(self) -> None:
        with self.assertRaisesRegex(TypeError, "arrival must be an integer"):
            Notification("n", arrival=True, max_delay=0)
        with self.assertRaisesRegex(TypeError, "max_delay must be an integer"):
            Notification("n", arrival=0, max_delay=False)
        with self.assertRaisesRegex(TypeError, "arrival must be an integer"):
            Notification("n", arrival=1.5, max_delay=0)  # type: ignore[arg-type]

    def test_deadline_and_negative_arrival(self) -> None:
        self.assertEqual(Notification("n", 7, 5).deadline, 12)
        self.assertEqual(Notification("past", -5, 2).deadline, -3)


class BatchTests(unittest.TestCase):
    def test_normalizes_notifications_to_an_immutable_tuple(self) -> None:
        notification = Notification("n", arrival=0, max_delay=5)
        batch = Batch(5, [notification])  # type: ignore[arg-type]

        self.assertEqual(batch.notifications, (notification,))
        self.assertIsInstance(batch.notifications, tuple)

    def test_rejects_non_iterable_or_empty_members(self) -> None:
        with self.assertRaisesRegex(TypeError, "iterable"):
            Batch(0, None)  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "at least one"):
            Batch(0, ())

    def test_rejects_invalid_delivery_time(self) -> None:
        notification = Notification("n", arrival=2, max_delay=3)
        with self.assertRaisesRegex(ValueError, "valid interval"):
            Batch(1, (notification,))
        with self.assertRaisesRegex(ValueError, "valid interval"):
            Batch(6, (notification,))
        with self.assertRaisesRegex(TypeError, "deliver_at must be an integer"):
            Batch(True, (notification,))

    def test_rejects_non_notification_member(self) -> None:
        with self.assertRaisesRegex(TypeError, "Notification objects"):
            Batch(0, (object(),))  # type: ignore[arg-type]


class OnlineSchedulerTests(unittest.TestCase):
    def test_initial_state(self) -> None:
        scheduler = OnlineScheduler()

        self.assertIsNone(scheduler.current_time)
        self.assertIsNone(scheduler.next_deadline)
        self.assertEqual(scheduler.pending_count, 0)

    def test_empty_tick_advances_clock(self) -> None:
        scheduler = OnlineScheduler()

        self.assertIsNone(scheduler.advance(10))
        self.assertEqual(scheduler.current_time, 10)
        self.assertIsNone(scheduler.next_deadline)

    def test_arms_and_moves_timer_earlier(self) -> None:
        scheduler = OnlineScheduler()

        self.assertIsNone(
            scheduler.advance(0, [Notification("email", 0, 20)])
        )
        self.assertEqual(scheduler.next_deadline, 20)
        self.assertEqual(scheduler.pending_count, 1)

        self.assertIsNone(
            scheduler.advance(5, [Notification("message", 5, 3)])
        )
        self.assertEqual(scheduler.current_time, 5)
        self.assertEqual(scheduler.next_deadline, 8)
        self.assertEqual(scheduler.pending_count, 2)

    def test_later_deadline_does_not_move_timer(self) -> None:
        scheduler = OnlineScheduler()
        scheduler.advance(0, [Notification("a", 0, 5)])

        scheduler.advance(2, [Notification("b", 2, 20)])

        self.assertEqual(scheduler.next_deadline, 5)

    def test_timer_tick_emits_pending_batch(self) -> None:
        scheduler = OnlineScheduler()
        scheduler.advance(0, [Notification("a", 0, 5)])
        scheduler.advance(3, [Notification("b", 3, 10)])

        batch = scheduler.advance(5)

        self.assertIsNotNone(batch)
        assert batch is not None
        self.assertEqual(batch.deliver_at, 5)
        self.assertEqual([item.id for item in batch.notifications], ["a", "b"])
        self.assertIsNone(scheduler.next_deadline)
        self.assertEqual(scheduler.pending_count, 0)

    def test_arrivals_at_deadline_join_batch(self) -> None:
        scheduler = OnlineScheduler()
        scheduler.advance(0, [Notification("a", 0, 5)])

        batch = scheduler.advance(
            5,
            [
                Notification("b", 5, 0),
                Notification("c", 5, 10),
            ],
        )

        self.assertIsNotNone(batch)
        assert batch is not None
        self.assertEqual([item.id for item in batch.notifications], ["a", "b", "c"])
        self.assertIsNone(scheduler.next_deadline)

    def test_zero_delay_arrival_emits_immediately(self) -> None:
        scheduler = OnlineScheduler()

        batch = scheduler.advance(7, [Notification("urgent", 7, 0)])

        self.assertIsNotNone(batch)
        assert batch is not None
        self.assertEqual(batch.deliver_at, 7)
        self.assertEqual(scheduler.current_time, 7)
        self.assertEqual(scheduler.pending_count, 0)

    def test_rejects_non_increasing_time_without_mutating_state(self) -> None:
        scheduler = OnlineScheduler()
        scheduler.advance(10, [Notification("a", 10, 5)])

        for invalid_time in (10, 9):
            with self.subTest(invalid_time=invalid_time):
                with self.assertRaises(TimeOrderError):
                    scheduler.advance(invalid_time)
                self.assertEqual(scheduler.current_time, 10)
                self.assertEqual(scheduler.next_deadline, 15)
                self.assertEqual(scheduler.pending_count, 1)

    def test_rejects_mismatched_arrival_without_mutating_state(self) -> None:
        scheduler = OnlineScheduler()

        with self.assertRaises(ArrivalTimeError):
            scheduler.advance(5, [Notification("a", 4, 10)])

        self.assertIsNone(scheduler.current_time)
        self.assertIsNone(scheduler.next_deadline)
        self.assertEqual(scheduler.pending_count, 0)

    def test_rejects_missed_deadline_without_consuming_arrivals(self) -> None:
        scheduler = OnlineScheduler()
        scheduler.advance(0, [Notification("a", 0, 5)])
        consumed = False

        def arrivals() -> Iterator[Notification]:
            nonlocal consumed
            consumed = True
            yield Notification("b", 6, 0)

        with self.assertRaises(DeadlineMissedError):
            scheduler.advance(6, arrivals())

        self.assertFalse(consumed)
        self.assertEqual(scheduler.current_time, 0)
        self.assertEqual(scheduler.next_deadline, 5)
        self.assertEqual(scheduler.pending_count, 1)

    def test_rejects_duplicate_pending_id_transactionally(self) -> None:
        scheduler = OnlineScheduler()
        scheduler.advance(0, [Notification("same", 0, 10)])

        with self.assertRaises(DuplicateNotificationError):
            scheduler.advance(
                3,
                [
                    Notification("new", 3, 10),
                    Notification("same", 3, 10),
                ],
            )

        self.assertEqual(scheduler.current_time, 0)
        self.assertEqual(scheduler.pending_count, 1)
        self.assertEqual(scheduler.next_deadline, 10)

    def test_rejects_duplicate_ids_within_one_call_transactionally(self) -> None:
        scheduler = OnlineScheduler()

        with self.assertRaises(DuplicateNotificationError):
            scheduler.advance(
                0,
                [Notification("same", 0, 1), Notification("same", 0, 2)],
            )

        self.assertIsNone(scheduler.current_time)
        self.assertEqual(scheduler.pending_count, 0)

    def test_iterable_failure_does_not_mutate_state(self) -> None:
        scheduler = OnlineScheduler()
        scheduler.advance(0, [Notification("a", 0, 10)])

        def broken() -> Iterator[Notification]:
            yield Notification("b", 2, 3)
            raise RuntimeError("source failed")

        with self.assertRaisesRegex(RuntimeError, "source failed"):
            scheduler.advance(2, broken())

        self.assertEqual(scheduler.current_time, 0)
        self.assertEqual(scheduler.next_deadline, 10)
        self.assertEqual(scheduler.pending_count, 1)

    def test_identifier_can_be_reused_after_emission(self) -> None:
        scheduler = OnlineScheduler()
        scheduler.advance(0, [Notification("same", 0, 0)])

        self.assertIsNone(scheduler.advance(1, [Notification("same", 1, 1)]))
        batch = scheduler.advance(2)

        self.assertIsNotNone(batch)
        assert batch is not None
        self.assertEqual(batch.notifications[0].id, "same")

    def test_rejects_invalid_now_and_arrival_collection(self) -> None:
        scheduler = OnlineScheduler()
        with self.assertRaisesRegex(TypeError, "now must be an integer"):
            scheduler.advance(True)
        with self.assertRaisesRegex(TypeError, "arrivals must be an iterable"):
            scheduler.advance(0, None)  # type: ignore[arg-type]
        with self.assertRaisesRegex(TypeError, "Notification objects"):
            scheduler.advance(0, [object()])  # type: ignore[list-item]

        self.assertIsNone(scheduler.current_time)

    def test_online_and_offline_schedules_agree_randomly(self) -> None:
        random_source = random.Random(20260723)

        for trial in range(500):
            events: list[Notification] = []
            arrival = 0
            for index in range(random_source.randint(0, 30)):
                arrival += random_source.randint(0, 3)
                events.append(
                    Notification(
                        id=f"{trial}-{index}",
                        arrival=arrival,
                        max_delay=random_source.randint(0, 12),
                    )
                )

            with self.subTest(trial=trial):
                self.assertEqual(_run_online(events), schedule(events))


class ScheduleTests(unittest.TestCase):
    def test_empty_input(self) -> None:
        self.assertEqual(schedule([]), ())
        self.assertEqual(tuple(schedule_sorted([])), ())

    def test_waits_until_earliest_deadline(self) -> None:
        events = [
            Notification("email", arrival=0, max_delay=10, source="email"),
            Notification("news", arrival=3, max_delay=20, source="news"),
        ]

        batches = schedule(events)

        self.assertEqual([batch.deliver_at for batch in batches], [10])
        self.assertEqual(
            [item.id for item in batches[0].notifications],
            ["email", "news"],
        )

    def test_immediate_notification_advances_pending_batch(self) -> None:
        events = [
            Notification("email", arrival=0, max_delay=10),
            Notification("message", arrival=5, max_delay=0),
        ]

        batches = schedule(events)

        self.assertEqual([batch.deliver_at for batch in batches], [5])
        self.assertEqual(
            [item.id for item in batches[0].notifications],
            ["email", "message"],
        )

    def test_arrival_at_deadline_joins_batch(self) -> None:
        events = [
            Notification("first", arrival=0, max_delay=5),
            Notification("second", arrival=5, max_delay=0),
            Notification("third", arrival=5, max_delay=8),
        ]

        batches = schedule(events)

        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0].deliver_at, 5)
        self.assertEqual(
            [item.id for item in batches[0].notifications],
            ["first", "second", "third"],
        )

    def test_notification_after_deadline_starts_new_batch(self) -> None:
        events = [
            Notification("first", arrival=0, max_delay=5),
            Notification("second", arrival=7, max_delay=2),
        ]

        self.assertEqual(
            [batch.deliver_at for batch in schedule(events)],
            [5, 9],
        )

    def test_schedule_sorts_stably(self) -> None:
        events = [
            Notification("late", arrival=4, max_delay=5),
            Notification("same-a", arrival=1, max_delay=10),
            Notification("same-b", arrival=1, max_delay=10),
        ]

        batches = schedule(events)

        self.assertEqual(
            [item.id for item in batches[0].notifications],
            ["same-a", "same-b", "late"],
        )

    def test_schedule_accepts_a_generator(self) -> None:
        events = (
            Notification(str(index), arrival=index, max_delay=2)
            for index in range(3)
        )

        self.assertEqual([batch.deliver_at for batch in schedule(events)], [2])

    def test_rejects_non_notification_values(self) -> None:
        with self.assertRaisesRegex(TypeError, "Notification objects"):
            schedule([object()])  # type: ignore[list-item]
        with self.assertRaisesRegex(TypeError, "Notification objects"):
            tuple(schedule_sorted([object()]))  # type: ignore[list-item]

    def test_schedule_sorted_rejects_decreasing_arrivals(self) -> None:
        events = [
            Notification("late", arrival=2, max_delay=1),
            Notification("early", arrival=1, max_delay=1),
        ]

        with self.assertRaises(UnsortedInputError):
            tuple(schedule_sorted(events))

    def test_duplicate_ids_are_rejected_by_both_apis(self) -> None:
        events = [
            Notification("same", arrival=0, max_delay=0),
            Notification("other", arrival=2, max_delay=0),
            Notification("same", arrival=4, max_delay=0),
        ]

        with self.assertRaises(DuplicateNotificationError):
            schedule(events)
        with self.assertRaises(DuplicateNotificationError):
            tuple(schedule_sorted(events))

    def test_exhaustive_small_instances_match_brute_force(self) -> None:
        intervals = [
            (arrival, deadline)
            for arrival in range(4)
            for deadline in range(arrival, 4)
        ]

        for size in range(1, 5):
            for pattern in itertools.combinations_with_replacement(
                intervals, size
            ):
                events = [
                    Notification(
                        id=f"n{index}",
                        arrival=arrival,
                        max_delay=deadline - arrival,
                    )
                    for index, (arrival, deadline) in enumerate(pattern)
                ]
                with self.subTest(pattern=pattern):
                    batches = schedule(events)
                    self.assertEqual(
                        len(batches),
                        _brute_force_minimum(events),
                    )
                    _assert_feasible(self, events, batches)


def _run_online(events: list[Notification]) -> tuple[Batch, ...]:
    by_arrival: dict[int, list[Notification]] = defaultdict(list)
    for event in events:
        by_arrival[event.arrival].append(event)

    scheduler = OnlineScheduler()
    emitted: list[Batch] = []
    for arrival in sorted(by_arrival):
        while (
            scheduler.next_deadline is not None
            and scheduler.next_deadline < arrival
        ):
            due = scheduler.advance(scheduler.next_deadline)
            assert due is not None
            emitted.append(due)

        due = scheduler.advance(arrival, by_arrival[arrival])
        if due is not None:
            emitted.append(due)

    while scheduler.next_deadline is not None:
        due = scheduler.advance(scheduler.next_deadline)
        assert due is not None
        emitted.append(due)

    return tuple(emitted)


def _brute_force_minimum(events: list[Notification]) -> int:
    earliest = min(event.arrival for event in events)
    latest = max(event.deadline for event in events)
    candidate_times = range(earliest, latest + 1)

    for size in range(1, len(events) + 1):
        for times in itertools.combinations(candidate_times, size):
            if all(
                any(event.arrival <= time <= event.deadline for time in times)
                for event in events
            ):
                return size

    raise AssertionError("no feasible schedule found")


def _assert_feasible(
    test: unittest.TestCase,
    events: list[Notification],
    batches: tuple[Batch, ...],
) -> None:
    delivered: dict[str, int] = {}
    for batch in batches:
        for event in batch.notifications:
            test.assertNotIn(event.id, delivered)
            delivered[event.id] = batch.deliver_at

    test.assertEqual(set(delivered), {event.id for event in events})
    for event in events:
        test.assertLessEqual(event.arrival, delivered[event.id])
        test.assertLessEqual(delivered[event.id], event.deadline)


if __name__ == "__main__":
    unittest.main()
