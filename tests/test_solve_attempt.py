import os
import signal
import tempfile
import time
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from pipeline.solve_attempt import Failure, ProcessResult, SolveFailure, retry, run_process


class RetryTests(unittest.TestCase):
    def test_caps_total_attempts_at_three(self) -> None:
        calls = []

        def attempt(number: int) -> ProcessResult:
            calls.append(number)
            return ProcessResult(False, failure=Failure("transient", "try again", "solve"))

        result = retry(attempt, max_attempts=5, delay_s=0)

        self.assertEqual([1, 2, 3], calls)
        self.assertEqual(3, result.attempts)

    def test_rejects_non_positive_max_attempts(self) -> None:
        with self.assertRaises(ValueError):
            retry(lambda _: ProcessResult(True), max_attempts=0, delay_s=0)

    def test_retries_two_failures_then_returns_third_success(self) -> None:
        calls = []

        def attempt(number: int) -> ProcessResult:
            calls.append(number)
            if number < 3:
                return ProcessResult(False, failure=Failure("transient", "try again", "solve"))
            return ProcessResult(True, value="answer")

        result = retry(attempt, delay_s=0)

        self.assertEqual([1, 2, 3], calls)
        self.assertTrue(result.ok)
        self.assertEqual("answer", result.value)
        self.assertEqual(3, result.attempts)

    def test_stops_after_three_retryable_failures(self) -> None:
        calls = []

        def attempt(number: int) -> ProcessResult:
            calls.append(number)
            return ProcessResult(False, failure=Failure("transient", "try again", "solve"))

        result = retry(attempt, delay_s=0)

        self.assertEqual([1, 2, 3], calls)
        self.assertFalse(result.ok)
        self.assertEqual(3, result.attempts)

    def test_stops_after_one_non_retryable_failure(self) -> None:
        calls = []

        def attempt(number: int) -> ProcessResult:
            calls.append(number)
            return ProcessResult(
                False,
                failure=Failure("configuration", "missing setting", "setup", retryable=False),
            )

        result = retry(attempt, delay_s=0)

        self.assertEqual([1], calls)
        self.assertFalse(result.ok)
        self.assertEqual(1, result.attempts)

    def test_propagates_keyboard_interrupt_without_retrying(self) -> None:
        calls = []

        def attempt(number: int) -> ProcessResult:
            calls.append(number)
            raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            retry(attempt, delay_s=0)

        self.assertEqual([1], calls)


class FailureTests(unittest.TestCase):
    def test_failure_normalizes_reason_and_is_immutable(self) -> None:
        failure = Failure("internal", " one\n two\t" + "x" * 250, "solve")

        self.assertEqual("one two", failure.reason[:7])
        self.assertLessEqual(len(failure.reason), 240)
        with self.assertRaises(FrozenInstanceError):
            failure.reason = "changed"

    def test_solve_failure_uses_public_constructor(self) -> None:
        error = SolveFailure("configuration", " bad\n reason " + "x" * 250, "setup", False)

        self.assertEqual("configuration", error.failure.kind)
        self.assertEqual("setup", error.failure.stage)
        self.assertFalse(error.failure.retryable)
        self.assertLessEqual(len(error.failure.reason), 240)


class ProcessTests(unittest.TestCase):
    def test_timeout_kills_child_before_it_can_write_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "marker.txt"
            result = run_process(
                "tests.process_fixtures",
                "sleep_then_write",
                (str(marker), 0.25),
                timeout_s=0.05,
            )
            time.sleep(0.30)

            self.assertFalse(result.ok)
            self.assertEqual("timeout", result.failure.kind)
            self.assertFalse(marker.exists())

    def test_timeout_kills_sigterm_ignoring_descendant(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "marker.txt"
            ready = Path(directory) / "ready.txt"
            pid_path = Path(directory) / "descendant.pid"
            try:
                result = run_process(
                    "tests.process_fixtures",
                    "spawn_sigterm_ignoring_descendant",
                    (str(marker), str(ready), str(pid_path), 0.80),
                    timeout_s=0.50,
                )
                time.sleep(0.85)

                self.assertFalse(result.ok)
                self.assertEqual("timeout", result.failure.kind)
                self.assertTrue(ready.exists())
                self.assertFalse(marker.exists())
            finally:
                if pid_path.exists():
                    try:
                        os.kill(int(pid_path.read_text(encoding="utf-8")), signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_preserves_structured_solve_failure_from_child(self) -> None:
        result = run_process(
            "tests.process_fixtures", "raise_structured_failure", (), timeout_s=1
        )

        self.assertFalse(result.ok)
        self.assertEqual("upstream", result.failure.kind)
        self.assertEqual("solve", result.failure.stage)
        self.assertFalse(result.failure.retryable)
        self.assertEqual("temporary provider error", result.failure.reason)

    def test_child_exit_without_a_message_becomes_internal_failure(self) -> None:
        result = run_process("tests.process_fixtures", "exit_abruptly", (), timeout_s=1)

        self.assertFalse(result.ok)
        self.assertEqual("internal", result.failure.kind)
        self.assertEqual("process", result.failure.stage)

    def test_spawn_error_returns_safe_internal_failure(self) -> None:
        result = run_process(
            "tests.process_fixtures",
            "sleep_then_write",
            (lambda: None,),
            timeout_s=1,
        )

        self.assertFalse(result.ok)
        self.assertEqual("internal", result.failure.kind)
        self.assertEqual("process", result.failure.stage)


if __name__ == "__main__":
    unittest.main()
