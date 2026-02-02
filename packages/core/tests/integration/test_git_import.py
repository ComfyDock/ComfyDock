"""Integration tests for git-based import functionality."""
import subprocess

import pytest


class TestGitImport:
    """Test importing environments from git repositories."""

    def test_import_from_local_git_repo(self, test_workspace, tmp_path, mock_comfyui_clone, mock_github_api):
        """Test importing from a local git repository."""
        # Create a mock git repo with .cec structure
        git_repo = tmp_path / "mock-repo"
        git_repo.mkdir()

        # Create pyproject.toml with ComfyUI version
        pyproject_content = """
[project]
name = "test-git-env"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []

[tool.comfygit]
comfyui_version = "main"
comfyui_version_type = "branch"
python_version = "3.12"
nodes = {}
"""
        (git_repo / "pyproject.toml").write_text(pyproject_content)

        # Create .python-version
        (git_repo / ".python-version").write_text("3.12\n")

        # Create workflows directory
        workflows = git_repo / "workflows"
        workflows.mkdir()
        (workflows / "test.json").write_text('{"nodes": []}')

        # Initialize as git repo
        subprocess.run(["git", "init"], cwd=git_repo, check=True, capture_output=True)
        subprocess.run(["git", "add", "."], cwd=git_repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=git_repo,
            check=True,
            capture_output=True,
            env={"GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@test.com",
                 "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@test.com"}
        )

        # Import from local git path (fixture mocks UV and ComfyUI operations)
        env = test_workspace.import_from_git(
            git_url=str(git_repo),
            name="test-git-import",
            model_strategy="skip"
        )

        # Verify environment was created
        assert env.name == "test-git-import"
        assert env.cec_path.exists()
        assert (env.cec_path / "pyproject.toml").exists()
        assert (env.cec_path / "workflows" / "test.json").exists()

        # Verify git repo was initialized (fresh, not from cloned repo)
        assert (env.cec_path / ".git").exists()
        # Should have initial commit from initialize_environment_repo
        result = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=env.cec_path,
            capture_output=True,
            text=True
        )
        assert "Imported environment" in result.stdout

    def test_import_from_git_without_pyproject(self, test_workspace, tmp_path, mock_comfyui_clone, mock_github_api):
        """Test that import fails gracefully if repo doesn't have pyproject.toml."""
        # Create a mock git repo WITHOUT pyproject.toml
        git_repo = tmp_path / "invalid-repo"
        git_repo.mkdir()
        (git_repo / "README.md").write_text("# Not a ComfyDock repo")

        # Initialize as git repo
        subprocess.run(["git", "init"], cwd=git_repo, check=True, capture_output=True)
        subprocess.run(["git", "add", "."], cwd=git_repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=git_repo,
            check=True,
            capture_output=True,
            env={"GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@test.com",
                 "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@test.com"}
        )

        # Should fail with clear error message (wrapped in RuntimeError by workspace)
        with pytest.raises(RuntimeError, match="does not contain pyproject.toml"):
            test_workspace.import_from_git(
                git_url=str(git_repo),
                name="test-invalid-git",
                model_strategy="skip"
            )

    def test_import_from_git_with_branch(self, test_workspace, tmp_path, mock_comfyui_clone, mock_github_api):
        """Test importing from a specific git branch."""
        # Create a mock git repo
        git_repo = tmp_path / "branch-repo"
        git_repo.mkdir()

        # Create pyproject.toml
        pyproject_content = """
[project]
name = "test-branch-env"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []

[tool.comfygit]
comfyui_version = "main"
python_version = "3.12"
nodes = {}
"""
        (git_repo / "pyproject.toml").write_text(pyproject_content)
        (git_repo / ".python-version").write_text("3.12\n")

        # Initialize git and create branch
        subprocess.run(["git", "init"], cwd=git_repo, check=True, capture_output=True)
        subprocess.run(["git", "add", "."], cwd=git_repo, check=True, capture_output=True)
        env_vars = {
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@test.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@test.com"
        }
        subprocess.run(
            ["git", "commit", "-m", "Initial"],
            cwd=git_repo,
            check=True,
            capture_output=True,
            env=env_vars
        )
        subprocess.run(["git", "branch", "feature"], cwd=git_repo, check=True, capture_output=True)

        # Import with branch specification (fixture handles mocking)
        env = test_workspace.import_from_git(
            git_url=str(git_repo),
            name="test-branch-import",
            branch="feature",
            model_strategy="skip"
        )

        assert env.name == "test-branch-import"
        assert env.cec_path.exists()
