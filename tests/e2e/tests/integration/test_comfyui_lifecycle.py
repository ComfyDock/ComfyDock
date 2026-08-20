"""
E2E Tests: ComfyUI Lifecycle
============================
Spec: specs/environment-lifecycle.yaml#comfyui-lifecycle

Tests starting and stopping ComfyUI. This is the critical path - if users
can't run ComfyUI, nothing else matters.

NOTE: These tests are slower and require more resources than smoke tests.
They should be run separately or with appropriate markers.
"""
import os
import signal
import socket
import subprocess
import time
from contextlib import contextmanager

import pytest
import requests

# Use a port that won't conflict with dev (8188-8190) or other tests
COMFYUI_TEST_PORT = 18188
STARTUP_TIMEOUT = 120  # seconds - first run can be slow


def is_port_in_use(port: int) -> bool:
    """Check if a port is already in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) == 0


def wait_for_health(port: int, timeout: int = STARTUP_TIMEOUT) -> bool:
    """Wait for ComfyUI to respond to health check."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            resp = requests.get(f"http://localhost:{port}/system_stats", timeout=2)
            if resp.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(1)
    return False


@contextmanager
def comfyui_process(cg_cmd: list[str], env: dict):
    """Context manager to start ComfyUI and ensure cleanup."""
    proc = subprocess.Popen(
        cg_cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        # Use process group for clean shutdown
        start_new_session=True,
    )
    try:
        yield proc
    finally:
        # Clean shutdown
        if proc.poll() is None:
            # Send SIGTERM to process group
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
            # Wait for graceful shutdown
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                # Force kill if needed
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                proc.wait(timeout=5)


class TestComfyUILifecycle:
    """
    Spec: comfyui-lifecycle

    Tests starting and stopping ComfyUI. This is the critical path.
    """

    @pytest.mark.slow
    def test_run_comfyui_cpu(self, workspace, shared_uv_cache):
        """
        Spec: comfyui-lifecycle.run-comfyui-cpu

        WHY: Running ComfyUI is the entire point of comfygit. This verifies:
        1. Python venv activation works
        2. ComfyUI dependencies are installed
        3. --torch-backend cpu override works
        4. Arguments pass through to ComfyUI (--port)
        5. Server actually starts and responds to HTTP

        Port 18188 avoids conflicts with dev ports (8188-8190).
        """
        # Skip if port already in use
        if is_port_in_use(COMFYUI_TEST_PORT):
            pytest.skip(f"Port {COMFYUI_TEST_PORT} already in use")

        # Build command
        cmd = [
            "cg", "-e", "default", "run",
            "--torch-backend", "cpu",
            "--no-sync",  # Skip sync for faster startup
            "--port", str(COMFYUI_TEST_PORT),
        ]

        # Set up environment
        env = os.environ.copy()
        env["COMFYGIT_HOME"] = str(workspace)
        env["UV_CACHE_DIR"] = str(shared_uv_cache)

        with comfyui_process(cmd, env) as proc:
            # Wait for health check
            is_healthy = wait_for_health(COMFYUI_TEST_PORT, timeout=STARTUP_TIMEOUT)

            if not is_healthy:
                # Capture output for debugging
                stdout, stderr = "", ""
                try:
                    stdout, stderr = proc.communicate(timeout=1)
                except subprocess.TimeoutExpired:
                    pass
                pytest.fail(
                    f"ComfyUI failed to start within {STARTUP_TIMEOUT}s\n"
                    f"stdout: {stdout}\n"
                    f"stderr: {stderr}"
                )

            # Verify it's actually running
            assert proc.poll() is None, "ComfyUI process exited unexpectedly"

            # Additional health check - get system stats
            try:
                resp = requests.get(
                    f"http://localhost:{COMFYUI_TEST_PORT}/system_stats",
                    timeout=5
                )
                assert resp.status_code == 200
                stats = resp.json()
                # Should have system info
                assert "system" in stats
            except requests.RequestException as e:
                pytest.fail(f"Health check request failed: {e}")
