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


class TestProbeVenvPath:
    """Tests for probe venv path uniqueness."""

    def test_probe_venv_path_is_unique(self, tmp_path):
        """Each probe instance should use a unique venv directory."""
        probe_one = DependencyProbe(
            cec_path=tmp_path,
            workspace_path=tmp_path / "workspace",
        )
        probe_two = DependencyProbe(
            cec_path=tmp_path,
            workspace_path=tmp_path / "workspace",
        )

        assert probe_one.probe_venv != probe_two.probe_venv
        assert probe_one.probe_venv.name.startswith(".venv-probe-")
        assert probe_two.probe_venv.name.startswith(".venv-probe-")


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

        # Test that torch-related packages are protected (MVP: torch-only)
        before = {"torch": "2.4.0", "torchvision": "0.19.0"}
        after = {"torch": "2.3.0", "torchvision": "0.18.0"}
        failures = []

        result = probe._analyze(before, after, failures)

        assert "torch" in result.protected_changes
        assert "torchvision" in result.protected_changes


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
    """Tests for package name normalization using PEP 503 canonical form."""

    def test_normalize_uppercase(self, tmp_path):
        """Package names are normalized to lowercase per PEP 503."""
        probe = DependencyProbe(
            cec_path=tmp_path,
            workspace_path=tmp_path / "workspace",
        )

        normalized = probe._normalize_name("Foo-Bar")
        # PEP 503: lowercase with dashes
        assert normalized == "foo-bar"

    def test_normalize_underscore_to_dash(self, tmp_path):
        """Underscores are normalized to dashes per PEP 503."""
        probe = DependencyProbe(
            cec_path=tmp_path,
            workspace_path=tmp_path / "workspace",
        )

        # PEP 503 canonical form uses dashes
        normalized = probe._normalize_name("foo_bar")
        assert normalized == "foo-bar"

    def test_normalize_mixed_separators(self, tmp_path):
        """Multiple separators (-, _, .) collapse to single dash per PEP 503."""
        probe = DependencyProbe(
            cec_path=tmp_path,
            workspace_path=tmp_path / "workspace",
        )

        # PEP 503: runs of separators become single dash
        assert probe._normalize_name("foo__bar") == "foo-bar"
        assert probe._normalize_name("foo..bar") == "foo-bar"
        assert probe._normalize_name("foo-_-bar") == "foo-bar"

    def test_normalize_matches_packaging_utils(self, tmp_path):
        """Normalization should match packaging.utils.canonicalize_name."""
        from packaging.utils import canonicalize_name

        probe = DependencyProbe(
            cec_path=tmp_path,
            workspace_path=tmp_path / "workspace",
        )

        test_cases = [
            "Hugging_Face.Hub",
            "foo-bar",
            "foo_bar",
            "COMfyUI-Manager",
            "numpy",
        ]

        for name in test_cases:
            assert probe._normalize_name(name) == canonicalize_name(name)

    def test_version_to_constraint_uses_canonical_names(self, tmp_path):
        """Generated constraints should use PEP 503 canonical names (dashes)."""
        probe = DependencyProbe(
            cec_path=tmp_path,
            workspace_path=tmp_path / "workspace",
        )

        # Test with underscore input - should output dash-separated
        constraint = probe._version_to_constraint("huggingface_hub", "0.36.0")
        assert constraint == "huggingface-hub<0.37"

        # Test with mixed separators
        constraint = probe._version_to_constraint("Foo__Bar", "1.2.3")
        assert constraint == "foo-bar<1.3"

    def test_normalization_matches_conflict_analyzer(self, tmp_path):
        """Probe normalization must match conflict_analyzer for constraint compatibility."""
        from comfygit_core.utils.conflict_analyzer import normalize_package_name_pep503

        probe = DependencyProbe(
            cec_path=tmp_path,
            workspace_path=tmp_path / "workspace",
        )

        test_cases = [
            "huggingface_hub",
            "Hugging-Face.Hub",
            "foo__bar",
            "COMfyUI_Manager",
        ]

        for name in test_cases:
            probe_normalized = probe._normalize_name(name)
            analyzer_normalized = normalize_package_name_pep503(name)
            assert probe_normalized == analyzer_normalized, (
                f"Normalization mismatch for '{name}': "
                f"probe='{probe_normalized}' vs analyzer='{analyzer_normalized}'"
            )


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
