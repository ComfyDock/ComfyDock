"""Tests for dependency probe utilities."""

from pathlib import Path

from comfygit_core.utils.dependency_probe import (
    DependencyProbe,
    ProbeResult,
)


class TestDetectPythonVersion:
    """Tests for _detect_python_version parsing requires-python."""

    def test_parses_gte_format(self, tmp_path):
        """Parses >=3.12 from legacy environments."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nrequires-python = ">=3.12"\n')
        probe = DependencyProbe(cec_path=tmp_path, workspace_path=tmp_path / "ws")
        assert probe._detect_python_version() == "3.12"

    def test_parses_pinned_wildcard_format(self, tmp_path):
        """Parses ==3.12.* from new environments."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nrequires-python = "==3.12.*"\n')
        probe = DependencyProbe(cec_path=tmp_path, workspace_path=tmp_path / "ws")
        assert probe._detect_python_version() == "3.12"

    def test_parses_pinned_311(self, tmp_path):
        """Parses ==3.11.* correctly."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nrequires-python = "==3.11.*"\n')
        probe = DependencyProbe(cec_path=tmp_path, workspace_path=tmp_path / "ws")
        assert probe._detect_python_version() == "3.11"


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


class TestRequirementFiltering:
    """Tests for protected requirement filtering in probe installs."""

    def test_install_one_by_one_no_constraints(self, tmp_path, monkeypatch):
        """uv pip_install calls should not include constraints pinning."""
        calls: list[dict] = []

        class FakeUV:
            def __init__(self, **kwargs):
                self.timeout = None

            def pip_install(self, **kwargs):
                calls.append(kwargs)

        probe = DependencyProbe(
            cec_path=tmp_path,
            workspace_path=tmp_path / "workspace",
        )

        monkeypatch.setattr("comfygit_core.utils.dependency_probe.UVCommand", FakeUV)
        monkeypatch.setattr(probe, "_get_probe_python", lambda: Path("/tmp/probe-python"))

        failures = probe._install_one_by_one(["numpy"])

        assert failures == []
        assert len(calls) == 1
        assert "constraints" not in calls[0]

    def test_filter_protected_requirements_handles_simple_url_and_editable(self, tmp_path):
        """Protected names should be skipped across common requirement forms."""
        probe = DependencyProbe(
            cec_path=tmp_path,
            workspace_path=tmp_path / "workspace",
        )

        installable, skipped = probe._filter_protected_requirements([
            "numpy>=2.0",
            "torch @ https://download.pytorch.org/whl/cu129",
            "-e git+https://example.com/repo.git#egg=torchsde",
            "requests>=2.32.0",
        ])

        assert "torch @ https://download.pytorch.org/whl/cu129" in skipped
        assert "-e git+https://example.com/repo.git#egg=torchsde" in skipped
        assert "numpy>=2.0" in installable
        assert "requests>=2.32.0" in installable

    def test_filter_protected_requirements_does_not_skip_unparseable_path(self, tmp_path):
        """Unparseable path/url requirements should be installed, not skipped."""
        probe = DependencyProbe(
            cec_path=tmp_path,
            workspace_path=tmp_path / "workspace",
        )

        installable, skipped = probe._filter_protected_requirements([
            "./local_package",
            "https://example.com/custom.whl",
        ])

        assert installable == ["./local_package", "https://example.com/custom.whl"]
        assert skipped == []

    def test_is_protected_uses_package_config_list(self, tmp_path):
        """Protected checks should use package config when provided."""

        class FakePackageConfig:
            @property
            def probe_protected_packages(self):
                return ["my_pkg"]

        probe = DependencyProbe(
            cec_path=tmp_path,
            workspace_path=tmp_path / "workspace",
            package_config=FakePackageConfig(),
        )

        assert probe._is_protected("my-pkg")
        assert not probe._is_protected("torch")

    def test_run_skips_protected_requirements_and_tracks_them(self, tmp_path, monkeypatch):
        """Protected requirements should be tracked and omitted from installs."""
        probe = DependencyProbe(
            cec_path=tmp_path,
            workspace_path=tmp_path / "workspace",
            keep_venv=True,
        )
        before = {"torch": "2.2.3"}
        after = {"torch": "2.2.3", "requests": "2.32.4"}
        install_calls: list[list[str]] = []

        def fake_create_probe_venv():
            probe.probe_venv.mkdir(parents=True, exist_ok=True)

        def fake_install(requirements):
            install_calls.append(list(requirements))
            return []

        monkeypatch.setattr(probe, "_create_probe_venv", fake_create_probe_venv)
        monkeypatch.setattr(probe, "_sync_probe_to_current_state", lambda: None)
        monkeypatch.setattr(probe, "_freeze_packages", lambda: before if not install_calls else after)
        monkeypatch.setattr(probe, "_install_one_by_one", fake_install)

        result = probe.run(["torch", "requests>=2.0"])

        assert result.success is True
        assert result.install_failures == []
        assert result.skipped_requirements == ["torch"]
        assert install_calls == [["requests>=2.0"]]

    def test_run_reports_install_failure_for_non_skipped_requirement(self, tmp_path, monkeypatch):
        """Install failures should still fail the probe after skip filtering."""
        probe = DependencyProbe(
            cec_path=tmp_path,
            workspace_path=tmp_path / "workspace",
            keep_venv=True,
        )
        before = {"torch": "2.2.3"}
        after = {"torch": "2.2.3"}
        failure_req = "librosa<0.1"
        install_calls: list[list[str]] = []

        def fake_create_probe_venv():
            probe.probe_venv.mkdir(parents=True, exist_ok=True)

        def fake_install(requirements):
            install_calls.append(list(requirements))
            return [failure_req]

        monkeypatch.setattr(probe, "_create_probe_venv", fake_create_probe_venv)
        monkeypatch.setattr(probe, "_sync_probe_to_current_state", lambda: None)
        monkeypatch.setattr(probe, "_freeze_packages", lambda: before if not install_calls else after)
        monkeypatch.setattr(probe, "_install_one_by_one", fake_install)

        result = probe.run(["torch", failure_req])

        assert result.success is False
        assert result.install_failures == [failure_req]
        assert result.skipped_requirements == ["torch"]
        assert install_calls == [[failure_req]]


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

        before = {"scipy": "1.15.1"}
        after = {"scipy": "1.14.0"}
        failures = []

        result = probe._analyze(before, after, failures)

        assert len(result.suggested_constraints) > 0
        assert any("scipy" in c for c in result.suggested_constraints)

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
    """Tests for protected package analyze compatibility behavior."""

    def test_protected_changes_remain_empty_for_compatibility(self, tmp_path):
        """protected_changes should remain empty in permissive probe mode."""
        probe = DependencyProbe(
            cec_path=tmp_path,
            workspace_path=tmp_path / "workspace",
        )

        before = {"torch": "2.4.0"}
        after = {"torch": "2.3.0"}
        failures = []

        result = probe._analyze(before, after, failures)

        assert "torch" in result.downgraded
        assert result.protected_changes == []

    def test_protected_package_downgrade_still_generates_constraint(self, tmp_path):
        """Downgrades discovered transitively still produce suggested constraints."""
        probe = DependencyProbe(
            cec_path=tmp_path,
            workspace_path=tmp_path / "workspace",
        )

        before = {"numpy": "2.3.0"}
        after = {"numpy": "2.2.0"}
        failures = []

        result = probe._analyze(before, after, failures)

        assert "numpy" in result.downgraded
        assert any("numpy<" in constraint for constraint in result.suggested_constraints)


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
        assert result.skipped_requirements == []

    def test_probe_result_with_values(self):
        """ProbeResult stores all provided values."""
        result = ProbeResult(
            success=False,
            added={"scipy": "1.15.0"},
            suggested_constraints=["numpy<2.4"],
            install_failures=["librosa"],
            skipped_requirements=["numpy"],
        )

        assert result.success is False
        assert result.added == {"scipy": "1.15.0"}
        assert result.suggested_constraints == ["numpy<2.4"]
        assert result.install_failures == ["librosa"]
        assert result.skipped_requirements == ["numpy"]
