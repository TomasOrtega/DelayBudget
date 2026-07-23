# Algorithm and correctness

## Problem

Each notification `i` has an arrival time `a_i`, a non-negative delay budget
`b_i`, and a deadline `d_i = a_i + b_i`.

A delivery time `t` serves notification `i` exactly when:

```text
a_i <= t <= d_i
```

The goal is to choose as few delivery times as possible while serving every
notification. This is the minimum hitting-set problem for intervals on a line.

## Greedy rule

1. Find the earliest deadline `T` among pending notifications.
2. Deliver every notification that has arrived by `T` in one batch at `T`.
3. Repeat for the remaining notifications.

## Optimality proof

Let `I` be a remaining notification with the earliest deadline `T`. Every valid
schedule must contain at least one delivery at or before `T` to serve `I`.

Take an optimal schedule and merge all of its delivery times at or before `T`
into one delivery at `T`. Any notification served by one of those times had
already arrived by `T`. Its deadline is at least `T`, because `T` is the
earliest remaining deadline. The merged delivery is therefore valid and uses no
more batches than the original schedule.

Thus an optimal schedule exists whose first delivery is exactly at `T`. That
delivery may include every notification pending at `T` without creating a
violation. Removing those notifications leaves the same problem on the
remaining intervals. Repeating the argument proves that the greedy schedule
uses the minimum number of batches.

The guarantee concerns the number of batches. It does not claim to minimize
average delay or select a unique schedule among all minimum-batch schedules.

## Arrival at a deadline

A notification arriving exactly at `T` is eligible for the batch at `T`.
Accordingly, `schedule_sorted()` flushes a pending batch only when the next
arrival is strictly greater than the earliest deadline.

For the same reason, `OnlineScheduler.advance(T, arrivals)` adds all arrivals at
`T` before it emits the due batch. A caller cannot supply more arrivals stamped
`T` later because online scheduler times must be strictly increasing.

## Online operation

The decision rule needs no future information. A live integration maintains the
earliest pending deadline as a timer. A new arrival can move that timer earlier.
When the clock reaches the timer, all pending notifications are emitted.

`OnlineScheduler` enforces these invariants:

- scheduler time is strictly increasing;
- every arrival supplied at time `T` has `arrival == T`;
- pending notification IDs are unique; and
- the caller never advances beyond the next pending deadline.

Validation failures raise explicit exceptions and leave state unchanged. This
protects the guarantee from integration bugs such as a lost or late timer
callback. IDs may be reused after their pending batch is emitted.

## Complexity

For `n` notifications, `p` currently pending notifications, and `k` arrivals in
one online call:

- `schedule()`: `O(n log n)` time and `O(n)` memory;
- `schedule_sorted()`: `O(n)` time and `O(n)` memory, including global
  duplicate-ID validation; and
- `OnlineScheduler.advance()`: `O(k)` time for a non-emitting call and
  `O(p + k)` when a batch is emitted, with `O(p)` pending memory.

`schedule_sorted()` yields completed batches as soon as later input proves they
are due. It therefore avoids storing and sorting the complete trace, although
its global set of previously seen IDs still grows with the trace.
