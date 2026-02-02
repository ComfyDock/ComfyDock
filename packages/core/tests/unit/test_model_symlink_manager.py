"""Unit tests for ModelSymlinkManager."""
import pytest
from comfygit_core.managers.model_symlink_manager import ModelSymlinkManager, is_link
from comfygit_core.models.exceptions import CDEnvironmentError


class TestModelSymlinkManager:
    """Test ModelSymlinkManager symlink creation and management."""

    def test_create_symlink_fresh_directory(self, tmp_path):
        """Test creating symlink when models/ doesn't exist yet."""
        comfyui_path = tmp_path / "ComfyUI"
        comfyui_path.mkdir()
        global_models = tmp_path / "global_models"
        global_models.mkdir()

        manager = ModelSymlinkManager(comfyui_path, global_models)
        manager.create_symlink()

        models_link = comfyui_path / "models"
        assert models_link.exists(), "Link should be created"
        assert is_link(models_link), "Should be a link (symlink or junction)"
        assert models_link.resolve() == global_models.resolve(), "Should point to global models"

    def test_create_symlink_already_exists_correct_target(self, tmp_path):
        """Test idempotent behavior when symlink already points to correct target."""
        comfyui_path = tmp_path / "ComfyUI"
        comfyui_path.mkdir()
        global_models = tmp_path / "global_models"
        global_models.mkdir()

        # Create symlink manually first
        models_link = comfyui_path / "models"
        models_link.symlink_to(global_models)

        manager = ModelSymlinkManager(comfyui_path, global_models)
        manager.create_symlink()  # Should not error

        assert is_link(models_link)
        assert models_link.resolve() == global_models.resolve()

    def test_create_symlink_wrong_target(self, tmp_path):
        """Test recreating symlink when it points to wrong directory."""
        comfyui_path = tmp_path / "ComfyUI"
        comfyui_path.mkdir()
        global_models = tmp_path / "global_models"
        global_models.mkdir()
        wrong_target = tmp_path / "wrong_models"
        wrong_target.mkdir()

        # Create symlink to wrong target
        models_link = comfyui_path / "models"
        models_link.symlink_to(wrong_target)

        manager = ModelSymlinkManager(comfyui_path, global_models)
        manager.create_symlink()

        # Should recreate to point to correct target
        assert is_link(models_link)
        assert models_link.resolve() == global_models.resolve()

    def test_create_symlink_with_empty_comfyui_default_dirs(self, tmp_path):
        """Test handling ComfyUI's default empty models/ directory structure."""
        comfyui_path = tmp_path / "ComfyUI"
        comfyui_path.mkdir()
        global_models = tmp_path / "global_models"
        global_models.mkdir()

        # Create default ComfyUI structure (empty subdirs)
        models_dir = comfyui_path / "models"
        models_dir.mkdir()
        (models_dir / "checkpoints").mkdir()
        (models_dir / "loras").mkdir()
        (models_dir / "vae").mkdir()

        manager = ModelSymlinkManager(comfyui_path, global_models)
        manager.create_symlink()

        # Should delete empty structure and create link
        assert is_link(models_dir), "Should be link after replacing empty dirs"
        assert models_dir.resolve() == global_models.resolve()

    def test_create_symlink_with_placeholder_files(self, tmp_path):
        """Test handling .gitkeep and similar placeholder files."""
        comfyui_path = tmp_path / "ComfyUI"
        comfyui_path.mkdir()
        global_models = tmp_path / "global_models"
        global_models.mkdir()

        # Create models/ with only placeholder files
        models_dir = comfyui_path / "models"
        models_dir.mkdir()
        (models_dir / "checkpoints").mkdir()
        (models_dir / "checkpoints" / ".gitkeep").touch()
        (models_dir / ".gitignore").write_text("*")

        manager = ModelSymlinkManager(comfyui_path, global_models)
        manager.create_symlink()

        # Should be safe to delete and replace with link
        assert is_link(models_dir)
        assert models_dir.resolve() == global_models.resolve()

    def test_create_symlink_with_actual_model_files_errors(self, tmp_path):
        """Test error when models/ contains actual model files."""
        comfyui_path = tmp_path / "ComfyUI"
        comfyui_path.mkdir()
        global_models = tmp_path / "global_models"
        global_models.mkdir()

        # Create models/ with actual model file
        models_dir = comfyui_path / "models"
        models_dir.mkdir()
        (models_dir / "checkpoints").mkdir()
        (models_dir / "checkpoints" / "model.safetensors").write_text("fake model data")

        manager = ModelSymlinkManager(comfyui_path, global_models)

        with pytest.raises(CDEnvironmentError) as exc_info:
            manager.create_symlink()

        assert "models/ directory exists with content" in str(exc_info.value)
        assert models_dir.exists() and not is_link(models_dir), "Should not delete user data"

    def test_create_symlink_global_models_missing_errors(self, tmp_path):
        """Test error when global models directory doesn't exist."""
        comfyui_path = tmp_path / "ComfyUI"
        comfyui_path.mkdir()
        global_models = tmp_path / "nonexistent_models"

        manager = ModelSymlinkManager(comfyui_path, global_models)

        with pytest.raises(CDEnvironmentError) as exc_info:
            manager.create_symlink()

        assert "Global models directory does not exist" in str(exc_info.value)

    def test_validate_symlink_returns_true_when_valid(self, tmp_path):
        """Test validate_symlink returns True for correct symlink."""
        comfyui_path = tmp_path / "ComfyUI"
        comfyui_path.mkdir()
        global_models = tmp_path / "global_models"
        global_models.mkdir()

        models_link = comfyui_path / "models"
        models_link.symlink_to(global_models)

        manager = ModelSymlinkManager(comfyui_path, global_models)
        assert manager.validate_symlink() is True

    def test_validate_symlink_returns_false_when_missing(self, tmp_path):
        """Test validate_symlink returns False when symlink doesn't exist."""
        comfyui_path = tmp_path / "ComfyUI"
        comfyui_path.mkdir()
        global_models = tmp_path / "global_models"
        global_models.mkdir()

        manager = ModelSymlinkManager(comfyui_path, global_models)
        assert manager.validate_symlink() is False

    def test_validate_symlink_returns_false_when_wrong_target(self, tmp_path):
        """Test validate_symlink returns False when pointing to wrong directory."""
        comfyui_path = tmp_path / "ComfyUI"
        comfyui_path.mkdir()
        global_models = tmp_path / "global_models"
        global_models.mkdir()
        wrong_target = tmp_path / "wrong"
        wrong_target.mkdir()

        models_link = comfyui_path / "models"
        models_link.symlink_to(wrong_target)

        manager = ModelSymlinkManager(comfyui_path, global_models)
        assert manager.validate_symlink() is False

    def test_remove_symlink_removes_link_only(self, tmp_path):
        """Test remove_symlink only removes the link, not the target."""
        comfyui_path = tmp_path / "ComfyUI"
        comfyui_path.mkdir()
        global_models = tmp_path / "global_models"
        global_models.mkdir()

        # Create a file in global models to verify it's not deleted
        test_file = global_models / "test_model.safetensors"
        test_file.write_text("test data")

        models_link = comfyui_path / "models"
        models_link.symlink_to(global_models)

        manager = ModelSymlinkManager(comfyui_path, global_models)
        manager.remove_symlink()

        assert not models_link.exists(), "Symlink should be removed"
        assert test_file.exists(), "Target files should still exist"

    def test_remove_symlink_when_not_exists(self, tmp_path):
        """Test remove_symlink is safe when symlink doesn't exist."""
        comfyui_path = tmp_path / "ComfyUI"
        comfyui_path.mkdir()
        global_models = tmp_path / "global_models"
        global_models.mkdir()

        manager = ModelSymlinkManager(comfyui_path, global_models)
        manager.remove_symlink()  # Should not error

    def test_remove_symlink_errors_on_real_directory(self, tmp_path):
        """Test remove_symlink errors when models/ is a real directory."""
        comfyui_path = tmp_path / "ComfyUI"
        comfyui_path.mkdir()
        global_models = tmp_path / "global_models"
        global_models.mkdir()

        # Create real directory
        models_dir = comfyui_path / "models"
        models_dir.mkdir()
        (models_dir / "checkpoints").mkdir()

        manager = ModelSymlinkManager(comfyui_path, global_models)

        with pytest.raises(CDEnvironmentError) as exc_info:
            manager.remove_symlink()

        assert "not a link" in str(exc_info.value)
        assert models_dir.exists(), "Should not delete real directory"

    def test_get_status_shows_correct_info(self, tmp_path):
        """Test get_status returns useful debugging information."""
        comfyui_path = tmp_path / "ComfyUI"
        comfyui_path.mkdir()
        global_models = tmp_path / "global_models"
        global_models.mkdir()

        models_link = comfyui_path / "models"
        models_link.symlink_to(global_models)

        manager = ModelSymlinkManager(comfyui_path, global_models)
        status = manager.get_status()

        assert status["exists"] is True
        assert status["is_symlink"] is True
        assert status["is_valid"] is True
        assert status["target"] == str(global_models.resolve())
