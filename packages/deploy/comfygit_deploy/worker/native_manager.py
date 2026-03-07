"""Native process manager for running ComfyUI without Docker.

Uses `cg` CLI directly to import environments and run ComfyUI processes.
"""

import asyncio
import os
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import aiohttp

from ..commands.dev import get_dev_nodes


@dataclass
class ProcessInfo:
    """Info about a running ComfyUI process."""

    pid: int
    port: int
    returncode: int | None = None


@dataclass
class DeployResult:
    """Result of a deploy operation."""

    success: bool
    skipped: bool = False
    error: str | None = None


@dataclass
class ProcessLogs:
    """Captured process output."""

    stdout: list[str]
    stderr: list[str]


class NativeManager:
    """Manages ComfyUI instances as native processes."""

    def __init__(self, workspace_path: Path):
        """Initialize native manager.

        Args:
            workspace_path: Path to ComfyGit workspace
        """
        self.workspace_path = workspace_path
        self._processes: dict[str, subprocess.Popen] = {}
        self._log_buffers: dict[str, list[str]] = {}  # Ring buffers for log capture
        self._max_log_lines: int = 1000  # Keep last N lines per instance
        self._log_threads: dict[str, threading.Thread] = {}

    def _ensure_log_buffer(self, instance_id: str) -> list[str]:
        """Create the ring buffer for an instance if needed."""
        return self._log_buffers.setdefault(instance_id, [])

    def _append_log_line(self, instance_id: str, line: str) -> None:
        """Append a line to the in-memory log buffer."""
        buf = self._ensure_log_buffer(instance_id)
        buf.append(line)
        if len(buf) > self._max_log_lines:
            del buf[0 : len(buf) - self._max_log_lines]

    def recover_instance_logs(self, instance_id: str, pid: int) -> None:
        """Try to re-attach log reading for a recovered instance.

        When the worker restarts, running instances have no log reader thread.
        This attempts to read from /proc/{pid}/fd/1 (stdout) to capture ongoing
        output, and seeds the buffer with a recovery notice.
        """
        if instance_id in self._log_threads and self._log_threads[instance_id].is_alive():
            return  # Already have a reader

        buf = self._ensure_log_buffer(instance_id)
        buf.append(f"[worker] Recovered instance (PID {pid}) — log capture re-attached")

        # Try to tail the process's stdout via /proc
        fd_path = Path(f"/proc/{pid}/fd/1")
        if not fd_path.exists():
            buf.append(f"[worker] Cannot read /proc/{pid}/fd/1 — process stdout not accessible")
            return

        try:
            # Open the fd in non-blocking read mode
            fd = os.open(str(fd_path), os.O_RDONLY | os.O_NONBLOCK)
        except (OSError, PermissionError) as exc:
            buf.append(f"[worker] Cannot open /proc/{pid}/fd/1: {exc}")
            return

        def _tail_proc_fd():
            """Background thread to read from the process fd."""
            try:
                f = os.fdopen(fd, "r", errors="replace")
                for line in f:
                    self._append_log_line(instance_id, line.rstrip())
            except Exception:
                pass

        thread = threading.Thread(target=_tail_proc_fd, daemon=True, name=f"log-recover-{instance_id}")
        thread.start()
        self._log_threads[instance_id] = thread

    def environment_exists(self, environment_name: str) -> bool:
        """Check if an environment is fully set up.

        An environment is considered to exist if its ComfyUI directory is present.
        This matches the RunPod script behavior for restart detection.

        Args:
            environment_name: Name of the environment

        Returns:
            True if environment has ComfyUI installed
        """
        comfyui_path = (
            self.workspace_path / "environments" / environment_name / "ComfyUI"
        )
        return comfyui_path.is_dir()

    def delete_environment(self, environment_name: str) -> bool:
        """Delete an environment directory.

        Args:
            environment_name: Name of the environment to delete

        Returns:
            True if deleted, False if not found
        """
        import shutil

        env_path = self.workspace_path / "environments" / environment_name
        if env_path.is_dir():
            shutil.rmtree(env_path)
            return True
        return False

    async def deploy(
        self,
        instance_id: str,
        environment_name: str,
        import_source: str,
        branch: str | None = None,
    ) -> DeployResult:
        """Deploy an environment by cloning from git.

        If the environment already exists (has ComfyUI directory), skips import
        and returns success with skipped=True.

        Args:
            instance_id: Unique instance identifier
            environment_name: Name for the environment
            import_source: Git URL to import from
            branch: Optional branch/tag to checkout

        Returns:
            DeployResult with success/skipped/error status
        """
        # Check if environment already exists (e.g., worker restart)
        if self.environment_exists(environment_name):
            # Still apply dev nodes in case config changed
            self._append_log_line(instance_id, "Environment already exists. Skipping import.")
            self._apply_dev_nodes(environment_name)
            return DeployResult(success=True, skipped=True)

        # Build import command
        cmd = [
            "cg",
            "import",
            import_source,
            "--name",
            environment_name,
            "-y",
            "--models",
            "all",
        ]
        if branch:
            cmd.extend(["--branch", branch])

        env = os.environ.copy()
        env["COMFYGIT_HOME"] = str(self.workspace_path)

        # Run import in subprocess
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        output_lines: list[str] = []
        stdout_stream = proc.stdout
        if stdout_stream is not None:
            while True:
                line = await stdout_stream.readline()
                if not line:
                    break
                text = line.decode(errors="replace").rstrip()
                output_lines.append(text)
                self._append_log_line(instance_id, text)

        await proc.wait()

        if proc.returncode != 0:
            output = "\n".join(output_lines)
            return DeployResult(
                success=False,
                error=f"Import failed for {instance_id}: {output}",
            )

        # Apply dev nodes if configured
        self._apply_dev_nodes(environment_name)

        return DeployResult(success=True, skipped=False)

    def _apply_dev_nodes(self, environment_name: str) -> None:
        """Apply configured dev nodes to an environment.

        Creates symlinks and tracks with cg node add --dev.
        """
        dev_nodes = get_dev_nodes()
        if not dev_nodes:
            return

        env_path = self.workspace_path / "environments" / environment_name
        custom_nodes = env_path / "ComfyUI" / "custom_nodes"

        if not custom_nodes.exists():
            return

        env = os.environ.copy()
        env["COMFYGIT_HOME"] = str(self.workspace_path)

        for node in dev_nodes:
            target = custom_nodes / node.name
            source = Path(node.path)

            if not source.exists():
                continue

            # Create/update symlink
            if target.is_symlink():
                if target.resolve() != source.resolve():
                    target.unlink()
                    target.symlink_to(source)
            elif target.exists():
                shutil.rmtree(target)
                target.symlink_to(source)
            else:
                target.symlink_to(source)

            # Track with cg node add --dev
            cmd = ["cg", "-e", environment_name, "node", "add", node.name, "--dev"]
            subprocess.run(cmd, env=env, capture_output=True)

    def start(
        self,
        instance_id: str,
        environment_name: str,
        port: int,
        listen_host: str = "0.0.0.0",
    ) -> ProcessInfo | None:
        """Start ComfyUI process for an environment.

        Args:
            instance_id: Instance identifier for tracking
            environment_name: Environment to run
            port: Port for ComfyUI
            listen_host: Host to listen on

        Returns:
            ProcessInfo if started successfully, None otherwise
        """
        if instance_id in self._processes:
            proc = self._processes[instance_id]
            if proc.poll() is None:
                # Already running
                return ProcessInfo(pid=proc.pid, port=port)

        cmd = [
            "cg",
            "-e",
            environment_name,
            "run",
            "--no-sync",  # Skip sync since we just imported
            "--listen",
            listen_host,
            "--port",
            str(port),
        ]

        env = os.environ.copy()
        env["COMFYGIT_HOME"] = str(self.workspace_path)

        try:
            proc = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,  # Detach from parent
                text=True,
                bufsize=1,  # Line buffered
            )
            self._processes[instance_id] = proc
            self._ensure_log_buffer(instance_id)

            # Start background thread to read output
            import threading
            def read_output():
                try:
                    for line in proc.stdout:
                        self._append_log_line(instance_id, line.rstrip())
                except Exception:
                    pass

            thread = threading.Thread(target=read_output, daemon=True)
            thread.start()

            return ProcessInfo(pid=proc.pid, port=port)
        except Exception as e:
            print(f"Failed to start {instance_id}: {e}")
            return None

    def stop(self, instance_id: str, pid: int | None = None) -> bool:
        """Stop a running ComfyUI process.

        Args:
            instance_id: Instance to stop
            pid: Optional PID to kill if process not tracked in memory

        Returns:
            True if stopped (or wasn't running)
        """
        proc = self._processes.get(instance_id)

        # If we have a tracked process, use it
        if proc:
            if proc.poll() is not None:
                # Already dead
                return True

            try:
                # Send SIGTERM to process group
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)

                # Wait up to 5 seconds for graceful shutdown
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    # Force kill
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    proc.wait(timeout=2)

                return True
            except ProcessLookupError:
                return True
            except Exception as e:
                print(f"Error stopping {instance_id}: {e}")
                return False

        # No tracked process - try to kill by PID if provided
        if pid:
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
                # Give it a moment to die
                time.sleep(0.5)
                # Check if still alive and force kill
                try:
                    os.kill(pid, 0)  # Check if process exists
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass  # Already dead
                return True
            except ProcessLookupError:
                return True  # Already dead
            except (PermissionError, OSError):
                return False

        return True

    def terminate(self, instance_id: str, pid: int | None = None) -> bool:
        """Terminate instance and remove tracking.

        Args:
            instance_id: Instance to terminate
            pid: Optional PID to kill if process not tracked in memory

        Returns:
            True if terminated successfully
        """
        result = self.stop(instance_id, pid=pid)
        self._processes.pop(instance_id, None)
        return result

    def is_running(self, instance_id: str) -> bool:
        """Check if instance process is running.

        Args:
            instance_id: Instance to check

        Returns:
            True if process is alive
        """
        proc = self._processes.get(instance_id)
        if not proc:
            return False
        return proc.poll() is None

    def get_pid(self, instance_id: str) -> int | None:
        """Get PID of running instance.

        Args:
            instance_id: Instance to check

        Returns:
            PID if running, None otherwise
        """
        proc = self._processes.get(instance_id)
        if proc and proc.poll() is None:
            return proc.pid
        return None

    def recover_process(self, instance_id: str, pid: int) -> bool:
        """Attempt to recover tracking for a process from a previous run.

        Args:
            instance_id: Instance identifier
            pid: PID from previous run

        Returns:
            True if process is still alive and now tracked
        """
        try:
            os.kill(pid, 0)  # Check if process exists
            # We can't recover the Popen object, but we can track the PID
            # For now, just report if it's alive
            return True
        except (ProcessLookupError, PermissionError):
            return False

    def get_logs(self, instance_id: str, lines: int = 100) -> ProcessLogs:
        """Get recent logs from an instance.

        Args:
            instance_id: Instance to get logs for
            lines: Maximum number of lines to return

        Returns:
            ProcessLogs with stdout/stderr content
        """
        buf = self._log_buffers.get(instance_id, [])
        # Return last N lines
        return ProcessLogs(stdout=buf[-lines:], stderr=[])

    async def wait_for_ready(
        self,
        port: int,
        timeout_seconds: float = 120.0,
        poll_interval: float = 2.0,
    ) -> bool:
        """Wait for ComfyUI to become ready by polling HTTP endpoint.

        Polls the ComfyUI HTTP endpoint until it responds successfully
        or the timeout is reached.

        Args:
            port: Port ComfyUI is listening on
            timeout_seconds: Maximum time to wait (default 2 minutes)
            poll_interval: Time between polling attempts

        Returns:
            True if ComfyUI is ready, False if timeout expired
        """
        url = f"http://localhost:{port}/"
        deadline = time.monotonic() + timeout_seconds

        async with aiohttp.ClientSession() as session:
            while time.monotonic() < deadline:
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        if resp.status == 200:
                            return True
                except Exception:
                    # Connection refused, timeout, etc - keep trying
                    pass

                await asyncio.sleep(poll_interval)

        return False
