"""Shared fixtures for integration tests."""
import json
import shutil
from pathlib import Path

import pytest
from comfygit_core.core.environment import Environment

# ============================================================================
# Path Fixtures
# ============================================================================

@pytest.fixture(scope="session")
def fixtures_dir():
    """Path to test fixtures directory."""
    return Path(__file__).parent / "fixtures"

@pytest.fixture(scope="session")
def workflow_fixtures(fixtures_dir):
    """Path to workflow fixture files."""
    return fixtures_dir / "workflows"

@pytest.fixture(scope="session")
def model_fixtures(fixtures_dir):
    """Path to model fixture metadata."""
    return fixtures_dir / "models"

# ============================================================================
# Workspace & Environment Fixtures
# ============================================================================

@pytest.fixture
def test_workspace(tmp_path):
    """Create isolated workspace for each test."""
    from comfygit_core.factories.workspace_factory import WorkspaceFactory

    workspace_path = tmp_path / "comfygit_workspace"

    # Use factory to create properly initialized workspace
    workspace = WorkspaceFactory.create(workspace_path)

    # Create empty node mappings file to avoid network fetch in tests
    custom_nodes_cache = workspace.paths.cache / "custom_nodes"
    custom_nodes_cache.mkdir(parents=True, exist_ok=True)
    node_mappings = custom_nodes_cache / "node_mappings.json"
    with open(node_mappings, 'w') as f:
        json.dump({"mappings": {}, "packages": {}, "stats": {}}, f)

    # Create minimal builtins-by-version file to avoid network fetch in tests
    builtins_by_version = custom_nodes_cache / "comfyui_builtins_by_version.json"
    with open(builtins_by_version, 'w') as f:
        json.dump(
            {
                "version": "test",
                "generated_at": "1970-01-01T00:00:00Z",
                "comfyui_versions_processed": [],
                "stats": {},
                "builtins": {}
            },
            f
        )

    # Set up models directory inside workspace
    models_dir = workspace_path / "models"
    models_dir.mkdir(exist_ok=True)
    workspace.set_models_directory(models_dir)

    return workspace

@pytest.fixture
def test_env(test_workspace):
    """Create test environment with minimal setup (no actual ComfyUI clone)."""
    from comfygit_core.core.environment import Environment
    from comfygit_core.managers.git_manager import GitManager

    env_path = test_workspace.paths.environments / "test-env"
    env_path.mkdir(parents=True)

    # Create .cec directory
    cec_path = env_path / ".cec"
    cec_path.mkdir()

    # Create minimal ComfyUI structure (no actual clone)
    comfyui_path = env_path / "ComfyUI"
    comfyui_path.mkdir()
    (comfyui_path / "custom_nodes").mkdir()
    (comfyui_path / "user" / "default" / "workflows").mkdir(parents=True)

    # Create Environment instance
    env = Environment(
        name="test-env",
        path=env_path,
        workspace=test_workspace
    )

    # Create minimal pyproject.toml
    config = {
        "project": {
            "name": "comfygit-env-test-env",
            "version": "0.1.0",
            "requires-python": ">=3.12",
            "dependencies": []
        },
        "tool": {
            "comfygit": {
                "comfyui_version": "test",
                "python_version": "3.12",
                "nodes": {}
            }
        }
    }
    env.pyproject.save(config)

    # Create .pytorch-backend file for tests that need it
    (cec_path / ".pytorch-backend").write_text("cu121")

    # Initialize git repo
    git_mgr = GitManager(cec_path)
    git_mgr.initialize_environment_repo("Initial test environment")

    return env

# ============================================================================
# Model Management Fixtures
# ============================================================================

@pytest.fixture
def test_models(test_workspace, model_fixtures):
    """Create and index test model files."""

    # Use workspace's configured models directory
    models_dir = test_workspace.workspace_config_manager.get_models_directory()

    created_models = {}

    # Load model specs
    with open(model_fixtures / "test_models.json") as f:
        model_specs = json.load(f)

    # Create each model
    for spec in model_specs:
        model = _create_test_model_file(
            models_dir=models_dir,
            filename=spec["filename"],
            relative_path=spec["path"],
            size_mb=spec.get("size_mb", 4)
        )
        created_models[spec["filename"]] = model

    # Index models
    test_workspace.sync_model_directory()

    return created_models

def _create_test_model_file(models_dir: Path, filename: str, relative_path: str, size_mb: int = 4):
    """Create a stub model file with deterministic hash."""
    # Create path
    model_path = models_dir / relative_path / filename
    model_path.parent.mkdir(parents=True, exist_ok=True)

    # Write deterministic content for reproducible hash
    content = b"TEST_MODEL_" + filename.encode() + b"\x00" * (size_mb * 1024 * 1024)
    with open(model_path, 'wb') as f:
        f.write(content)

    # Simple deterministic hash based on filename
    from hashlib import sha256
    file_hash = sha256(filename.encode()).hexdigest()[:16]

    return {
        'filename': filename,
        'hash': file_hash,
        'file_size': model_path.stat().st_size,
        'relative_path': relative_path,
        'path': model_path
    }

# ============================================================================
# Workflow Simulation Helpers
# ============================================================================

def simulate_comfyui_save_workflow(env: Environment, name: str, workflow_data):
    """Simulate ComfyUI saving a workflow to disk."""
    workflows_dir = env.comfyui_path / "user" / "default" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)

    workflow_file = workflows_dir / f"{name}.json"

    # Handle both dict and Path inputs
    if isinstance(workflow_data, Path):
        shutil.copy(workflow_data, workflow_file)
    else:
        with open(workflow_file, 'w') as f:
            json.dump(workflow_data, f, indent=2)

    return workflow_file

def load_workflow_fixture(workflow_fixtures: Path, name: str) -> dict:
    """Load a workflow fixture file."""
    fixture_path = workflow_fixtures / f"{name}.json"
    with open(fixture_path) as f:
        return json.load(f)

# ============================================================================
# Test Strategy Fixtures
# ============================================================================

class TestModelStrategy:
    """Model resolution strategy for tests with predefined choices."""

    def __init__(self, choices: dict[str, int]):
        """
        Args:
            choices: Map model_ref.filename -> candidate index
        """
        self.choices = choices
        self.resolutions_attempted = []

    def resolve_ambiguous_model(self, model_ref, candidates):
        self.resolutions_attempted.append(model_ref.filename)

        if model_ref.filename in self.choices:
            idx = self.choices[model_ref.filename]
            if idx < len(candidates):
                return candidates[idx]

        return None

@pytest.fixture
def auto_model_strategy():
    """Strategy that auto-selects first match for any model."""
    class AutoFirstStrategy:
        def resolve_ambiguous_model(self, model_ref, candidates):
            return candidates[0] if candidates else None

    return AutoFirstStrategy()

# ============================================================================
# ComfyUI Mocking Fixtures
# ============================================================================

def _create_fake_comfyui_structure(comfyui_path: Path) -> None:
    """Create a minimal fake ComfyUI directory structure."""
    comfyui_path.mkdir(parents=True, exist_ok=True)

    # Create essential files
    (comfyui_path / "main.py").write_text("# Fake ComfyUI main.py")
    (comfyui_path / "nodes.py").write_text("# Fake ComfyUI nodes.py")
    (comfyui_path / "folder_paths.py").write_text("# Fake ComfyUI folder_paths.py")

    # Create essential directories
    (comfyui_path / "comfy").mkdir(exist_ok=True)
    (comfyui_path / "models").mkdir(exist_ok=True)
    (comfyui_path / "custom_nodes").mkdir(exist_ok=True)
    (comfyui_path / "user" / "default" / "workflows").mkdir(parents=True, exist_ok=True)

    # Create .git directory to simulate git repo
    git_dir = comfyui_path / ".git"
    git_dir.mkdir(exist_ok=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/master")
    (git_dir / "config").write_text("[core]\n\trepositoryformatversion = 0")

@pytest.fixture
def mock_comfyui_clone(monkeypatch):
    """Mock ComfyUI clone operations to avoid network calls.

    This fixture mocks the clone_comfyui function to create a fake
    ComfyUI structure instead of cloning from GitHub.
    """
    import subprocess
    import sys

    # Save original subprocess.run
    original_subprocess_run = subprocess.run

    def fake_clone_comfyui(target_path: Path, version: str | None = None) -> str:
        """Fake clone that creates ComfyUI structure without network."""
        _create_fake_comfyui_structure(target_path)
        return "v0.0.1-test-fake"

    monkeypatch.setattr(
        "comfygit_core.utils.comfyui_ops.clone_comfyui",
        fake_clone_comfyui
    )

    # Mock git_rev_parse to return fake SHA only for ComfyUI paths
    # Let real git operations work for test environment repos
    def fake_git_rev_parse(repo_path: Path, ref: str) -> str:
        # Only return fake SHA if this looks like ComfyUI repo path
        if "ComfyUI" in str(repo_path):
            return "abc123def456789012345678901234567890abcd"
        # Otherwise use real git
        result = subprocess.run(
            ["git", "rev-parse", ref],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return "abc123def456789012345678901234567890abcd"

    monkeypatch.setattr(
        "comfygit_core.utils.git.git_rev_parse",
        fake_git_rev_parse
    )

    def _create_venv_structure(cwd: Path) -> None:
        """Create cross-platform venv structure."""
        venv_path = cwd / ".venv"
        venv_path.mkdir(exist_ok=True)

        # Windows uses Scripts/, Unix uses bin/
        if sys.platform == "win32":
            scripts_dir = venv_path / "Scripts"
            scripts_dir.mkdir(exist_ok=True)
            (scripts_dir / "python.exe").touch()
        else:
            bin_dir = venv_path / "bin"
            bin_dir.mkdir(exist_ok=True)
            (bin_dir / "python").touch()

    def fake_subprocess_run(cmd, *args, **kwargs):
        """Mock subprocess calls for uv and git."""
        if isinstance(cmd, list) and len(cmd) > 0:
            # Get basename for matching (handles full paths like "C:\...\uv.EXE")
            command_path = Path(cmd[0])
            command = command_path.stem.lower()  # "uv.EXE" -> "uv"

            # Handle all uv commands
            if command == "uv":
                result = subprocess.CompletedProcess(
                    args=cmd,
                    returncode=0,
                    stdout="",
                    stderr=""
                )

                # uv sync or uv pip install - create venv
                if "sync" in cmd or ("pip" in cmd and "install" in cmd):
                    cwd = kwargs.get('cwd', Path.cwd())
                    if isinstance(cwd, str | Path):
                        _create_venv_structure(Path(cwd))

                # uv pip show - return fake package info
                elif "pip" in cmd and "show" in cmd:
                    result.stdout = "Name: torch\nVersion: 2.5.1+cu128\n"

                # uv pip list - return empty list
                elif "pip" in cmd and "list" in cmd:
                    result.stdout = ""

                # uv pip freeze - return empty
                elif "pip" in cmd and "freeze" in cmd:
                    result.stdout = ""

                # uv add - no-op
                elif "add" in cmd:
                    pass

                return result

            # Handle git commands - let all git commands run real
            # (git_rev_parse Python function is mocked separately above)
            elif command == "git":
                return original_subprocess_run(cmd, *args, **kwargs)

            # Handle Windows mklink (for model symlinks)
            elif command == "mklink":
                # Create a fake junction/symlink
                if len(cmd) >= 4 and cmd[1] == "/J":
                    link_path = Path(cmd[2])
                    target_path = Path(cmd[3])
                    # Create actual junction for tests to work
                    link_path.symlink_to(target_path, target_is_directory=True)
                return subprocess.CompletedProcess(
                    args=cmd,
                    returncode=0,
                    stdout="Junction created",
                    stderr=""
                )

        # For unmocked commands, use original subprocess.run
        # This allows tests to run real git commands for test setup
        return original_subprocess_run(cmd, *args, **kwargs)

    monkeypatch.setattr("subprocess.run", fake_subprocess_run)

    # Mock ComfyUI cache to avoid caching operations
    class FakeComfyUICacheManager:
        def __init__(self, *args, **kwargs):
            pass

        def get_cached_comfyui(self, spec):
            """Always return None (no cache hit)."""
            return None

        def cache_comfyui(self, spec, source_path):
            """No-op cache operation."""
            pass

    monkeypatch.setattr(
        "comfygit_core.caching.comfyui_cache.ComfyUICacheManager",
        FakeComfyUICacheManager
    )

    return fake_clone_comfyui

def _fake_probe_pytorch_versions(python_version, backend):
    """Fake probe that returns mock versions without network."""
    # Resolve "auto" to a reasonable default
    resolved_backend = "cu128" if backend == "auto" else backend

    # Return fake versions with the resolved backend suffix
    if resolved_backend == "cpu":
        versions = {
            "torch": "2.5.1",
            "torchvision": "0.20.1",
            "torchaudio": "2.5.1",
        }
    else:
        versions = {
            "torch": f"2.5.1+{resolved_backend}",
            "torchvision": f"0.20.1+{resolved_backend}",
            "torchaudio": f"2.5.1+{resolved_backend}",
        }

    return versions, resolved_backend


@pytest.fixture
def mock_pytorch_probe(monkeypatch):
    """Mock PyTorch probing to avoid network calls and actual venv creation.

    This fixture mocks probe_pytorch_versions to return fake versions
    instead of actually probing with uv dry-run.
    """
    monkeypatch.setattr(
        "comfygit_core.utils.pytorch_prober.probe_pytorch_versions",
        _fake_probe_pytorch_versions
    )

    return _fake_probe_pytorch_versions


@pytest.fixture(autouse=True)
def auto_mock_pytorch_probe_for_integration(request, monkeypatch):
    """Auto-mock PyTorch probing for integration tests.

    This fixture automatically mocks probe_pytorch_versions for any test
    in the integration/ directory to avoid real UV dry-run probes.
    """
    # Only apply to integration tests (check for tests/integration/ directory, not just "integration" anywhere)
    if "/tests/integration/" in str(request.fspath) or "\\tests\\integration\\" in str(request.fspath):
        monkeypatch.setattr(
            "comfygit_core.utils.pytorch_prober.probe_pytorch_versions",
            _fake_probe_pytorch_versions
        )


@pytest.fixture
def mock_github_api(monkeypatch):
    """Mock GitHub API calls to avoid network requests."""

    class FakeRepositoryInfo:
        def __init__(self):
            self.latest_release = "v0.3.20"
            self.default_branch = "main"

    class FakeRelease:
        def __init__(self, tag_name: str):
            self.tag_name = tag_name
            self.name = f"Release {tag_name}"

    class FakeGitHubClient:
        def get_repository_info(self, repo_url: str):
            return FakeRepositoryInfo()

        def validate_version_exists(self, repo_url: str, version: str) -> bool:
            # Accept common test versions
            return version.startswith('v') or version in ('master', 'test')

        def list_releases(self, repo_url: str, limit: int = 10):
            return [FakeRelease("v0.3.20"), FakeRelease("v0.3.19")]

    # Patch GitHubClient instantiation in resolve_comfyui_version
    try:
        from comfygit_core.clients.github_client import GitHubClient

        def patched_init(self, *args, **kwargs):
            # Copy attributes from FakeGitHubClient
            fake = FakeGitHubClient()
            for attr in dir(fake):
                if not attr.startswith('_'):
                    setattr(self, attr, getattr(fake, attr))

        monkeypatch.setattr(GitHubClient, "__init__", patched_init)
    except ImportError:
        pass

    return FakeGitHubClient()

# ============================================================================
# Enhanced Fixtures for Pipeline Tests
# ============================================================================

@pytest.fixture
def model_index_builder(test_workspace):
    """Create ModelIndexBuilder for fluent model setup."""
    from helpers.model_index_builder import ModelIndexBuilder
    return ModelIndexBuilder(test_workspace)

@pytest.fixture
def pyproject_assertions(test_env):
    """Create PyprojectAssertions for fluent validation."""
    from helpers.pyproject_assertions import PyprojectAssertions
    return PyprojectAssertions(test_env)
