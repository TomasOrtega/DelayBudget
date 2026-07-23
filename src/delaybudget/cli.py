"""Command-line interface for DelayBudget."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import tempfile
from collections.abc import Iterable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from pathlib import Path
from typing import Any, NoReturn, TextIO, cast

from . import __version__
from .core import Batch, Notification, schedule, schedule_sorted

_ALLOWED_FIELDS = frozenset({"id", "arrival", "max_delay", "source"})
_REQUIRED_FIELDS = frozenset({"id", "arrival", "max_delay"})
_MAX_RECORD_CHARS = 1_000_000
_MAX_JSON_DEPTH = 64


class InputError(ValueError):
    """Raised when a JSON Lines input record is invalid."""


class _DuplicateJsonKeyError(ValueError):
    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


class _NonStandardNumberError(ValueError):
    def __init__(self, value: str) -> None:
        super().__init__(value)
        self.value = value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    record: dict[str, Any] = {}
    for key, value in pairs:
        if key in record:
            raise _DuplicateJsonKeyError(key)
        record[key] = value
    return record


def _reject_nonstandard_number(value: str) -> NoReturn:
    raise _NonStandardNumberError(value)


def _nesting_exceeds_limit(text: str, *, limit: int = _MAX_JSON_DEPTH) -> bool:
    """Return whether JSON container nesting exceeds *limit*.

    This bounded pre-scan prevents deeply nested untrusted input from consuming
    the decoder's recursion budget. Brackets inside JSON strings are ignored;
    the standard-library decoder remains responsible for syntax validation.
    """

    depth = 0
    in_string = False
    escaped = False

    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue

        if character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > limit:
                return True
        elif character in "]}":
            depth = max(0, depth - 1)

    return False


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="delaybudget",
        description=(
            "Compute a minimum-batch schedule for notifications with "
            "individual delay budgets."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    schedule_parser = subparsers.add_parser(
        "schedule",
        help="schedule a JSON Lines notification trace",
    )
    schedule_parser.add_argument(
        "input",
        nargs="?",
        default="-",
        help="input JSON Lines file, or - for standard input (default: -)",
    )
    schedule_parser.add_argument(
        "-o",
        "--output",
        default="-",
        help="output JSON Lines file, or - for standard output (default: -)",
    )
    schedule_parser.add_argument(
        "--assume-sorted",
        action="store_true",
        help=(
            "require nondecreasing arrivals and stream the trace instead of sorting it"
        ),
    )
    return parser


def _bounded_lines(stream: TextIO) -> Iterator[tuple[int, str]]:
    line_number = 0
    while True:
        try:
            # Two extra characters permit a CRLF line ending at the limit.
            line = stream.readline(_MAX_RECORD_CHARS + 3)
        except UnicodeDecodeError as exc:
            raise InputError(
                f"line {line_number + 1}: input is not valid UTF-8"
            ) from exc

        if line == "":
            return
        line_number += 1

        content = line[:-1] if line.endswith("\n") else line
        if content.endswith("\r"):
            content = content[:-1]
        if len(content) > _MAX_RECORD_CHARS:
            raise InputError(
                f"line {line_number}: record exceeds {_MAX_RECORD_CHARS} characters"
            )
        yield line_number, line


def _iter_notifications(
    stream: TextIO,
    *,
    assume_sorted: bool,
) -> Iterator[Notification]:
    seen_ids: set[str] = set()
    last_arrival: int | None = None

    for line_number, line in _bounded_lines(stream):
        if not line.strip():
            continue

        if _nesting_exceeds_limit(line):
            raise InputError(
                f"line {line_number}: JSON nesting is too deep "
                f"(maximum {_MAX_JSON_DEPTH})"
            )

        try:
            loaded = json.loads(
                line,
                object_pairs_hook=_unique_object,
                parse_constant=_reject_nonstandard_number,
            )
        except _DuplicateJsonKeyError as exc:
            raise InputError(
                f"line {line_number}: duplicate JSON field: {exc.key!r}"
            ) from exc
        except _NonStandardNumberError as exc:
            raise InputError(
                f"line {line_number}: non-standard JSON number: {exc.value}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise InputError(f"line {line_number}: invalid JSON: {exc.msg}") from exc
        except RecursionError as exc:
            raise InputError(f"line {line_number}: JSON nesting is too deep") from exc
        except ValueError as exc:
            # CPython can raise a plain ValueError for inputs such as integer
            # literals exceeding the interpreter's configured digit limit.
            raise InputError(f"line {line_number}: invalid JSON: {exc}") from exc

        if not isinstance(loaded, dict):
            raise InputError(f"line {line_number}: expected a JSON object")
        record = cast(dict[str, object], loaded)

        fields = set(record)
        missing = sorted(_REQUIRED_FIELDS - fields)
        extra = sorted(fields - _ALLOWED_FIELDS)
        if missing:
            raise InputError(
                f"line {line_number}: missing field(s): {', '.join(missing)}"
            )
        if extra:
            raise InputError(
                f"line {line_number}: unknown field(s): {', '.join(extra)}"
            )

        try:
            notification = Notification(
                id=cast(str, record["id"]),
                arrival=cast(int, record["arrival"]),
                max_delay=cast(int, record["max_delay"]),
                source=cast(str, record.get("source", "")),
            )
        except (TypeError, ValueError) as exc:
            raise InputError(f"line {line_number}: {exc}") from exc

        if notification.id in seen_ids:
            raise InputError(
                f"line {line_number}: duplicate notification id: {notification.id!r}"
            )
        if (
            assume_sorted
            and last_arrival is not None
            and notification.arrival < last_arrival
        ):
            raise InputError(
                f"line {line_number}: --assume-sorted requires "
                "nondecreasing arrival times"
            )

        seen_ids.add(notification.id)
        last_arrival = notification.arrival
        yield notification


def _batch_record(batch: Batch) -> dict[str, object]:
    return {
        "deliver_at": batch.deliver_at,
        "notifications": [
            {
                "id": notification.id,
                "source": notification.source,
                "arrival": notification.arrival,
                "max_delay": notification.max_delay,
            }
            for notification in batch.notifications
        ],
    }


def _write_batches(stream: TextIO, batches: Iterable[Batch]) -> None:
    for batch in batches:
        json.dump(
            _batch_record(batch),
            stream,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        stream.write("\n")


def _input_context(path: str) -> AbstractContextManager[TextIO]:
    if path == "-":
        return nullcontext(sys.stdin)
    return Path(path).open("r", encoding="utf-8")


@contextmanager
def _atomic_output(path: str) -> Iterator[TextIO]:
    """Yield a stream and atomically replace *path* only after success."""

    target = Path(path)
    try:
        previous_mode = stat.S_IMODE(target.stat().st_mode)
    except FileNotFoundError:
        previous_mode = None

    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    temporary = Path(temporary_name)

    try:
        with os.fdopen(
            file_descriptor,
            "w",
            encoding="utf-8",
            newline="\n",
        ) as stream:
            yield stream
            stream.flush()
            os.fsync(stream.fileno())

        if previous_mode is not None:
            os.chmod(temporary, previous_mode)
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _output_context(path: str) -> AbstractContextManager[TextIO]:
    if path == "-":
        return nullcontext(sys.stdout)
    return _atomic_output(path)


def _silence_broken_pipe() -> None:
    """Prevent a second broken-pipe error while Python flushes stdout."""

    try:
        stdout_fd = sys.stdout.fileno()
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(devnull_fd, stdout_fd)
        finally:
            os.close(devnull_fd)
    except (AttributeError, OSError, ValueError):
        pass


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""

    parser = _parser()
    args = parser.parse_args(argv)

    if args.command != "schedule":  # Defensive: argparse prevents this today.
        parser.error(f"unknown command: {args.command}")

    try:
        # The output context is outermost so an in-place input file is closed
        # before its atomic replacement occurs (important on Windows).
        with (
            _output_context(args.output) as output_stream,
            _input_context(args.input) as input_stream,
        ):
            notifications = _iter_notifications(
                input_stream,
                assume_sorted=args.assume_sorted,
            )
            if args.assume_sorted:
                batches: Iterable[Batch] = schedule_sorted(notifications)
            else:
                batches = schedule(notifications)
            _write_batches(output_stream, batches)
    except BrokenPipeError:
        _silence_broken_pipe()
        return 0
    except (OSError, InputError, TypeError, ValueError) as exc:
        print(f"delaybudget: error: {exc}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
