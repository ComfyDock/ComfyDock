"""Tests for dependency probe utilities."""

from comfygit_core.utils.dependency_probe import (
    DependencyProbe,
    ProbeResult,
)


class TestVersionToConstraint:
    """Tests for _version_to_constraint method."""

    def test_next_minor_downgrade(self, tmp_path):
        """numpy 2.3.5 → numpy<2.4 (downgrade within same major)."""
        probe = DependencyProbe(
            cec_path=tmp_path,
            workspace_path=tmp_path / "workspace",
        )

        constraint = probe._version_to_constraint("numpy", "2.3.5")
        assert constraint == "numpy<2.4"

    def test_next_minor_downgrade_llvmlite(self, tmp_path):
        """llvmlite 0.46.0 → llvmlite<0.47."""
        probe = DependencyProbe(
            cec_path=tmp_path,
            workspace_path=tmp_path / "workspace",
        )

        constraint = probe._version_to_constraint("llvmlite", "0.46.0")
        assert constraint == "llvmlite<0.47"

    def test_major_downgrade_constraint(self, tmp_path):
        """Constraint uses next minor regardless of downgrade magnitude."""
        probe = DependencyProbe(
            cec_path=tmp_path,
            workspace_path=tmp_path / "workspace",
        )

        # Version 2.5.1 produces constraint <2.6 (next minor from downgraded version)
        constraint = probe._version_to_constraint("package", "2.5.1")
        assert constraint == "package<2.6"

    def test_normalize_package_names_in_constraint(self, tmp_path):
        """Constraint uses normalized package name (lowercase, - → _)."""
        probe = DependencyProbe(
            cec_path=tmp_path,
            workspace_path=tmp_path / "workspace",
        )

        constraint = probe._version_to_constraint("Foo-Bar", "1.2.3")
        # Should normalize to foo_bar or foo-bar in constraint
        assert "foo" in constraint.lower()


class TestAnalyzeDetectDowngrades:
    """Tests for _analyze detecting downgrades and suggesting constraints."""

    def test_analyze_detects_downgrade(self, tmp_path):
        """Detects when package version goes down."""
        probe = DependencyProbe(
            cec_path=tmp_path,
            workspace_path=tmp_path / "workspace",
        )

        before = {"numpy": "2.4.1", "scipy": "1.15.0"}
        after = {"numpy": "2.3.5", "scipy": "1.15.0"}
        failures = []

        result = probe._analyze(before, after, failures)

        assert result.success is True
        assert "numpy" in result.downgraded
        assert result.downgraded["numpy"] == ("2.4.1", "2.3.5")

    def test_analyze_suggests_constraint_for_downgrade(self, tmp_path):
        """Downgrade triggers constraint suggestion."""
        probe = DependencyProbe(
            cec_path=tmp_path,
            workspace_path=tmp_path / "workspace",
        )

        before = {"numpy": "2.4.1"}
        after = {"numpy": "2.3.5"}
        failures = []

        result = probe._analyze(before, after, failures)

        assert len(result.suggested_constraints) > 0
        assert any("numpy" in c for c in result.suggested_constraints)

    def test_analyze_detects_upgrade(self, tmp_path):
        """Detects when package version goes up."""
        probe = DependencyProbe(
            cec_path=tmp_path,
            workspace_path=tmp_path / "workspace",
        )

        before = {"numpy": "2.3.0"}
        after = {"numpy": "2.4.1"}
        failures = []

        result = probe._analyze(before, after, failures)

        assert "numpy" in result.upgraded
        assert result.upgraded["numpy"] == ("2.3.0", "2.4.1")

    def test_analyze_detects_added_packages(self, tmp_path):
        """Detects new packages added during install."""
        probe = DependencyProbe(
            cec_path=tmp_path,
            workspace_path=tmp_path / "workspace",
        )

        before = {"numpy": "2.4.1"}
        after = {"numpy": "2.4.1", "scipy": "1.15.0"}
        failures = []

        result = probe._analyze(before, after, failures)

        assert "scipy" in result.added
        assert result.added["scipy"] == "1.15.0"

    def test_analyze_detects_removed_packages(self, tmp_path):
        """Detects packages removed during install."""
        probe = DependencyProbe(
            cec_path=tmp_path,
            workspace_path=tmp_path / "workspace",
        )

        before = {"numpy": "2.4.1", "scipy": "1.15.0"}
        after = {"numpy": "2.4.1"}
        failures = []

        result = probe._analyze(before, after, failures)

        assert "scipy" in result.removed
        assert result.removed["scipy"] == "1.15.0"


class TestAnalyzeProtectedPackages:
    """Tests for protected package detection."""

    def test_does_not_suggest_constraint_for_protected_torch(self, tmp_path):
        """torch downgrade should NOT generate constraint."""
        probe = DependencyProbe(
            cec_path=tmp_path,
            workspace_path=tmp_path / "workspace",
        )

        before = {"torch": "2.4.0"}
        after = {"torch": "2.3.0"}
        failures = []

        result = probe._analyze(before, after, failures)

        # torch downgrade should be captured in downgraded but NO constraint suggested
        assert "torch" in result.downgraded
        assert not any("torch" in c for c in result.suggested_constraints)

    def test_marks_protected_change_for_torch(self, tmp_path):
        """Protected packages are flagged in protected_changes."""
        probe = DependencyProbe(
            cec_path=tmp_path,
            workspace_path=tmp_path / "workspace",
        )

        before = {"torch": "2.4.0"}
        after = {"torch": "2.3.0"}
        failures = []

        result = probe._analyze(before, after, failures)

        assert "torch" in result.protected_changes

    def test_all_protected_packages_detected(self, tmp_path):
        """All packages in PROTECTED_PACKAGES are flagged."""
        probe = DependencyProbe(
            cec_path=tmp_path,
            workspace_path=tmp_path / "workspace",
        )

        # Test that transformers and safetensors are protected
        before = {"transformers": "4.40.0", "safetensors": "0.4.0"}
        after = {"transformers": "4.35.0", "safetensors": "0.3.5"}
        failures = []

        result = probe._analyze(before, after, failures)

        assert "transformers" in result.protected_changes
        assert "safetensors" in result.protected_changes


class TestAnalyzeFailures:
    """Tests for failure handling in analyze."""

    def test_marks_failure_when_install_failures(self, tmp_path):
        """When some requirements fail to install, success=False."""
        probe = DependencyProbe(
            cec_path=tmp_path,
            workspace_path=tmp_path / "workspace",
        )

        before = {"numpy": "2.4.1"}
        after = {"numpy": "2.4.1"}
        failures = ["librosa"]

        result = probe._analyze(before, after, failures)

        assert result.success is False
        assert "librosa" in result.install_failures

    def test_captures_all_failure_packages(self, tmp_path):
        """All failed packages are captured."""
        probe = DependencyProbe(
            cec_path=tmp_path,
            workspace_path=tmp_path / "workspace",
        )

        before = {"numpy": "2.4.1"}
        after = {"numpy": "2.4.1"}
        failures = ["librosa", "soundfile"]

        result = probe._analyze(before, after, failures)

        assert len(result.install_failures) == 2
        assert "librosa" in result.install_failures
        assert "soundfile" in result.install_failures


class TestPackageNameNormalization:
    """Tests for package name normalization."""

    def test_normalize_uppercase(self, tmp_path):
        """Package names are normalized to lowercase."""
        probe = DependencyProbe(
            cec_path=tmp_path,
            workspace_path=tmp_path / "workspace",
        )

        normalized = probe._normalize_name("Foo-Bar")
        # Should be lowercase, may use - or _
        assert normalized == normalized.lower()

    def test_normalize_underscore_dash(self, tmp_path):
        """Dashes are normalized to underscores in names."""
        probe = DependencyProbe(
            cec_path=tmp_path,
            workspace_path=tmp_path / "workspace",
        )

        # Package index treats foo-bar and foo_bar as same package
        normalized = probe._normalize_name("foo-bar")
        assert "-" not in normalized or "_" in normalized


class TestProbeResultDataclass:
    """Tests for ProbeResult dataclass."""

    def test_probe_result_defaults(self):
        """ProbeResult initializes with correct defaults."""
        result = ProbeResult(success=True)

        assert result.success is True
        assert result.added == {}
        assert result.removed == {}
        assert result.upgraded == {}
        assert result.downgraded == {}
        assert result.protected_changes == []
        assert result.suggested_constraints == []
        assert result.install_failures == []

    def test_probe_result_with_values(self):
        """ProbeResult stores all provided values."""
        result = ProbeResult(
            success=False,
            added={"scipy": "1.15.0"},
            suggested_constraints=["numpy<2.4"],
            install_failures=["librosa"],
        )

        assert result.success is False
        assert result.added == {"scipy": "1.15.0"}
        assert result.suggested_constraints == ["numpy<2.4"]
        assert result.install_failures == ["librosa"]
