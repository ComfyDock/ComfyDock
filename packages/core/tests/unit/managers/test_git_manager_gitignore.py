"""Tests for environment gitignore policy."""

from pathlib import Path
from tempfile import TemporaryDirectory

from comfygit_core.managers.git_manager import GitManager
from comfygit_core.utils.git import _git


class TestGitManagerGitignore:
    """Environment gitignore should keep generated local artifacts out of commits."""

    def test_standard_gitignore_excludes_generated_comfyui_metadata(self):
        with TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            manager = GitManager(repo_path)

            manager._create_gitignore()

            content = (repo_path / ".gitignore").read_text(encoding="utf-8")
            assert "comfyui_builtins.json" in content
            assert "comfyui_folder_paths.json" in content
            assert "comfyui_model_loaders.json" in content
            assert "backups/" in content

    def test_schema_migration_untracks_generated_comfyui_metadata(self, test_env):
        # Simulate an older environment created before generated metadata was ignored.
        gitignore_path = test_env.cec_path / ".gitignore"
        gitignore_path.write_text(
            gitignore_path.read_text(encoding="utf-8")
            .replace("comfyui_builtins.json\n", "")
            .replace("comfyui_folder_paths.json\n", "")
            .replace("comfyui_model_loaders.json\n", ""),
            encoding="utf-8",
        )

        for filename in (
            "comfyui_builtins.json",
            "comfyui_folder_paths.json",
            "comfyui_model_loaders.json",
        ):
            (test_env.cec_path / filename).write_text("{}", encoding="utf-8")

        test_env.git_manager.commit_all("Track generated metadata")

        assert "comfyui_builtins.json" in _git(["ls-files"], test_env.cec_path).stdout
        assert "comfyui_folder_paths.json" in _git(["ls-files"], test_env.cec_path).stdout
        assert "comfyui_model_loaders.json" in _git(["ls-files"], test_env.cec_path).stdout

        test_env._ensure_schema_migrated()

        tracked_files = _git(["ls-files"], test_env.cec_path).stdout
        assert "comfyui_builtins.json" not in tracked_files
        assert "comfyui_folder_paths.json" not in tracked_files
        assert "comfyui_model_loaders.json" not in tracked_files

        gitignore = (test_env.cec_path / ".gitignore").read_text(encoding="utf-8")
        assert "comfyui_builtins.json" in gitignore
        assert "comfyui_folder_paths.json" in gitignore
        assert "comfyui_model_loaders.json" in gitignore
        assert "backups/" in gitignore
