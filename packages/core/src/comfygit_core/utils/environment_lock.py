"""Environment operation lock utilities."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import IO

from ..models.exceptions import CDEnvironmentError


class EnvironmentOperationLock:
    """Cross-process, cross-thread lock for environment mutations."""

    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        self._thread_lock = threading.Lock()
        self._depth = 0
        self._file: IO[str] | None = None
        self._owner_thread: int | None = None

    def __enter__(self) -> "EnvironmentOperationLock":
        current_thread = threading.get_ident()
        with self._thread_lock:
            if self._depth > 0 and self._owner_thread != current_thread:
                raise CDEnvironmentError(self._lock_error_message())
            if self._depth == 0:
                self._acquire_file_lock()
                self._owner_thread = current_thread
            self._depth += 1
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        with self._thread_lock:
            self._depth -= 1
            if self._depth == 0:
                self._owner_thread = None
                self._release_file_lock()
        return False

    def _lock_error_message(self) -> str:
        return (
            "Another ComfyGit operation is running on this environment. "
            "Wait for it to complete. "
            f"If this persists, delete the lock file: {self.lock_path}"
        )

    def _acquire_file_lock(self) -> None:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self.lock_path, "a+")

        try:
            self._file.seek(0)
            if sys.platform == "win32":
                import msvcrt

                try:
                    msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as e:
                    raise CDEnvironmentError(self._lock_error_message()) from e
            else:
                import fcntl

                try:
                    fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as e:
                    raise CDEnvironmentError(self._lock_error_message()) from e

            try:
                self._file.seek(0)
                self._file.truncate()
                self._file.write(str(os.getpid()))
                self._file.flush()
            except OSError:
                pass
        except Exception:
            self._file.close()
            self._file = None
            raise

    def _release_file_lock(self) -> None:
        if not self._file:
            return

        try:
            self._file.seek(0)
            if sys.platform == "win32":
                import msvcrt

                try:
                    msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl

                try:
                    fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
        finally:
            self._file.close()
            self._file = None
