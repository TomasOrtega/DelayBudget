from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from delaybudget import cli
from delaybudget.cli import main


class CliTests(unittest.TestCase):
    def test_schedule_arbitrary_order_to_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "trace.jsonl"
            input_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "id": "message-1",
                                "source": "message",
                                "arrival": 5,
                                "max_delay": 0,
                            }
                        ),
                        json.dumps(
                            {
                                "id": "email-1",
                                "source": "email",
                                "arrival": 0,
                                "max_delay": 10,
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["schedule", str(input_path)])

        self.assertEqual(exit_code, 0)
        records = [json.loads(line) for line in stdout.getvalue().splitlines()]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["deliver_at"], 5)
        self.assertEqual(
            [item["id"] for item in records[0]["notifications"]],
            ["email-1", "message-1"],
        )

    def test_stdin_blank_lines_and_default_source(self) -> None:
        stdout = io.StringIO()
        trace = '\n{"id":"n","arrival":0,"max_delay":0}\n\n'

        with patch("sys.stdin", io.StringIO(trace)), redirect_stdout(stdout):
            exit_code = main(["schedule"])

        self.assertEqual(exit_code, 0)
        record = json.loads(stdout.getvalue())
        self.assertEqual(record["deliver_at"], 0)
        self.assertEqual(record["notifications"][0]["source"], "")

    def test_assume_sorted_streams_valid_input(self) -> None:
        stdout = io.StringIO()
        trace = "\n".join(
            [
                '{"id":"a","arrival":0,"max_delay":0}',
                '{"id":"b","arrival":2,"max_delay":1}',
            ]
        )

        with patch("sys.stdin", io.StringIO(trace)), redirect_stdout(stdout):
            exit_code = main(["schedule", "--assume-sorted"])

        self.assertEqual(exit_code, 0)
        records = [json.loads(line) for line in stdout.getvalue().splitlines()]
        self.assertEqual([record["deliver_at"] for record in records], [0, 3])

    def test_assume_sorted_rejects_late_disorder_atomically_for_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "trace.jsonl"
            output_path = Path(directory) / "output.jsonl"
            input_path.write_text(
                "\n".join(
                    [
                        '{"id":"a","arrival":0,"max_delay":0}',
                        '{"id":"b","arrival":2,"max_delay":0}',
                        '{"id":"c","arrival":1,"max_delay":0}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            output_path.write_text("keep me", encoding="utf-8")
            stderr = io.StringIO()

            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "schedule",
                        "--assume-sorted",
                        str(input_path),
                        "-o",
                        str(output_path),
                    ]
                )

            self.assertEqual(output_path.read_text(encoding="utf-8"), "keep me")
            self.assertEqual(list(Path(directory).glob(".output.jsonl.*.tmp")), [])

        self.assertEqual(exit_code, 2)
        self.assertIn("line 3", stderr.getvalue())
        self.assertIn("nondecreasing", stderr.getvalue())

    def test_assume_sorted_stdout_can_be_partial_on_late_error(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        trace = "\n".join(
            [
                '{"id":"a","arrival":0,"max_delay":0}',
                '{"id":"b","arrival":2,"max_delay":0}',
                '{"id":"c","arrival":1,"max_delay":0}',
            ]
        )

        with (
            patch("sys.stdin", io.StringIO(trace)),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            exit_code = main(["schedule", "--assume-sorted"])

        self.assertEqual(exit_code, 2)
        self.assertEqual(json.loads(stdout.getvalue())["deliver_at"], 0)
        self.assertIn("line 3", stderr.getvalue())

    def test_invalid_input_reports_line_without_changing_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "bad.jsonl"
            output_path = Path(directory) / "output.jsonl"
            output_path.write_text("keep me", encoding="utf-8")
            input_path.write_text(
                '{"id":"ok","arrival":0,"max_delay":1}\nnot-json\n',
                encoding="utf-8",
            )

            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = main(
                    ["schedule", str(input_path), "-o", str(output_path)]
                )

            self.assertEqual(output_path.read_text(encoding="utf-8"), "keep me")
            self.assertEqual(list(Path(directory).glob(".output.jsonl.*.tmp")), [])

        self.assertEqual(exit_code, 2)
        self.assertIn("line 2", stderr.getvalue())

    def test_output_failure_does_not_replace_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "trace.jsonl"
            output_path = Path(directory) / "output.jsonl"
            input_path.write_text(
                '{"id":"n","arrival":0,"max_delay":1}\n',
                encoding="utf-8",
            )
            output_path.write_text("original", encoding="utf-8")

            def fail_after_write(stream: io.TextIOBase, batches: object) -> None:
                del batches
                stream.write("partial")
                raise OSError("simulated disk failure")

            stderr = io.StringIO()
            with (
                patch("delaybudget.cli._write_batches", side_effect=fail_after_write),
                redirect_stderr(stderr),
            ):
                exit_code = main(
                    ["schedule", str(input_path), "-o", str(output_path)]
                )

            self.assertEqual(output_path.read_text(encoding="utf-8"), "original")
            self.assertEqual(list(Path(directory).glob(".output.jsonl.*.tmp")), [])

        self.assertEqual(exit_code, 2)
        self.assertIn("simulated disk failure", stderr.getvalue())

    def test_successful_file_output_is_atomic_and_preserves_existing_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "trace.jsonl"
            output_path = Path(directory) / "output.jsonl"
            input_path.write_text(
                '{"id":"n","arrival":0,"max_delay":1}\n',
                encoding="utf-8",
            )
            output_path.write_text("old", encoding="utf-8")
            if os.name != "nt":
                output_path.chmod(0o640)

            exit_code = main(
                ["schedule", str(input_path), "-o", str(output_path)]
            )

            self.assertEqual(exit_code, 0)
            record = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(record["deliver_at"], 1)
            self.assertEqual(list(Path(directory).glob(".output.jsonl.*.tmp")), [])
            if os.name != "nt":
                self.assertEqual(output_path.stat().st_mode & 0o777, 0o640)

    @unittest.skipIf(os.name == "nt", "POSIX mode semantics")
    def test_new_output_file_is_owner_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "trace.jsonl"
            output_path = Path(directory) / "output.jsonl"
            input_path.write_text(
                '{"id":"n","arrival":0,"max_delay":0}\n',
                encoding="utf-8",
            )

            exit_code = main(
                ["schedule", str(input_path), "-o", str(output_path)]
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(output_path.stat().st_mode & 0o777, 0o600)

    def test_input_can_be_replaced_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            path.write_text(
                '{"id":"n","arrival":0,"max_delay":1}\n',
                encoding="utf-8",
            )

            exit_code = main(["schedule", str(path), "-o", str(path)])

            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(path.read_text())["deliver_at"], 1)

    def test_duplicate_id_reports_second_line(self) -> None:
        stderr = self._run_bad_input(
            "\n".join(
                [
                    '{"id":"same","arrival":0,"max_delay":1}',
                    '{"id":"same","arrival":2,"max_delay":1}',
                ]
            )
            + "\n"
        )

        self.assertIn("line 2", stderr)
        self.assertIn("duplicate notification id", stderr)

    def test_duplicate_json_key_is_rejected(self) -> None:
        stderr = self._run_bad_input(
            '{"id":"a","id":"b","arrival":0,"max_delay":0}\n'
        )

        self.assertIn("duplicate JSON field", stderr)
        self.assertIn("'id'", stderr)

    def test_non_standard_json_numbers_are_rejected(self) -> None:
        for value in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(value=value):
                stderr = self._run_bad_input(
                    f'{{"id":"n","arrival":{value},"max_delay":0}}\n'
                )
                self.assertIn("non-standard JSON number", stderr)
                self.assertIn(value, stderr)

    def test_unpaired_unicode_surrogate_is_rejected(self) -> None:
        stderr = self._run_bad_input(
            '{"id":"\\ud800","arrival":0,"max_delay":0}\n'
        )

        self.assertIn("line 1", stderr)
        self.assertIn("valid Unicode scalar values", stderr)

    def test_plain_json_value_error_gets_line_context(self) -> None:
        with patch("delaybudget.cli.json.loads", side_effect=ValueError("too large")):
            stderr = self._run_bad_input("{}\n")

        self.assertIn("line 1", stderr)
        self.assertIn("too large", stderr)

    def test_json_recursion_error_gets_clear_message(self) -> None:
        with patch("delaybudget.cli.json.loads", side_effect=RecursionError):
            stderr = self._run_bad_input("{}\n")

        self.assertIn("line 1", stderr)
        self.assertIn("nesting is too deep", stderr)

    def test_unknown_and_missing_fields_are_rejected(self) -> None:
        unknown = self._run_bad_input(
            '{"id":"n","arrival":0,"max_delay":1,"typo":true}\n'
        )
        missing = self._run_bad_input('{"id":"n","arrival":0}\n')

        self.assertIn("unknown field", unknown)
        self.assertIn("missing field", missing)

    def test_non_object_and_invalid_values_are_rejected(self) -> None:
        cases = {
            "expected a JSON object": "[]\n",
            "id must be a string": '{"id":1,"arrival":0,"max_delay":0}\n',
            "id must be non-empty": '{"id":"","arrival":0,"max_delay":0}\n',
            "arrival must be an integer": (
                '{"id":"n","arrival":true,"max_delay":0}\n'
            ),
            "max_delay must be an integer": (
                '{"id":"n","arrival":0,"max_delay":1.5}\n'
            ),
            "max_delay must be non-negative": (
                '{"id":"n","arrival":0,"max_delay":-1}\n'
            ),
            "source must be a string": (
                '{"id":"n","arrival":0,"max_delay":0,"source":1}\n'
            ),
        }

        for expected, text in cases.items():
            with self.subTest(expected=expected):
                self.assertIn(expected, self._run_bad_input(text))

    def test_record_size_limit_ignores_line_ending(self) -> None:
        with patch.object(cli, "_MAX_RECORD_CHARS", 16):
            stdout = io.StringIO()
            with (
                patch("sys.stdin", io.StringIO(" " * 16 + "\r\n")),
                redirect_stdout(stdout),
            ):
                exit_code = main(["schedule"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("record exceeds", self._run_bad_input(" " * 17))

    def test_invalid_utf8_is_rejected_with_line_number(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "invalid.jsonl"
            input_path.write_bytes(b'\xff\n')
            stderr = io.StringIO()

            with redirect_stderr(stderr):
                exit_code = main(["schedule", str(input_path)])

        self.assertEqual(exit_code, 2)
        self.assertIn("line 1", stderr.getvalue())
        self.assertIn("valid UTF-8", stderr.getvalue())

    def test_deeply_nested_json_is_rejected(self) -> None:
        text = "[" * (cli._MAX_JSON_DEPTH + 1)
        text += "]" * (cli._MAX_JSON_DEPTH + 1) + "\n"

        stderr = self._run_bad_input(text)

        self.assertIn("nesting is too deep", stderr)

    def test_brackets_inside_strings_do_not_count_as_nesting(self) -> None:
        stdout = io.StringIO()
        source = "[" * (cli._MAX_JSON_DEPTH + 1)
        trace = json.dumps(
            {"id": "n", "source": source, "arrival": 0, "max_delay": 0}
        ) + "\n"

        with patch("sys.stdin", io.StringIO(trace)), redirect_stdout(stdout):
            exit_code = main(["schedule"])

        self.assertEqual(exit_code, 0)
        record = json.loads(stdout.getvalue())
        self.assertEqual(record["notifications"][0]["source"], source)

    def test_unicode_is_preserved(self) -> None:
        stdout = io.StringIO()
        trace = '{"id":"café","source":"邮件","arrival":0,"max_delay":0}\n'

        with patch("sys.stdin", io.StringIO(trace)), redirect_stdout(stdout):
            exit_code = main(["schedule"])

        self.assertEqual(exit_code, 0)
        self.assertIn("café", stdout.getvalue())
        self.assertIn("邮件", stdout.getvalue())

    def test_missing_input_file_returns_error(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            exit_code = main(["schedule", "/path/that/does/not/exist"])

        self.assertEqual(exit_code, 2)
        self.assertIn("delaybudget: error:", stderr.getvalue())

    def test_missing_output_parent_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "trace.jsonl"
            input_path.write_text(
                '{"id":"n","arrival":0,"max_delay":0}\n',
                encoding="utf-8",
            )
            output_path = Path(directory) / "missing" / "output.jsonl"
            stderr = io.StringIO()

            with redirect_stderr(stderr):
                exit_code = main(
                    ["schedule", str(input_path), "-o", str(output_path)]
                )

        self.assertEqual(exit_code, 2)
        self.assertFalse(output_path.exists())
        self.assertIn("delaybudget: error:", stderr.getvalue())

    def test_output_directory_is_rejected_and_temp_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "trace.jsonl"
            input_path.write_text(
                '{"id":"n","arrival":0,"max_delay":0}\n',
                encoding="utf-8",
            )
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = main(
                    ["schedule", str(input_path), "-o", str(Path(directory))]
                )
            leftovers = list(Path(directory).glob(f".{Path(directory).name}.*.tmp"))

        self.assertEqual(exit_code, 2)
        self.assertEqual(leftovers, [])
        self.assertIn("delaybudget: error:", stderr.getvalue())

    def test_broken_pipe_is_a_successful_termination(self) -> None:
        with (
            patch("sys.stdin", io.StringIO("")),
            patch("delaybudget.cli._write_batches", side_effect=BrokenPipeError),
            patch("delaybudget.cli._silence_broken_pipe") as silence,
        ):
            exit_code = main(["schedule"])

        self.assertEqual(exit_code, 0)
        silence.assert_called_once_with()

    def test_version(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout), self.assertRaises(SystemExit) as raised:
            main(["--version"])

        self.assertEqual(raised.exception.code, 0)
        self.assertRegex(stdout.getvalue(), r"^delaybudget 1\.0\.0\n$")

    def _run_bad_input(self, text: str) -> str:
        stderr = io.StringIO()
        with patch("sys.stdin", io.StringIO(text)), redirect_stderr(stderr):
            exit_code = main(["schedule"])
        self.assertEqual(exit_code, 2)
        return stderr.getvalue()


if __name__ == "__main__":
    unittest.main()
