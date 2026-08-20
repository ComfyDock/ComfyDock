"""Security-aware logging primitives for CLI-owned log files."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from comfygit_core.security import harden_private_file, redact_sensitive_text


class RedactingFormatter(logging.Formatter):
    """Redact sensitive values after normal formatting, including tracebacks."""

    def format(self, record: logging.LogRecord) -> str:
        return redact_sensitive_text(super().format(record))


class PrivateRotatingFileHandler(RotatingFileHandler):
    """Rotating handler whose active log is always owner-only on POSIX."""

    def _open(self):
        stream = super()._open()
        harden_private_file(Path(self.baseFilename))
        return stream


class PrivateFileHandler(logging.FileHandler):
    """Non-rotating file handler whose log is owner-only on POSIX."""

    def _open(self):
        stream = super()._open()
        harden_private_file(Path(self.baseFilename))
        return stream


def harden_existing_logs(logs_dir: Path) -> None:
    """Best-effort hardening for existing ComfyGit log files."""
    if not logs_dir.exists():
        return
    for path in logs_dir.rglob("*.log*"):
        if path.is_file():
            harden_private_file(path)
