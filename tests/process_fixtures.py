"""Importable child-process targets used by solve-attempt tests."""

import multiprocessing
import os
import signal
import time
from pathlib import Path

from pipeline.solve_attempt import SolveFailure


def sleep_then_write(marker_path: str, delay_s: float) -> None:
    time.sleep(delay_s)
    Path(marker_path).write_text("written", encoding="utf-8")


def raise_structured_failure() -> None:
    raise SolveFailure("upstream", "temporary provider error", "solve", retryable=False)


def exit_abruptly() -> None:
    os._exit(7)


def _ignore_term_then_write(marker_path: str, ready_path: str, delay_s: float) -> None:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    Path(ready_path).write_text("ready", encoding="utf-8")
    time.sleep(delay_s)
    Path(marker_path).write_text("written", encoding="utf-8")


def spawn_sigterm_ignoring_descendant(
    marker_path: str, ready_path: str, pid_path: str, delay_s: float
) -> None:
    descendant = multiprocessing.get_context("spawn").Process(
        target=_ignore_term_then_write,
        args=(marker_path, ready_path, delay_s),
    )
    descendant.start()
    Path(pid_path).write_text(str(descendant.pid), encoding="utf-8")
    time.sleep(delay_s * 2)
