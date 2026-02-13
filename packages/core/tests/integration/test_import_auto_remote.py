"""Test remote validation on import."""
import subprocess


class TestImportAutoRemote:
    """Test that import properly validates and configures git remotes."""

    def test_import_from_git_verifies_origin_remote(self, test_workspace, tmp_path, mock_comfyui_clone, mock_github_api):
        """Import from git should verify origin remote is configured."""
        # Create remote repo
        remote_repo = tmp_path / "remote-repo"
        remote_repo.mkdir()
        subprocess.run(["git", "init"], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=remote_repo, check=True, capture_output=True)

        # Create ComfyGit environment structure
        pyproject_content = """
[project]
name = "test-env"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []

[tool.comfygit]
comfyui_version = "main"
python_version = "3.12"
nodes = {}
"""
        (remote_repo / "pyproject.toml").write_text(pyproject_content)
        (remote_repo / ".python-version").write_text("3.12\n")
        workflows_dir = remote_repo / "workflows"
        workflows_dir.mkdir()
        (workflows_dir / "test.json").write_text('{"nodes": []}')

        subprocess.run(["git", "add", "."], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=remote_repo, check=True, capture_output=True)

        # Import from git URL (fixture handles mocking)
        env = test_workspace.import_from_git(
            git_url=str(remote_repo),
            name="test-auto-remote",
            model_strategy="skip"
        )

        # Verify origin remote is configured (git clone does this automatically)
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=env.cec_path,
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert str(remote_repo) in result.stdout

        # Also verify via GitManager
        assert env.git_manager.has_remote("origin")

    def test_import_from_git_preserves_clone_url(self, test_workspace, tmp_path, mock_comfyui_clone, mock_github_api):
        """Import should preserve original clone URL as origin."""
        # Create remote repo
        remote_repo = tmp_path / "remote-repo"
        remote_repo.mkdir()
        subprocess.run(["git", "init"], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=remote_repo, check=True, capture_output=True)

        pyproject_content = """
[project]
name = "test-env"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []

[tool.comfygit]
comfyui_version = "main"
python_version = "3.12"
nodes = {}
"""
        (remote_repo / "pyproject.toml").write_text(pyproject_content)
        subprocess.run(["git", "add", "."], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=remote_repo, check=True, capture_output=True)

        # Import with specific URL (fixture handles mocking)
        original_url = str(remote_repo)
        env = test_workspace.import_from_git(
            git_url=original_url,
            name="test-preserve-url",
            model_strategy="skip"
        )

        # Verify origin URL matches exactly what we imported
        from comfygit_core.utils.git import git_remote_get_url
        remote_url = git_remote_get_url(env.cec_path, "origin")

        assert remote_url == original_url

    def test_import_subdirectory_warns_no_remote(self, test_workspace, tmp_path, caplog, mock_comfyui_clone, mock_github_api):
        """Import from subdirectory should warn about missing remote."""
        # Create repo with subdirectory structure
        remote_repo = tmp_path / "remote-repo"
        remote_repo.mkdir()
        subprocess.run(["git", "init"], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=remote_repo, check=True, capture_output=True)

        # Create subdirectory with ComfyGit environment
        subdir = remote_repo / "environments" / "prod"
        subdir.mkdir(parents=True)

        pyproject_content = """
[project]
name = "test-env"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []

[tool.comfygit]
comfyui_version = "main"
python_version = "3.12"
nodes = {}
"""
        (subdir / "pyproject.toml").write_text(pyproject_content)
        (subdir / ".python-version").write_text("3.12\n")
        workflows_dir = subdir / "workflows"
        workflows_dir.mkdir()
        (workflows_dir / "test.json").write_text('{"nodes": []}')

        subprocess.run(["git", "add", "."], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=remote_repo, check=True, capture_output=True)

        # Import from subdirectory using # syntax (fixture handles mocking)
        git_url_with_subdir = f"{str(remote_repo)}#environments/prod"

        import logging
        with caplog.at_level(logging.WARNING):
            env = test_workspace.import_from_git(
                git_url=git_url_with_subdir,
                name="test-subdir-no-remote",
                model_strategy="skip"
            )

        # Subdirectory imports lose git history, so no remote should be configured
        # and a warning should be logged
        assert not env.git_manager.has_remote("origin")

        # Check for warning in logs
        warning_found = any(
            "no remote configured" in record.message.lower() or
            "subdirectory import" in record.message.lower()
            for record in caplog.records
        )
        assert warning_found, "Expected warning about missing remote for subdirectory import"

    def test_import_regular_clone_can_push(self, test_workspace, tmp_path, mock_comfyui_clone, mock_github_api):
        """After regular (non-subdirectory) import, should be able to push."""
        # Create bare remote for pushing
        bare_repo = tmp_path / "bare-repo"
        bare_repo.mkdir()
        subprocess.run(["git", "init", "--bare", "-b", "main"], cwd=bare_repo, check=True, capture_output=True)

        # Create regular repo to populate bare repo
        remote_repo = tmp_path / "remote-repo"
        remote_repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=remote_repo, check=True, capture_output=True)

        pyproject_content = """
[project]
name = "test-env"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []

[tool.comfygit]
comfyui_version = "main"
python_version = "3.12"
nodes = {}
"""
        (remote_repo / "pyproject.toml").write_text(pyproject_content)
        subprocess.run(["git", "add", "."], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "remote", "add", "origin", str(bare_repo)], cwd=remote_repo, check=True, capture_output=True)
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=remote_repo, check=True, capture_output=True)

        # Import from bare repo (simulates cloning from GitHub, fixture handles mocking)
        env = test_workspace.import_from_git(
            git_url=str(bare_repo),
            name="test-can-push",
            model_strategy="skip"
        )

        # Make and commit a change
        workflows_dir = env.cec_path / "workflows"
        workflows_dir.mkdir(exist_ok=True)
        (workflows_dir / "new.json").write_text('{"new": true}')
        env.git_manager.commit_with_identity("Add workflow")

        # Should be able to push because origin is configured
        result = env.push_commits(remote="origin")
        assert result is not None

        # Verify push succeeded
        verify_repo = tmp_path / "verify"
        subprocess.run(["git", "clone", str(bare_repo), str(verify_repo)], check=True, capture_output=True)
        assert (verify_repo / "workflows" / "new.json").exists()
