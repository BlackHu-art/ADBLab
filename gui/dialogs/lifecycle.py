"""Small helpers for dialog signal and worker cleanup."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QThread


def safe_disconnect(signal: Any, handler: Callable | None = None) -> None:
    try:
        if handler is None:
            signal.disconnect()
        else:
            signal.disconnect(handler)
    except (TypeError, RuntimeError):
        pass


def wait_for_thread_later(thread: QThread, timeout_ms: int) -> None:
    threading.Thread(target=lambda: thread.wait(timeout_ms), daemon=True).start()


def wait_for_threads_later(threads: list[QThread], timeout_ms: int) -> None:
    threading.Thread(
        target=lambda: [thread.wait(timeout_ms) for thread in threads],
        daemon=True,
    ).start()
