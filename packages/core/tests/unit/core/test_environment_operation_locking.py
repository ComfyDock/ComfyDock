"""Tests for environment operation lock decorators."""

from comfygit_core.core.environment import Environment
from comfygit_core.utils.environment_lock import EnvironmentOperationLock


class _FakeLock:
    def __init__(self) -> None:
        self.entered = False
        self.exited = False

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.exited = True
        return False


class _FakeGitOrchestrator:
    def __init__(self, lock: _FakeLock) -> None:
        self.lock = lock
        self.called_with: str | None = None

    def revert_commit(self, commit: str) -> None:
        assert self.lock.entered, "Lock must be entered before orchestration call"
        self.called_with = commit


class _FakeEnvironment:
    def __init__(self) -> None:
        self._operation_lock = _FakeLock()
        self.git_orchestrator = _FakeGitOrchestrator(self._operation_lock)


def test_revert_commit_acquires_environment_lock():
    """Environment.revert_commit should execute under the operation lock."""
    env = _FakeEnvironment()

    Environment.revert_commit(env, "abc123")

    assert env._operation_lock.entered is True
    assert env._operation_lock.exited is True
    assert env.git_orchestrator.called_with == "abc123"


def test_environment_operation_lock_clears_owner_file_on_release(tmp_path):
    """Released lock files should not retain misleading stale owner PIDs."""
    lock_path = tmp_path / ".comfygit.lock"

    with EnvironmentOperationLock(lock_path):
        assert lock_path.read_text(encoding="utf-8").strip()

    assert lock_path.read_text(encoding="utf-8") == ""
