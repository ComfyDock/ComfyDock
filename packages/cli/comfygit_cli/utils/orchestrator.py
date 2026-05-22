"""Orchestrator utility functions for CLI commands."""

import json
import os
import signal
import sys
import time
from pathlib import Path

from comfygit_core.runtime import (
    SWITCH_STATUS_FILE,
)
from comfygit_core.runtime import (
    read_switch_status as core_read_switch_status,
)


def read_orchestrator_pid(metadata_dir: Path) -> int | None:
    """Read orchestrator PID from file."""
    pid_file = metadata_dir / ".orchestrator.pid"
    if not pid_file.exists():
        return None

    try:
        return int(pid_file.read_text().strip())
    except ValueError:
        return None


def _is_process_running(pid: int) -> bool:
    """Check if a process is running (cross-platform)."""
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        SYNCHRONIZE = 0x00100000
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    else:
        try:
            os.kill(pid, 0)  # Signal 0 checks if process exists
            return True
        except ProcessLookupError:
            return False


def is_orchestrator_running(metadata_dir: Path) -> tuple[bool, int | None]:
    """Check if orchestrator is running.

    Returns:
        (is_running, pid) tuple
    """
    pid = read_orchestrator_pid(metadata_dir)
    if not pid:
        return (False, None)

    if _is_process_running(pid):
        return (True, pid)
    else:
        return (False, pid)  # PID file exists but process is dead


def read_switch_status(metadata_dir: Path) -> dict | None:
    """Read environment switch status."""
    return core_read_switch_status(metadata_dir)


def safe_write_command(metadata_dir: Path, command: dict) -> None:
    """
    Atomically write command file for orchestrator.

    Uses temp file + atomic rename to prevent partial reads.
    """
    temp_file = metadata_dir / f".cmd.tmp.{os.getpid()}"

    try:
        with open(temp_file, 'w') as f:
            json.dump(command, f)

        # Atomic rename
        temp_file.replace(metadata_dir / ".cmd")
    finally:
        if temp_file.exists():
            temp_file.unlink()


def _kill_process(pid: int, force: bool = False) -> bool:
    """Kill a process (cross-platform).

    Args:
        pid: Process ID to kill
        force: If True, force kill immediately

    Returns:
        True if kill signal sent, False if process not found
    """
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        PROCESS_TERMINATE = 0x0001
        handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
        if handle:
            result = kernel32.TerminateProcess(handle, 1)
            kernel32.CloseHandle(handle)
            return bool(result)
        return False
    else:
        try:
            if force:
                os.kill(pid, signal.SIGKILL)
            else:
                os.kill(pid, signal.SIGTERM)
            return True
        except ProcessLookupError:
            return False


def kill_orchestrator_process(pid: int, force: bool = False) -> bool:
    """Kill orchestrator process.

    Args:
        pid: Process ID to kill
        force: If True, kill immediately without graceful shutdown

    Returns:
        True if process was killed, False if already dead
    """
    if not _is_process_running(pid):
        return False  # Already dead

    if force:
        return _kill_process(pid, force=True)

    # Try graceful shutdown first
    _kill_process(pid, force=False)

    # Wait for graceful shutdown (3s)
    for _ in range(30):
        time.sleep(0.1)
        if not _is_process_running(pid):
            return True  # Process died

    # Still alive, force kill
    _kill_process(pid, force=True)
    return True


def cleanup_orchestrator_state(metadata_dir: Path, preserve_config: bool = True) -> list[str]:
    """Clean up orchestrator state files.

    Args:
        metadata_dir: Metadata directory path
        preserve_config: If True, keep workspace_config.json

    Returns:
        List of removed file names
    """
    files_to_remove = [
        ".orchestrator.pid",
        ".control_port",
        ".cmd",
        ".switch_request.json",
        SWITCH_STATUS_FILE,
        ".switch.lock",
        ".startup_state.json",
    ]

    removed = []

    # Remove specific files
    for filename in files_to_remove:
        file_path = metadata_dir / filename
        if file_path.exists():
            try:
                file_path.unlink()
                removed.append(filename)
            except OSError:
                pass

    # Remove temp command files
    for temp_file in metadata_dir.glob(".cmd.tmp.*"):
        try:
            temp_file.unlink()
            removed.append(temp_file.name)
        except OSError:
            pass

    return removed


def format_uptime(seconds: float) -> str:
    """Format uptime in human-readable format."""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        minutes = int(seconds / 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    else:
        hours = int(seconds / 3600)
        minutes = int((seconds % 3600) / 60)
        secs = int(seconds % 60)
        return f"{hours}h {minutes}m {secs}s"


def get_orchestrator_uptime(metadata_dir: Path, pid: int) -> float | None:
    """Get orchestrator uptime in seconds.

    Reads process start time from /proc on Linux.
    Returns None if cannot determine.
    """
    try:
        # Linux: read from /proc
        stat_file = Path(f"/proc/{pid}/stat")
        if stat_file.exists():
            stat = stat_file.read_text()
            # Field 22 is starttime (clock ticks since boot)
            fields = stat.split()
            start_ticks = int(fields[21])

            # Get system boot time and clock ticks per second
            with open("/proc/uptime") as f:
                uptime_secs = float(f.read().split()[0])

            # Calculate process start time
            clk_tck = os.sysconf(os.sysconf_names['SC_CLK_TCK'])
            process_start = start_ticks / clk_tck
            current_uptime = uptime_secs

            return current_uptime - process_start
    except (FileNotFoundError, ValueError, OSError):
        pass

    return None


def tail_log_file(log_file: Path, num_lines: int = 50) -> list[str]:
    """Tail last N lines from log file."""
    if not log_file.exists():
        return []

    try:
        with open(log_file) as f:
            lines = f.readlines()
            return lines[-num_lines:]
    except OSError:
        return []


def follow_log_file(log_file: Path, poll_interval: float = 0.3) -> None:
    """Follow a log file using polling (cross-platform, no inotify).

    Starts from end of file and prints new lines as they appear.
    Handles file truncation (log rotation).
    """
    with open(log_file) as f:
        f.seek(0, 2)
        while True:
            line = f.readline()
            if line:
                print(line, end='')
            else:
                current_pos = f.tell()
                f.seek(0, 2)
                if f.tell() < current_pos:
                    # File was truncated (log rotation), start from beginning
                    f.seek(0)
                else:
                    f.seek(current_pos)
                time.sleep(poll_interval)
