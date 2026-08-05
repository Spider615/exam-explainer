"""Isolated process execution and retry policy for question solves."""

import importlib
import multiprocessing
import os
import signal
import time
from dataclasses import dataclass
from typing import Callable


_MAX_REASON_LENGTH = 240


@dataclass
class Failure:
    kind: str
    reason: str
    stage: str
    retryable: bool = True


@dataclass
class ProcessResult:
    ok: bool
    value: object = None
    failure: Failure | None = None


@dataclass
class RetryResult(ProcessResult):
    attempts: int = 0


class SolveFailure(RuntimeError):
    """An expected failure that can safely cross the process boundary."""

    def __init__(self, failure: Failure):
        self.failure = Failure(
            kind=failure.kind,
            reason=_safe_reason(failure.reason),
            stage=failure.stage,
            retryable=failure.retryable,
        )
        super().__init__(self.failure.reason)


def _safe_reason(reason: object) -> str:
    return " ".join(str(reason).split())[:_MAX_REASON_LENGTH]


def _internal_failure(stage: str = "process") -> Failure:
    return Failure("internal", "Unhandled internal error", stage)


def _process_target(connection, module_name: str, function_name: str, args: tuple) -> None:
    try:
        if os.name == "posix":
            os.setsid()
        target = getattr(importlib.import_module(module_name), function_name)
        connection.send(("ok", target(*args)))
    except SolveFailure as error:
        connection.send(("failure", error.failure))
    except BaseException:
        # Do not send tracebacks or exception messages from an untrusted child.
        try:
            connection.send(("failure", _internal_failure()))
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        connection.close()


def _stop_process(process: multiprocessing.Process) -> None:
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (PermissionError, ProcessLookupError):
            if process.is_alive():
                process.terminate()
        process.join(0.1)
        try:
            os.killpg(process.pid, 0)
        except (PermissionError, ProcessLookupError):
            pass
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (PermissionError, ProcessLookupError):
                pass
        process.join(0.1)
        return

    if not process.is_alive():
        return
    process.terminate()
    process.join(0.1)
    if process.is_alive():
        process.kill()
        process.join(0.1)


def run_process(
    module_name: str, function_name: str, args: tuple, timeout_s: float
) -> ProcessResult:
    """Run an importable target in a spawned process with a hard deadline."""
    context = multiprocessing.get_context("spawn")
    parent_connection, child_connection = context.Pipe(duplex=False)
    process = context.Process(
        target=_process_target,
        args=(child_connection, module_name, function_name, tuple(args)),
    )
    process.start()
    child_connection.close()
    try:
        if parent_connection.poll(timeout_s):
            try:
                status, payload = parent_connection.recv()
            except EOFError:
                return ProcessResult(False, failure=_internal_failure())
            process.join(0.1)
            if status == "ok":
                return ProcessResult(True, value=payload)
            return ProcessResult(False, failure=payload)

        if process.is_alive():
            _stop_process(process)
            return ProcessResult(
                False,
                failure=Failure("timeout", "Solve attempt exceeded its deadline", "process"),
            )

        process.join(0.1)
        if parent_connection.poll(0.05):
            try:
                status, payload = parent_connection.recv()
            except EOFError:
                return ProcessResult(False, failure=_internal_failure())
            if status == "ok":
                return ProcessResult(True, value=payload)
            return ProcessResult(False, failure=payload)
        return ProcessResult(False, failure=_internal_failure())
    finally:
        parent_connection.close()
        if process.is_alive():
            _stop_process(process)


def retry(
    attempt: Callable[[int], ProcessResult],
    max_attempts: int = 3,
    delay_s: float = 3,
    on_retry: Callable[[int, Failure], None] | None = None,
) -> RetryResult:
    """Run attempts until success or the retry policy reaches a terminal state."""
    last_result = ProcessResult(False, failure=_internal_failure("retry"))
    for number in range(1, max_attempts + 1):
        try:
            result = attempt(number)
        except BaseException:
            result = ProcessResult(False, failure=_internal_failure("retry"))
        if result.ok:
            return RetryResult(True, value=result.value, attempts=number)

        failure = result.failure or _internal_failure("retry")
        last_result = ProcessResult(False, failure=failure)
        if not failure.retryable or number == max_attempts:
            return RetryResult(False, failure=failure, attempts=number)
        if on_retry is not None:
            on_retry(number, failure)
        if delay_s:
            time.sleep(delay_s)

    return RetryResult(False, failure=last_result.failure, attempts=0)
