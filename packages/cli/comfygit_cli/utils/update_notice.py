"""Asynchronous CLI update notice helpers."""

from __future__ import annotations

import os
import sys
import threading
from dataclasses import dataclass

from . import update_checker


@dataclass
class UpdateCheckHandle:
    done: threading.Event
    result: update_checker.UpdateCheckResult | None = None


def _is_interactive_session() -> bool:
    # Keep stdout clean for piping and avoid noisy CI output.
    if os.environ.get("CI"):
        return False
    return sys.stdout.isatty()


def start_update_check_async(args: object) -> UpdateCheckHandle | None:
    """Start an update check in a daemon thread, returning a handle.

    Returns None if checks are disabled or the session is non-interactive.
    """
    if update_checker.is_update_check_disabled():
        return None
    if not _is_interactive_session():
        return None

    # Avoid recursion/noise for the updater itself.
    if getattr(args, "command", None) == "update":
        return None

    done = threading.Event()
    handle = UpdateCheckHandle(done=done)

    def _worker() -> None:
        try:
            handle.result = update_checker.check_for_update()
        finally:
            done.set()

    t = threading.Thread(target=_worker, name="comfygit-update-check", daemon=True)
    t.start()
    return handle


def maybe_print_update_notice(handle: UpdateCheckHandle | None) -> None:
    """Print a one-line update notice to stderr if a completed result says to."""
    if handle is None:
        return
    if not handle.done.is_set():
        return
    result = handle.result
    if result is None or not result.should_notify:
        return

    print(
        update_checker.format_update_notice(result.current_version, result.latest_version),
        file=sys.stderr,
    )
    update_checker.mark_notified(result.latest_version)

