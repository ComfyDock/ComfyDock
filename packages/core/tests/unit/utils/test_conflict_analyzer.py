"""Tests for conflict_analyzer.py utilities."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from comfygit_core.utils.conflict_analyzer import (
    ConflictAnalysis,
    ConflictChain,
    analyze_conflict,
    check_specifier_compatibility,
    format_conflict_report,
    get_existing_requirements,
    parse_conflict_from_stderr,
    parse_constraint_string,
)

# Real UV error output from depthflow conflict scenario
DEPTHFLOW_UV_ERROR = """
error: Cannot install depthflow==0.9.1 because:
    transformers==4.53.3 depends on huggingface-hub<1.0,>=0.30.0
    but comfygit-core==0.3.13 requires huggingface-hub>=1.1.0

we can conclude that depthflow==0.9.1 and comfygit-core==0.3.13 are incompatible

hint: To resolve this conflict, consider:
  - Using a different version of one of the packages
  - Adding an override-dependencies entry
"""


class TestParseConflictFromStderr:
    def test_parses_conflicting_package_name(self):
        """Should extract huggingface-hub as the conflicting package."""
        pkg, constraints = parse_conflict_from_stderr(DEPTHFLOW_UV_ERROR)

        assert pkg == "huggingface-hub"

    def test_extracts_version_constraints(self):
        """Should extract both version constraints mentioned."""
        pkg, constraints = parse_conflict_from_stderr(DEPTHFLOW_UV_ERROR)

        # Should have at least the two constraints from the error
        constraint_strs = [c.get("constraint", "") for c in constraints]
        assert any("<1.0" in c or ">=0.30.0" in c for c in constraint_strs)
        assert any(">=1.1.0" in c for c in constraint_strs)

    def test_returns_none_for_non_conflict_error(self):
        """Should return None for errors that aren't dependency conflicts."""
        pkg, constraints = parse_conflict_from_stderr("Some random error message")

        assert pkg is None
        assert constraints == []

    def test_handles_empty_input(self):
        """Should handle empty input gracefully."""
        pkg, constraints = parse_conflict_from_stderr("")

        assert pkg is None
        assert constraints == []


class TestAnalyzeConflict:
    def test_returns_none_for_non_conflict_stderr(self):
        """Should return None when stderr doesn't contain a conflict."""
        result = analyze_conflict(
            stderr="No error here",
            new_package="some-package==1.0.0",
        )

        assert result is None

    @patch("comfygit_core.utils.conflict_analyzer.subprocess.run")
    def test_analyzes_conflict_with_venv(self, mock_run):
        """Should run uv commands when venv is provided."""
        # Mock uv pip tree output
        mock_tree_result = MagicMock()
        mock_tree_result.returncode = 0
        mock_tree_result.stdout = """huggingface-hub v1.1.0
└── comfygit-core v0.3.13 [requires: huggingface-hub>=1.1.0]
"""

        # Mock uv pip compile output
        mock_compile_result = MagicMock()
        mock_compile_result.returncode = 0
        mock_compile_result.stdout = """depthflow==0.9.1
    # via -r -
transformers==4.53.3
    # via depthflow
huggingface-hub==0.30.0
    # via transformers
"""

        mock_run.side_effect = [mock_tree_result, mock_compile_result]

        result = analyze_conflict(
            stderr=DEPTHFLOW_UV_ERROR,
            new_package="depthflow==0.9.1",
            venv_python=Path("/fake/venv/bin/python"),
            uv_path=Path("/fake/uv"),
        )

        assert result is not None
        assert isinstance(result, ConflictAnalysis)
        assert result.conflicting_package == "huggingface-hub"

    @patch("comfygit_core.utils.conflict_analyzer.subprocess.run")
    def test_captures_existing_constraints(self, mock_run):
        """Should capture what existing packages require the conflicting dep."""
        mock_tree_result = MagicMock()
        mock_tree_result.returncode = 0
        mock_tree_result.stdout = """huggingface-hub v1.1.0
└── comfygit-core v0.3.13 [requires: huggingface-hub>=1.1.0]
"""
        mock_compile_result = MagicMock()
        mock_compile_result.returncode = 0
        mock_compile_result.stdout = ""

        mock_run.side_effect = [mock_tree_result, mock_compile_result]

        result = analyze_conflict(
            stderr=DEPTHFLOW_UV_ERROR,
            new_package="depthflow==0.9.1",
            venv_python=Path("/fake/venv/bin/python"),
            uv_path=Path("/fake/uv"),
        )

        assert result is not None
        # Should have comfygit-core as requiring huggingface-hub
        existing_pkgs = [pkg for pkg, _ in result.existing_constraints]
        assert "comfygit-core" in existing_pkgs

    @patch("comfygit_core.utils.conflict_analyzer.subprocess.run")
    def test_builds_new_package_chains(self, mock_run):
        """Should build dependency chains for the new package."""
        mock_tree_result = MagicMock()
        mock_tree_result.returncode = 0
        mock_tree_result.stdout = ""

        mock_compile_result = MagicMock()
        mock_compile_result.returncode = 0
        mock_compile_result.stdout = """depthflow==0.9.1
    # via -r -
transformers==4.53.3
    # via depthflow
huggingface-hub==0.30.0
    # via transformers
"""

        mock_run.side_effect = [mock_tree_result, mock_compile_result]

        result = analyze_conflict(
            stderr=DEPTHFLOW_UV_ERROR,
            new_package="depthflow==0.9.1",
            venv_python=Path("/fake/venv/bin/python"),
            uv_path=Path("/fake/uv"),
        )

        assert result is not None
        assert len(result.new_package_chains) > 0

        # Should have chain: depthflow -> transformers -> huggingface-hub
        chain = result.new_package_chains[0]
        assert isinstance(chain, ConflictChain)
        assert chain.root_package == "depthflow"
        assert "huggingface-hub" in chain.chain

    def test_gracefully_handles_missing_venv(self):
        """Should still provide basic analysis without venv."""
        result = analyze_conflict(
            stderr=DEPTHFLOW_UV_ERROR,
            new_package="depthflow==0.9.1",
            venv_python=None,
            uv_path=None,
        )

        # Should still parse the conflict from stderr
        assert result is not None
        assert result.conflicting_package == "huggingface-hub"


class TestConflictChain:
    def test_dataclass_fields(self):
        """ConflictChain should have expected fields."""
        chain = ConflictChain(
            root_package="depthflow",
            chain=["depthflow", "transformers", "huggingface-hub"],
            constraint="huggingface-hub<1.0,>=0.30.0",
            constraint_source="transformers",
        )

        assert chain.root_package == "depthflow"
        assert chain.chain == ["depthflow", "transformers", "huggingface-hub"]
        assert chain.constraint == "huggingface-hub<1.0,>=0.30.0"
        assert chain.constraint_source == "transformers"


class TestConflictAnalysis:
    def test_dataclass_fields(self):
        """ConflictAnalysis should have expected fields."""
        analysis = ConflictAnalysis(
            conflicting_package="huggingface-hub",
            existing_constraints=[("comfygit-core", ">=1.1.0")],
            new_package_chains=[],
            suggestions=["Try updating transformers"],
        )

        assert analysis.conflicting_package == "huggingface-hub"
        assert analysis.existing_constraints == [("comfygit-core", ">=1.1.0")]
        assert analysis.suggestions == ["Try updating transformers"]


class TestFormatConflictReport:
    def test_formats_complete_analysis(self):
        """Should produce the specified output format."""
        chain = ConflictChain(
            root_package="depthflow",
            chain=["depthflow", "transformers", "huggingface-hub"],
            constraint="huggingface-hub<1.0,>=0.30.0",
            constraint_source="transformers",
        )

        analysis = ConflictAnalysis(
            conflicting_package="huggingface-hub",
            existing_constraints=[("comfygit-core", ">=1.1.0")],
            new_package_chains=[chain],
            suggestions=["Add override-dependencies for transformers"],
        )

        report = format_conflict_report(analysis)

        # Check key elements are present
        assert "DEPENDENCY CONFLICT ANALYSIS" in report
        assert "huggingface-hub" in report
        assert "comfygit-core" in report
        assert "depthflow" in report
        assert "transformers" in report
        assert "SOLUTIONS" in report or "Suggestions" in report.upper()

    def test_formats_without_chains(self):
        """Should handle analysis without dependency chains."""
        analysis = ConflictAnalysis(
            conflicting_package="some-package",
            existing_constraints=[("other-package", ">=2.0")],
            new_package_chains=[],
            suggestions=[],
        )

        report = format_conflict_report(analysis)

        assert "some-package" in report
        assert "other-package" in report

    def test_includes_suggestions(self):
        """Should include actionable suggestions."""
        analysis = ConflictAnalysis(
            conflicting_package="pkg",
            existing_constraints=[],
            new_package_chains=[],
            suggestions=[
                "Try version override",
                "Contact maintainer",
            ],
        )

        report = format_conflict_report(analysis)

        assert "version override" in report.lower() or "override" in report.lower()


class TestParseConstraintString:
    def test_normalizes_name_and_strips_input(self):
        parsed = parse_constraint_string("  huggingface_hub<0.37  ")
        assert parsed == ("huggingface-hub", "<0.37")

    def test_returns_none_for_name_only(self):
        assert parse_constraint_string("numpy") is None

    def test_returns_none_for_wildcard_spec(self):
        assert parse_constraint_string("numpy *") is None


class TestNormalizePackageNamePep503:
    """Tests for PEP 503 package name normalization."""

    def test_normalizes_uppercase_to_lowercase(self):
        from comfygit_core.utils.conflict_analyzer import normalize_package_name_pep503

        assert normalize_package_name_pep503("Foo-Bar") == "foo-bar"
        assert normalize_package_name_pep503("NUMPY") == "numpy"

    def test_normalizes_underscores_to_dashes(self):
        from comfygit_core.utils.conflict_analyzer import normalize_package_name_pep503

        assert normalize_package_name_pep503("foo_bar") == "foo-bar"
        assert normalize_package_name_pep503("huggingface_hub") == "huggingface-hub"

    def test_collapses_multiple_separators(self):
        from comfygit_core.utils.conflict_analyzer import normalize_package_name_pep503

        assert normalize_package_name_pep503("foo__bar") == "foo-bar"
        assert normalize_package_name_pep503("foo..bar") == "foo-bar"
        assert normalize_package_name_pep503("foo-_-bar") == "foo-bar"

    def test_matches_packaging_utils_canonicalize(self):
        """Should match packaging.utils.canonicalize_name exactly."""
        from comfygit_core.utils.conflict_analyzer import normalize_package_name_pep503
        from packaging.utils import canonicalize_name

        test_cases = [
            "Hugging_Face.Hub",
            "foo-bar",
            "foo_bar",
            "COMfyUI-Manager",
            "numpy",
            "Foo__Bar",
        ]

        for name in test_cases:
            assert normalize_package_name_pep503(name) == canonicalize_name(name)


class TestGetExistingRequirements:
    @patch("comfygit_core.utils.conflict_analyzer.subprocess.run")
    def test_parses_first_level_deps_with_non_numeric_versions(self, mock_run):
        mock_tree_result = MagicMock()
        mock_tree_result.returncode = 0
        mock_tree_result.stdout = """huggingface-hub v1.1.0
└── comfygit-core v0.3.13rc1 [requires: huggingface-hub>=1.1.0]
    └── nested-pkg v1.0.0 [requires: comfygit-core>=0.3.0]
"""
        mock_run.return_value = mock_tree_result

        reqs = get_existing_requirements(
            "huggingface-hub", Path("/fake/venv/bin/python"), Path("/fake/uv")
        )
        assert ("comfygit-core", "huggingface-hub>=1.1.0") in reqs

    @patch("comfygit_core.utils.conflict_analyzer.subprocess.run")
    def test_skips_any_version_wildcard_but_not_pep440_wildcards(self, mock_run):
        mock_tree_result = MagicMock()
        mock_tree_result.returncode = 0
        mock_tree_result.stdout = """huggingface-hub v1.1.0
└── any-version v1.0.0 [requires: huggingface-hub *]
└── pep440-wildcard v1.0.0 [requires: huggingface-hub==1.2.*]
"""
        mock_run.return_value = mock_tree_result

        reqs = get_existing_requirements(
            "huggingface-hub", Path("/fake/venv/bin/python"), Path("/fake/uv")
        )
        requiring_pkgs = {pkg for pkg, _ in reqs}

        assert "any-version" not in requiring_pkgs
        assert "pep440-wildcard" in requiring_pkgs


class TestCheckSpecifierCompatibility:
    @patch("comfygit_core.utils.conflict_analyzer.subprocess.run")
    def test_uses_no_deps_and_python(self, mock_run):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        ok, _ = check_specifier_compatibility(
            "huggingface-hub>=1.1.0",
            "huggingface-hub<0.37",
            venv_python=Path("/fake/venv/bin/python"),
            uv_path=Path("/fake/uv"),
        )
        assert ok is True

        args, kwargs = mock_run.call_args
        cmd = args[0]
        assert "--no-deps" in cmd
        assert "--python" in cmd
        assert "/fake/venv/bin/python" in cmd
        assert "-" in cmd
        assert kwargs.get("input") is not None

    @patch("comfygit_core.utils.conflict_analyzer.subprocess.run")
    def test_returns_false_for_unsatisfiable(self, mock_run):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "requirements are unsatisfiable"
        mock_run.return_value = mock_result

        ok, stderr = check_specifier_compatibility(
            "huggingface-hub>=1.1.0",
            "huggingface-hub<0.37",
            venv_python=None,
            uv_path=Path("/fake/uv"),
        )
        assert ok is False
        assert "unsatisfiable" in stderr

    @patch("comfygit_core.utils.conflict_analyzer.subprocess.run")
    def test_treats_non_unsatisfiable_failures_as_compatible(self, mock_run):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "connection refused"
        mock_run.return_value = mock_result

        ok, stderr = check_specifier_compatibility(
            "huggingface-hub>=1.1.0",
            "huggingface-hub<0.37",
            venv_python=None,
            uv_path=Path("/fake/uv"),
        )
        assert ok is True
        assert stderr == ""
