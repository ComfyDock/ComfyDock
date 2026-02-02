"""Integration tests for git subdirectory import functionality."""
import subprocess

import pytest


class TestGitSubdirectoryImport:
    """Test importing environments from subdirectories in git repositories."""

    def test_import_from_subdirectory(self, test_workspace, tmp_path, mock_comfyui_clone, mock_github_api):
        """Test importing from a subdirectory using # syntax."""
        # Create a mock git repo with subdirectory structure
        git_repo = tmp_path / "test-repo"
        git_repo.mkdir()

        # Create subdirectory structure
        examples = git_repo / "examples"
        examples.mkdir()
        example1 = examples / "example1"
        example1.mkdir()

        # Create pyproject.toml in subdirectory
        pyproject = example1 / "pyproject.toml"
        pyproject.write_text("""
[project]
name = "test-subdir-env"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []

[tool.comfygit]
comfyui_version = "v0.2.7"
comfyui_version_type = "release"
python_version = "3.12"
nodes = {}
""")

        # Create .python-version
        (example1 / ".python-version").write_text("3.12\n")

        # Create workflows directory
        workflows = example1 / "workflows"
        workflows.mkdir()
        (workflows / "test.json").write_text('{"nodes": []}')

        # Initialize as git repo
        env_vars = {
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@test.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@test.com"
        }
        subprocess.run(["git", "init"], cwd=git_repo, check=True, capture_output=True)
        subprocess.run(["git", "add", "."], cwd=git_repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=git_repo,
            check=True,
            capture_output=True,
            env=env_vars
        )

        # Import with subdirectory syntax (fixture handles mocking)
        git_url = f"{git_repo}#examples/example1"
        env = test_workspace.import_from_git(
            git_url=git_url,
            name="test-subdir-env",
            model_strategy="skip"
        )

        # Verify environment was created with subdirectory contents
        assert env.path.exists()
        assert (env.cec_path / "pyproject.toml").exists()
        assert (env.cec_path / "workflows" / "test.json").exists()

        # Verify root-level files were NOT copied
        assert not (env.cec_path / "examples").exists()

    def test_import_subdirectory_not_found(self, test_workspace, tmp_path):
        """Test error when subdirectory doesn't exist."""
        git_repo = tmp_path / "test-repo"
        git_repo.mkdir()

        # Create minimal repo WITHOUT the subdirectory
        (git_repo / "README.md").write_text("# Test")

        env_vars = {
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@test.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@test.com"
        }
        subprocess.run(["git", "init"], cwd=git_repo, check=True, capture_output=True)
        subprocess.run(["git", "add", "."], cwd=git_repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial"],
            cwd=git_repo,
            check=True,
            capture_output=True,
            env=env_vars
        )

        # Should fail with helpful error
        git_url = f"{git_repo}#nonexistent/path"
        with pytest.raises(RuntimeError, match="Subdirectory 'nonexistent/path' does not exist"):
            test_workspace.import_from_git(
                git_url=git_url,
                name="test-fail",
                model_strategy="skip"
            )

    def test_import_subdirectory_missing_pyproject(self, test_workspace, tmp_path):
        """Test error when subdirectory lacks pyproject.toml."""
        git_repo = tmp_path / "test-repo"
        git_repo.mkdir()

        # Create subdirectory WITHOUT pyproject.toml
        examples = git_repo / "examples"
        examples.mkdir()
        example2 = examples / "example2"
        example2.mkdir()
        (example2 / "README.md").write_text("No pyproject here")

        env_vars = {
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@test.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@test.com"
        }
        subprocess.run(["git", "init"], cwd=git_repo, check=True, capture_output=True)
        subprocess.run(["git", "add", "."], cwd=git_repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial"],
            cwd=git_repo,
            check=True,
            capture_output=True,
            env=env_vars
        )

        # Should fail with validation error
        git_url = f"{git_repo}#examples/example2"
        with pytest.raises(RuntimeError, match="does not contain pyproject.toml"):
            test_workspace.import_from_git(
                git_url=git_url,
                name="test-fail",
                model_strategy="skip"
            )
