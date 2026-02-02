"""Tests for environment creation progress callbacks."""
from dataclasses import dataclass, field


@dataclass
class ProgressTracker:
    """Test implementation of EnvironmentCreateProgress to capture callbacks."""
    phases: list[tuple[str, str, int]] = field(default_factory=list)
    completed_phases: list[tuple[str, bool, str | None]] = field(default_factory=list)

    def on_phase(self, phase: str, description: str, progress_pct: int) -> None:
        """Capture phase transitions."""
        self.phases.append((phase, description, progress_pct))

    def on_phase_complete(self, phase: str, success: bool, error: str | None = None) -> None:
        """Capture phase completions."""
        self.completed_phases.append((phase, success, error))


class TestEnvironmentCreateProgress:
    """Tests for environment creation progress callbacks."""

    def test_create_environment_calls_progress_callbacks(
        self, test_workspace, mock_comfyui_clone, mock_github_api
    ):
        """Progress callbacks should be invoked during environment creation."""
        # ARRANGE
        tracker = ProgressTracker()

        # ACT
        test_workspace.create_environment(
            name="progress-test-env",
            progress=tracker,
        )

        # ASSERT - Should have received phase callbacks
        assert len(tracker.phases) > 0, "Expected progress callbacks to be invoked"

        # Verify we got key phases
        phase_names = [p[0] for p in tracker.phases]
        assert "clone_comfyui" in phase_names or "restore_comfyui" in phase_names, \
            f"Expected ComfyUI phase, got: {phase_names}"
        assert "probe_pytorch" in phase_names, \
            f"Expected PyTorch phase, got: {phase_names}"

        # Verify progress increases monotonically
        progress_values = [p[2] for p in tracker.phases]
        for i in range(1, len(progress_values)):
            assert progress_values[i] >= progress_values[i-1], \
                f"Progress should increase monotonically: {progress_values}"

        # Verify final progress is 100%
        assert progress_values[-1] == 100, \
            f"Final progress should be 100%, got {progress_values[-1]}"

    def test_create_environment_phase_descriptions_are_human_readable(
        self, test_workspace, mock_comfyui_clone, mock_github_api
    ):
        """Phase descriptions should be human-readable for UI display."""
        # ARRANGE
        tracker = ProgressTracker()

        # ACT
        test_workspace.create_environment(
            name="human-readable-test",
            progress=tracker,
        )

        # ASSERT - All descriptions should be non-empty strings
        for phase, description, _ in tracker.phases:
            assert isinstance(description, str), f"Description should be string: {description}"
            assert len(description) > 0, f"Description should not be empty for phase: {phase}"
            # Should not be technical identifiers
            assert "_" not in description or " " in description, \
                f"Description should be human-readable: {description}"

    def test_create_environment_works_without_progress_callback(
        self, test_workspace, mock_comfyui_clone, mock_github_api
    ):
        """Environment creation should work normally without progress callback."""
        # ACT - No progress callback provided
        env = test_workspace.create_environment(
            name="no-progress-test",
        )

        # ASSERT - Environment should be created successfully
        assert env is not None
        assert env.name == "no-progress-test"
        assert env.path.exists()
