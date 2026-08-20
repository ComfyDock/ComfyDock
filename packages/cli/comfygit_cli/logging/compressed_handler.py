"""Dual-output rotating file handler with real-time log compression."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from comfygit_core.security import harden_private_file

from .log_compressor import LogCompressor


class CompressedDualHandler(RotatingFileHandler):
    """File handler that writes both full and compressed logs simultaneously.

    Writes to:
    - full.log: Complete verbose logs with rotation
    - compressed.log: Real-time compressed version

    The compressed log uses a lighter format optimized for token count reduction
    while preserving all semantic content.
    """

    def __init__(
        self,
        log_dir: Path,
        env_name: str,
        compression_level: str = 'medium',
        maxBytes: int = 10 * 1024 * 1024,
        backupCount: int = 5,
        encoding: str = 'utf-8'
    ):
        """Initialize dual-output handler.

        Args:
            log_dir: Directory for log files (e.g., workspace/logs/test1/)
            env_name: Environment name (for header comments)
            compression_level: Compression level (light, medium, aggressive)
            maxBytes: Max size before rotation (applies to full.log)
            backupCount: Number of backup files to keep
            encoding: File encoding
        """
        # Ensure log directory exists
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)

        # Initialize base handler for full.log
        full_log = log_dir / 'full.log'
        super().__init__(full_log, maxBytes=maxBytes, backupCount=backupCount, encoding=encoding)

        # Store instance variables for rotation
        self.env_name = env_name
        self.compression_level = compression_level
        self.encoding = encoding

        # Open compressed.log
        self.compressed_path = log_dir / 'compressed.log'
        self.compressed_file = open(self.compressed_path, 'a', encoding=encoding)
        harden_private_file(self.compressed_path)

        # Initialize compressor
        self.compressor = LogCompressor(compression_level=compression_level)

        # Write header to compressed log
        self._write_compressed_header(env_name, compression_level)

    def _open(self):
        stream = super()._open()
        harden_private_file(Path(self.baseFilename))
        return stream

    def _write_compressed_header(self, env_name: str, level: str) -> None:
        """Write header to compressed log file."""
        from datetime import datetime
        self.compressed_file.write(f"# Compressed logs for environment: {env_name}\n")
        self.compressed_file.write(f"# Compression level: {level}\n")
        self.compressed_file.write(f"# Session started: {datetime.now().isoformat()}\n")
        self.compressed_file.write("#\n")
        self.compressed_file.flush()

    def emit(self, record: logging.LogRecord) -> None:
        """Emit a record to both full and compressed logs.

        Args:
            record: Log record to emit
        """
        try:
            # Write to full.log via parent handler
            super().emit(record)

            # Format the record for compression
            formatted = self.format(record)

            # Compress and write to compressed.log
            compressed = self.compressor.compress_record(formatted)
            if compressed:  # Empty string means skip this line
                self.compressed_file.write(compressed + '\n')
                self.compressed_file.flush()

        except Exception:
            self.handleError(record)

    def doRollover(self) -> None:
        """Override to rotate both full.log and compressed.log together."""
        import os

        # First, rotate full.log using parent
        super().doRollover()

        # Close current compressed file
        if self.compressed_file:
            # Write dictionary before closing
            dictionary = self.compressor.get_dictionary()
            if dictionary:
                self.compressed_file.write(dictionary)
            self.compressed_file.close()

        # Rotate compressed backups: .3→.4, .2→.3, .1→.2
        for i in range(self.backupCount - 1, 0, -1):
            sfn = f"{self.compressed_path}.{i}"
            dfn = f"{self.compressed_path}.{i + 1}"
            if os.path.exists(sfn):
                if os.path.exists(dfn):
                    os.remove(dfn)
                os.rename(sfn, dfn)

        # Rename current compressed.log → compressed.log.1
        dfn = f"{self.compressed_path}.1"
        if os.path.exists(dfn):
            os.remove(dfn)
        if os.path.exists(self.compressed_path):
            os.rename(self.compressed_path, dfn)

        # Reopen compressed.log for new session
        self.compressed_file = open(self.compressed_path, 'a', encoding=self.encoding)
        harden_private_file(self.compressed_path)

        # Create new compressor for new session
        self.compressor = LogCompressor(compression_level=self.compression_level)

        # Write header to new compressed log
        self._write_compressed_header(self.env_name, self.compression_level)

    def close(self) -> None:
        """Close both log files and write dictionary."""
        try:
            # Write module dictionary to compressed log
            dictionary = self.compressor.get_dictionary()
            if dictionary:
                self.compressed_file.write(dictionary)

            # Close compressed file
            self.compressed_file.close()

            # Close full log via parent
            super().close()

        except Exception:
            # Ensure we don't break on cleanup
            pass
