"""Logging configuration for ComfyUI Environment Capture."""

import logging
import logging.handlers
import sys
from pathlib import Path

# Default log format
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
SIMPLE_FORMAT = "%(levelname)s - %(message)s"
DETAILED_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s"


def setup_logging(
    level: str = "INFO",
    log_file: Path | None = None,
    simple_format: bool = False,
    use_rotation: bool = True,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
    console_level: str | None = None,
    file_level: str | None = None
) -> None:
    """Configure logging for the application.

    Args:
        level: Default logging level (DEBUG, INFO, WARNING, ERROR)
        log_file: Optional file path for logging output
        simple_format: Use simple format for console output
        use_rotation: Use rotating file handler for log files
        max_bytes: Maximum size of each log file in bytes (default 10MB)
        backup_count: Number of backup files to keep (default 5)
        console_level: Override console logging level (defaults to 'level')
        file_level: Override file logging level (defaults to DEBUG)
    """
    default_level = getattr(logging, level.upper(), logging.INFO)
    console_log_level = getattr(logging, (console_level or level).upper(), logging.INFO)
    file_log_level = getattr(logging, (file_level or "DEBUG").upper(), logging.DEBUG)

    # Root logger configuration - set to lowest of all levels
    root_logger = logging.getLogger()
    root_logger.setLevel(min(default_level, console_log_level, file_log_level))

    # Remove existing handlers
    root_logger.handlers.clear()

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_log_level)
    console_format = SIMPLE_FORMAT if simple_format else LOG_FORMAT
    console_handler.setFormatter(logging.Formatter(console_format))
    root_logger.addHandler(console_handler)

    # File handler (if specified)
    if log_file:
        # Ensure log directory exists
        log_file = Path(log_file)
        log_file.parent.mkdir(parents=True, exist_ok=True)

        if use_rotation:
            # Use rotating file handler
            file_handler = logging.handlers.RotatingFileHandler(
                log_file,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding='utf-8'
            )
        else:
            # Use regular file handler
            file_handler = logging.FileHandler(log_file, encoding='utf-8')

        file_handler.setLevel(file_log_level)  # Use specified file log level
        file_handler.setFormatter(logging.Formatter(DETAILED_FORMAT))
        root_logger.addHandler(file_handler)

        # Log the start of a new session
        root_logger.debug("🟩" * 50)
        root_logger.debug("=" * 80)
        root_logger.debug("New logging session started")
        root_logger.debug("=" * 80)
        root_logger.debug("🟩" * 50)

    # Set specific logger levels
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance for the given module.

    Args:
        name: Module name (typically __name__)

    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)
