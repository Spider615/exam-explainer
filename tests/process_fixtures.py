"""Importable child-process targets used by solve-attempt tests."""

import multiprocessing
import os
import signal
import time
from pathlib import Path

from pipeline.solve_attempt import Failure, SolveFailure


def sleep_then_write(marker_path: str, delay_s: float) -> None:
    time.sleep(delay_s)
    Path(marker_path).write_text("written", encoding="utf-8")


def raise_structured_failure() -> None:
    raise SolveFailure(
        Failure(
            kind="upstream",
            reason="temporary provider error",
            stage="solve",
            retryable=False,
        )
    )


def exit_abruptly() -> None:
    os._exit(7)


def _ignore_term_then_write(marker_path: str, delay_s: float) -> None:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    time.sleep(delay_s)
    Path(marker_path).write_text("written", encoding="utf-8")


def spawn_sigterm_ignoring_descendant(
    marker_path: str, pid_path: str, delay_s: float
) -> None:
    descendant = multiprocessing.get_context("spawn").Process(
        target=_ignore_term_then_write,
        args=(marker_path, delay_s),
    )
    descendant.start()
    Path(pid_path).write_text(str(descendant.pid), encoding="utf-8")
    time.sleep(delay_s * 2)
