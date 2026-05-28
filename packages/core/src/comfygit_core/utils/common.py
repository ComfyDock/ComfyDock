"""Common utilities for ComfyUI Environment Capture."""

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from ..logging.logging_config import get_logger
from ..models.exceptions import CDProcessError
from .redaction import redact_command, redact_sensitive_text

logger = get_logger(__name__)


def run_command(
    cmd: list[str],
    cwd: Path | None = None,
    timeout: int | None = 30,
    capture_output: bool = True,
    text: bool = True,
    check: bool = False,
    env: dict | None = None,
    output_callback: Callable[[str], None] | None = None,
) -> subprocess.CompletedProcess:
    """Run a subprocess command with proper error handling.

    Args:
        cmd: Command and arguments as a list
        cwd: Working directory for the command
        timeout: Command timeout in seconds
        capture_output: Whether to capture stdout/stderr
        text: Whether to decode output as text
        check: Whether to raise exception on non-zero exit code
        env: Environment variables to pass to subprocess
        output_callback: Optional callback for streaming decoded output lines

    Returns:
        CompletedProcess instance

    Raises:
        CDProcessError: If command fails and check=True
        subprocess.TimeoutExpired: If command times out
    """
    safe_cmd = redact_command(cmd)
    try:
        logger.debug(f"Running command: {safe_cmd}")
        if cwd:
            logger.debug(f"Working directory: {cwd}")

        if output_callback is not None:
            if not text:
                raise ValueError("output_callback requires text=True")

            process = subprocess.Popen(
                cmd,
                cwd=str(cwd) if cwd else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
                bufsize=1,
            )
            output_parts: list[str] = []
            try:
                assert process.stdout is not None
                for line in process.stdout:
                    output_parts.append(line)
                    if not capture_output:
                        sys.stdout.write(line)
                        sys.stdout.flush()
                    stripped = line.rstrip("\r\n")
                    if stripped:
                        output_callback(redact_sensitive_text(stripped))
                returncode = process.wait(timeout=timeout)
            except Exception:
                process.kill()
                process.wait()
                raise

            result = subprocess.CompletedProcess(
                args=cmd,
                returncode=returncode,
                stdout="".join(output_parts),
                stderr="",
            )
            if check and result.returncode != 0:
                raise subprocess.CalledProcessError(
                    result.returncode,
                    cmd,
                    output=result.stdout,
                    stderr=result.stderr,
                )
        else:
            result = subprocess.run(
                cmd,
                cwd=str(cwd) if cwd else None,
                check=check,
                timeout=timeout,
                capture_output=capture_output,
                text=text,
                env=env
            )

        return result

    except subprocess.CalledProcessError as e:
        # Transform CalledProcessError into our custom exception
        error_msg = f"Command failed with exit code {e.returncode}: {safe_cmd}"
        if e.stderr:
            error_msg += f"\nStderr: {redact_sensitive_text(e.stderr)}"
        logger.error(error_msg)
        raise CDProcessError(
            message=error_msg,
            command=cmd,
            stderr=e.stderr,
            stdout=e.stdout,
            returncode=e.returncode
        ) from e
    except subprocess.TimeoutExpired:
        error_msg = f"Command timed out after {timeout}s: {safe_cmd}"
        logger.error(error_msg)
        # Let TimeoutExpired propagate - it's specific and useful
        raise
    except Exception as e:
        error_msg = f"Error running command {safe_cmd}: {redact_sensitive_text(e)}"
        logger.error(error_msg)
        raise

def format_size(size_bytes: int) -> str:
    """Format a size in bytes as human-readable string.

    Args:
        size_bytes: Size in bytes

    Returns:
        Human-readable size string (e.g., "1.5 MB")
    """
    if size_bytes == 0:
        return "0 B"

    size_names = ["B", "KB", "MB", "GB", "TB"]
    size_index = 0
    size = float(size_bytes)

    while size >= 1024.0 and size_index < len(size_names) - 1:
        size /= 1024.0
        size_index += 1

    if size_index == 0:
        return f"{int(size)} {size_names[size_index]}"
    else:
        return f"{size:.1f} {size_names[size_index]}"


def log_pyproject_content(pyproject_path: Path, context: str = "") -> None:
    """Log pyproject.toml content in a nicely formatted way.

    Args:
        pyproject_path: Path to pyproject.toml file
        context: Optional context string for the log message
    """
    try:
        content = pyproject_path.read_text(encoding='utf-8')
        # Add indentation to each line for nice formatting
        indented_lines = ['' + line for line in content.split('\n')]
        formatted_content = '\n'.join(indented_lines)

        # Create the log message with separator lines
        separator = '-' * 60
        if context:
            msg = f"{context}:\n{separator}\n{formatted_content}\n{separator}"
        else:
            msg = f"pyproject.toml content:\n{separator}\n{formatted_content}\n{separator}"

        # Log as a single INFO message (change to DEBUG if too verbose)
        logger.info(msg)
    except Exception as e:
        logger.debug(f"Could not log pyproject.toml: {e}")

def log_requirements_content(requirements_file: Path, show_all: bool = True) -> None:
    """Log the compiled requirements file content.

    Args:
        requirements_file: Path to the compiled requirements file
        show_all: If True, show all lines, otherwise show a summary
    """
    try:
        content = requirements_file.read_text(encoding='utf-8')
        lines = content.split('\n')

        # Count non-comment, non-empty lines
        package_lines = [line for line in lines if line.strip() and not line.strip().startswith('#')]

        #
        separator = '=' * 60
        msg_lines = [
            f"Compiled requirements file ({len(package_lines)} packages):",
            separator
        ]

        # Show first 10 and last 5 packages if there are many
        if len(lines) > 50 and not show_all:
            msg_lines.extend(lines[:30])
            msg_lines.append(f"... ({len(lines) - 35} more lines) ...")
            msg_lines.extend(lines[-5:])
        else:
            msg_lines.extend(lines)

        msg_lines.append(separator)

        logger.info('\n'.join(msg_lines))
    except Exception as e:
        logger.debug(f"Could not log requirements file: {e}")
