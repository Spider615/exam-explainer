"""Importable child-process targets used by solve-attempt tests."""

import os
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
