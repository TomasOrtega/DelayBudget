"""Core scheduling primitives for DelayBudget.

A notification is available at ``arrival`` and must be delivered no later than
``arrival + max_delay``. The optimal rule is to deliver at the earliest pending
deadline and include every notification available at that time.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass


class DuplicateNotificationError(ValueError):
    """Raised when a notification identifier is not unique where required."""


class UnsortedInputError(ValueError):
    """Raised when arrival times are not nondecreasing."""


class TimeOrderError(ValueError):
    """Raised when an online scheduler clock does not move forward."""


class ArrivalTimeError(ValueError):
    """Raised when an online arrival is stamped with the wrong time."""


class DeadlineMissedError(RuntimeError):
    """Raised when an online caller advances past a pending deadline."""


def _require_int(value: object, field: str) -> int:
    """Return an integer value while rejecting booleans."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")
    return value


def _require_text(value: object, field: str, *, non_empty: bool = False) -> str:
    """Return text that can be represented as well-formed UTF-8."""

    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    if non_empty and not value:
        raise ValueError(f"{field} must be non-empty")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(
            f"{field} must contain only valid Unicode scalar values"
        ) from exc
    return value


@dataclass(frozen=True, slots=True)
class Notification:
    """A notification with an integer arrival and non-negative delay budget.

    Times may use any consistent integer unit. ``id`` and ``source`` are opaque
    labels; the scheduler never examines notification content.
    """

    id: str
    arrival: int
    max_delay: int
    source: str = ""

    def __post_init__(self) -> None:
        identifier = _require_text(self.id, "id", non_empty=True)
        source = _require_text(self.source, "source")
        arrival = _require_int(self.arrival, "arrival")
        max_delay = _require_int(self.max_delay, "max_delay")
        if max_delay < 0:
            raise ValueError("max_delay must be non-negative")

        object.__setattr__(self, "id", identifier)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "arrival", arrival)
        object.__setattr__(self, "max_delay", max_delay)

    @property
    def deadline(self) -> int:
        """Return the latest legal delivery time."""

        return self.arrival + self.max_delay


@dataclass(frozen=True, slots=True)
class Batch:
    """A non-empty immutable batch delivered at ``deliver_at``."""

    deliver_at: int
    notifications: tuple[Notification, ...]

    def __post_init__(self) -> None:
        deliver_at = _require_int(self.deliver_at, "deliver_at")
        try:
            notifications = tuple(self.notifications)
        except TypeError as exc:
            raise TypeError("notifications must be an iterable") from exc

        if not notifications:
            raise ValueError("a batch must contain at least one notification")
        for notification in notifications:
            if not isinstance(notification, Notification):
                raise TypeError("notifications must contain Notification objects")
            if not notification.arrival <= deliver_at <= notification.deadline:
                raise ValueError(
                    f"notification {notification.id!r} cannot be delivered at "
                    f"{deliver_at}; valid interval is "
                    f"[{notification.arrival}, {notification.deadline}]"
                )

        object.__setattr__(self, "deliver_at", deliver_at)
        object.__setattr__(self, "notifications", notifications)


class OnlineScheduler:
    """Incremental scheduler for a serialized, monotonic event loop.

    Call :meth:`advance` once for each timestamp that has arrivals or reaches
    :attr:`next_deadline`. All arrivals in one call must be stamped with that
    call's ``now`` value. Validation failures leave scheduler state unchanged.
    """

    __slots__ = ("_current_time", "_next_deadline", "_pending", "_pending_ids")

    def __init__(self) -> None:
        self._current_time: int | None = None
        self._next_deadline: int | None = None
        self._pending: list[Notification] = []
        self._pending_ids: set[str] = set()

    @property
    def current_time(self) -> int | None:
        """Return the last successfully processed time."""

        return self._current_time

    @property
    def next_deadline(self) -> int | None:
        """Return the timer deadline, or ``None`` when nothing is pending."""

        return self._next_deadline

    @property
    def pending_count(self) -> int:
        """Return the number of notifications waiting for delivery."""

        return len(self._pending)

    def advance(
        self,
        now: int,
        arrivals: Iterable[Notification] = (),
    ) -> Batch | None:
        """Process one timestamp and return a due batch, if any.

        ``now`` must be strictly greater than the previous successful call's
        time. A call may occur before a pending deadline, at that deadline, or
        at a new arrival time, but never after a pending deadline.
        Notifications arriving exactly at a deadline are included before the
        due batch is emitted.
        """

        now = _require_int(now, "now")
        if self._current_time is not None and now <= self._current_time:
            raise TimeOrderError("online scheduler times must be strictly increasing")
        if self._next_deadline is not None and now > self._next_deadline:
            raise DeadlineMissedError(
                f"advanced to {now} after pending deadline {self._next_deadline}"
            )

        try:
            incoming = tuple(arrivals)
        except TypeError as exc:
            raise TypeError("arrivals must be an iterable") from exc

        incoming_ids: set[str] = set()
        next_deadline = self._next_deadline
        for notification in incoming:
            if not isinstance(notification, Notification):
                raise TypeError("arrivals must contain Notification objects")
            if notification.arrival != now:
                raise ArrivalTimeError(
                    f"notification {notification.id!r} has arrival "
                    f"{notification.arrival}, expected {now}"
                )
            if notification.id in self._pending_ids or notification.id in incoming_ids:
                raise DuplicateNotificationError(
                    f"duplicate pending notification id: {notification.id!r}"
                )

            incoming_ids.add(notification.id)
            if next_deadline is None or notification.deadline < next_deadline:
                next_deadline = notification.deadline

        batch: Batch | None = None
        if next_deadline == now:
            batch = Batch(now, (*self._pending, *incoming))
            self._pending.clear()
            self._pending_ids.clear()
            next_deadline = None
        else:
            self._pending.extend(incoming)
            self._pending_ids.update(incoming_ids)

        self._current_time = now
        self._next_deadline = next_deadline
        return batch


def schedule_sorted(notifications: Iterable[Notification]) -> Iterator[Batch]:
    """Yield an optimal schedule for arrival-sorted notifications.

    Arrivals must be nondecreasing, and identifiers must be globally unique in
    the trace. Runtime is linear. The iterator retains the current pending batch
    and all identifiers seen so far.
    """

    pending: list[Notification] = []
    seen_ids: set[str] = set()
    earliest_deadline: int | None = None
    last_arrival: int | None = None

    for notification in notifications:
        if not isinstance(notification, Notification):
            raise TypeError("notifications must contain Notification objects")
        if notification.id in seen_ids:
            raise DuplicateNotificationError(
                f"duplicate notification id: {notification.id!r}"
            )
        if last_arrival is not None and notification.arrival < last_arrival:
            raise UnsortedInputError(
                "schedule_sorted requires nondecreasing arrival times"
            )

        seen_ids.add(notification.id)
        last_arrival = notification.arrival

        if earliest_deadline is not None and earliest_deadline < notification.arrival:
            yield Batch(earliest_deadline, tuple(pending))
            pending.clear()
            earliest_deadline = None

        pending.append(notification)
        if earliest_deadline is None or notification.deadline < earliest_deadline:
            earliest_deadline = notification.deadline

    if pending:
        assert earliest_deadline is not None
        yield Batch(earliest_deadline, tuple(pending))


def schedule(notifications: Iterable[Notification]) -> tuple[Batch, ...]:
    """Return an optimal schedule for notifications in any input order.

    Runtime is ``O(n log n)`` because arrivals are stably sorted first.
    Notification identifiers must be globally unique in the trace.
    """

    ordered: list[Notification] = []
    for notification in notifications:
        if not isinstance(notification, Notification):
            raise TypeError("notifications must contain Notification objects")
        ordered.append(notification)

    ordered.sort(key=lambda notification: notification.arrival)
    return tuple(schedule_sorted(ordered))
