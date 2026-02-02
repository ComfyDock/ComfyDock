"""Tests for UserContentSymlinkManager."""

import pytest
from comfygit_core.managers.user_content_symlink_manager import UserContentSymlinkManager
from comfygit_core.models.exceptions import CDEnvironmentError
from comfygit_core.utils.symlink_utils import is_link


@pytest.fixture
def workspace_base(tmp_path):
    """Create workspace base directories."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture
def manager(workspace_base, tmp_path):
    """Create UserContentSymlinkManager instance."""
    comfyui_path = tmp_path / "env1" / "ComfyUI"
    comfyui_path.mkdir(parents=True)

    input_base = workspace_base / "input"
    output_base = workspace_base / "output"

    return UserContentSymlinkManager(
        comfyui_path=comfyui_path,
        env_name="env1",
        workspace_input_base=input_base,
        workspace_output_base=output_base,
    )


class TestCreateDirectories:
    """Test workspace directory creation."""

    def test_creates_both_directories(self, manager):
        """Test that create_directories creates input and output subdirectories."""
        manager.create_directories()

        assert manager.input_target.exists()
        assert manager.output_target.exists()
        assert manager.input_target.is_dir()
        assert manager.output_target.is_dir()

    def test_is_idempotent(self, manager):
        """Test that calling create_directories multiple times is safe."""
        manager.create_directories()
        manager.create_directories()  # Should not error

        assert manager.input_target.exists()
        assert manager.output_target.exists()


class TestCreateSymlinks:
    """Test symlink creation."""

    def test_creates_both_symlinks(self, manager):
        """Test that create_symlinks creates input and output links."""
        manager.create_directories()
        manager.create_symlinks()

        assert manager.input_link.exists()
        assert manager.output_link.exists()
        assert is_link(manager.input_link)
        assert is_link(manager.output_link)
        assert manager.input_link.resolve() == manager.input_target.resolve()
        assert manager.output_link.resolve() == manager.output_target.resolve()

    def test_is_idempotent(self, manager):
        """Test that calling create_symlinks multiple times is safe."""
        manager.create_directories()
        manager.create_symlinks()
        manager.create_symlinks()  # Should not error

        assert is_link(manager.input_link)
        assert is_link(manager.output_link)

    def test_errors_if_workspace_directories_missing(self, manager):
        """Test that create_symlinks errors if workspace dirs don't exist."""
        with pytest.raises(CDEnvironmentError, match="does not exist"):
            manager.create_symlinks()

    def test_removes_empty_comfyui_directories(self, manager):
        """Test that empty ComfyUI input/output dirs are removed."""
        # Create empty directories
        manager.input_link.mkdir(parents=True)
        manager.output_link.mkdir()

        manager.create_directories()
        manager.create_symlinks()

        # Should be symlinks now
        assert is_link(manager.input_link)
        assert is_link(manager.output_link)

    def test_removes_directories_with_only_placeholders(self, manager):
        """Test that directories with only safe files are removed."""
        # Create directories with placeholder files
        manager.input_link.mkdir(parents=True)
        (manager.input_link / ".gitkeep").touch()

        manager.output_link.mkdir()
        (manager.output_link / "Put files here.txt").touch()

        manager.create_directories()
        manager.create_symlinks()

        # Should be symlinks now
        assert is_link(manager.input_link)
        assert is_link(manager.output_link)

    def test_errors_if_directories_have_content(self, manager):
        """Test that directories with actual content raise error."""
        # Create directory with actual content
        manager.input_link.mkdir(parents=True)
        (manager.input_link / "important_file.jpg").write_text("data")

        manager.create_directories()

        with pytest.raises(CDEnvironmentError, match="exists with content"):
            manager.create_symlinks()

    def test_updates_wrong_target(self, manager):
        """Test that symlink with wrong target is recreated."""
        # Create workspace directories
        manager.create_directories()

        # Create symlink to wrong target
        wrong_target = manager.input_target.parent / "wrong"
        wrong_target.mkdir()
        manager.input_link.symlink_to(wrong_target)

        # Should recreate with correct target
        manager.create_symlinks()

        assert is_link(manager.input_link)
        assert manager.input_link.resolve() == manager.input_target.resolve()


class TestMigrateExistingData:
    """Test migration of existing content to workspace."""

    def test_migrates_input_and_output_files(self, manager):
        """Test that existing files are moved to workspace."""
        # Create real directories with content
        manager.input_link.mkdir(parents=True)
        (manager.input_link / "input_file.jpg").write_text("input_data")
        (manager.input_link / "subfolder").mkdir()
        (manager.input_link / "subfolder" / "nested.jpg").write_text("nested")

        manager.output_link.mkdir()
        (manager.output_link / "output_file.png").write_text("output_data")

        # Migrate
        stats = manager.migrate_existing_data()

        # Check stats
        assert stats["input_files_moved"] == 2  # input_file.jpg and subfolder
        assert stats["output_files_moved"] == 1  # output_file.png

        # Check files moved
        assert (manager.input_target / "input_file.jpg").exists()
        assert (manager.input_target / "subfolder" / "nested.jpg").exists()
        assert (manager.output_target / "output_file.png").exists()

        # Check symlinks created
        assert is_link(manager.input_link)
        assert is_link(manager.output_link)

    def test_skips_empty_directories(self, manager):
        """Test that empty directories are just removed."""
        manager.input_link.mkdir(parents=True)
        manager.output_link.mkdir()

        stats = manager.migrate_existing_data()

        assert stats["input_files_moved"] == 0
        assert stats["output_files_moved"] == 0

    def test_skips_placeholder_files(self, manager):
        """Test that directories with only placeholder files are not migrated."""
        manager.input_link.mkdir(parents=True)
        (manager.input_link / ".gitkeep").touch()

        stats = manager.migrate_existing_data()

        assert stats["input_files_moved"] == 0

    def test_handles_existing_symlinks(self, manager):
        """Test that existing symlinks are not migrated."""
        manager.create_directories()
        manager.input_link.symlink_to(manager.input_target)

        stats = manager.migrate_existing_data()

        # Should not count as migration
        assert stats["input_files_moved"] == 0

    def test_skips_conflicting_filenames(self, manager):
        """Test that files with same name in target are skipped."""
        # Create workspace directories with existing file
        manager.create_directories()
        (manager.input_target / "existing.jpg").write_text("workspace_version")

        # Create source directory with conflicting file
        manager.input_link.mkdir(parents=True)
        (manager.input_link / "existing.jpg").write_text("env_version")
        (manager.input_link / "new.jpg").write_text("new")

        manager.migrate_existing_data()

        # Only new.jpg moved (existing.jpg skipped)
        assert (manager.input_target / "existing.jpg").read_text() == "workspace_version"
        assert (manager.input_target / "new.jpg").exists()


class TestValidateSymlinks:
    """Test symlink validation."""

    def test_validates_correct_symlinks(self, manager):
        """Test that valid symlinks pass validation."""
        manager.create_directories()
        manager.create_symlinks()

        result = manager.validate_symlinks()

        assert result["input"] is True
        assert result["output"] is True

    def test_detects_missing_symlinks(self, manager):
        """Test that missing symlinks fail validation."""
        result = manager.validate_symlinks()

        assert result["input"] is False
        assert result["output"] is False

    def test_detects_wrong_target(self, manager):
        """Test that symlinks with wrong target fail validation."""
        manager.create_directories()

        # Create symlink to wrong target
        wrong_target = manager.input_target.parent / "wrong"
        wrong_target.mkdir()
        manager.input_link.symlink_to(wrong_target)

        result = manager.validate_symlinks()

        assert result["input"] is False


class TestRemoveSymlinks:
    """Test symlink removal."""

    def test_removes_both_symlinks(self, manager):
        """Test that remove_symlinks removes input and output links."""
        manager.create_directories()
        manager.create_symlinks()

        manager.remove_symlinks()

        assert not manager.input_link.exists()
        assert not manager.output_link.exists()
        # Workspace data should still exist
        assert manager.input_target.exists()
        assert manager.output_target.exists()

    def test_handles_missing_symlinks(self, manager):
        """Test that removing nonexistent symlinks doesn't error."""
        manager.remove_symlinks()  # Should not error

    def test_errors_on_real_directories(self, manager):
        """Test that removing real directories raises error."""
        manager.input_link.mkdir(parents=True)

        with pytest.raises(CDEnvironmentError, match="not a link"):
            manager.remove_symlinks()


class TestGetUserDataSize:
    """Test user data size calculation."""

    def test_returns_zero_for_empty_directories(self, manager):
        """Test that empty directories return zero size."""
        manager.create_directories()

        sizes = manager.get_user_data_size()

        assert sizes["input"] == (0, 0)
        assert sizes["output"] == (0, 0)

    def test_counts_files_and_bytes(self, manager):
        """Test that files are counted correctly."""
        manager.create_directories()

        # Add files
        (manager.input_target / "file1.jpg").write_bytes(b"x" * 100)
        (manager.input_target / "file2.jpg").write_bytes(b"x" * 200)

        (manager.output_target / "output.png").write_bytes(b"x" * 300)

        sizes = manager.get_user_data_size()

        assert sizes["input"] == (2, 300)
        assert sizes["output"] == (1, 300)

    def test_includes_nested_files(self, manager):
        """Test that nested files are counted."""
        manager.create_directories()

        # Add nested files
        nested_dir = manager.input_target / "subfolder"
        nested_dir.mkdir()
        (nested_dir / "nested.jpg").write_bytes(b"x" * 50)

        sizes = manager.get_user_data_size()

        assert sizes["input"] == (1, 50)


class TestDeleteUserData:
    """Test user data deletion."""

    def test_deletes_both_directories(self, manager):
        """Test that delete_user_data removes input and output directories."""
        manager.create_directories()

        # Add files
        (manager.input_target / "file.jpg").write_text("data")
        (manager.output_target / "output.png").write_text("data")

        stats = manager.delete_user_data()

        assert stats["input_files_deleted"] == 1
        assert stats["output_files_deleted"] == 1
        assert not manager.input_target.exists()
        assert not manager.output_target.exists()

    def test_handles_missing_directories(self, manager):
        """Test that deleting nonexistent directories doesn't error."""
        stats = manager.delete_user_data()

        assert stats["input_files_deleted"] == 0
        assert stats["output_files_deleted"] == 0

    def test_counts_nested_files(self, manager):
        """Test that nested files are counted in deletion."""
        manager.create_directories()

        # Add nested files
        nested_dir = manager.input_target / "subfolder"
        nested_dir.mkdir()
        (nested_dir / "nested.jpg").write_text("data")
        (manager.input_target / "root.jpg").write_text("data")

        stats = manager.delete_user_data()

        assert stats["input_files_deleted"] == 2


class TestGetStatus:
    """Test status reporting."""

    def test_shows_correct_status_for_valid_symlinks(self, manager):
        """Test that get_status returns correct info for valid symlinks."""
        manager.create_directories()
        manager.create_symlinks()

        status = manager.get_status()

        assert status["input"]["exists"] is True
        assert status["input"]["is_symlink"] is True
        assert status["input"]["is_valid"] is True

        assert status["output"]["exists"] is True
        assert status["output"]["is_symlink"] is True
        assert status["output"]["is_valid"] is True

    def test_shows_correct_status_for_missing_symlinks(self, manager):
        """Test that get_status returns correct info for missing symlinks."""
        status = manager.get_status()

        assert status["input"]["exists"] is False
        assert status["input"]["is_symlink"] is False
        assert status["input"]["is_valid"] is False

    def test_shows_correct_status_for_wrong_target(self, manager):
        """Test that get_status detects wrong target."""
        manager.create_directories()

        # Create symlink to wrong target
        wrong_target = manager.input_target.parent / "wrong"
        wrong_target.mkdir()
        manager.input_link.symlink_to(wrong_target)

        status = manager.get_status()

        assert status["input"]["exists"] is True
        assert status["input"]["is_symlink"] is True
        assert status["input"]["is_valid"] is False
