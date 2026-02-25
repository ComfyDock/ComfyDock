"""Tests for dependency_parser.py utilities."""

from comfygit_core.utils.dependency_parser import (
    compare_dependency_sets,
    extract_all_dependencies,
    find_most_restrictive_constraint,
    is_meaningful_version_change,
    parse_dependency_string,
)


class TestParseDependencyString:
    def test_simple_package(self):
        name, spec = parse_dependency_string("numpy")
        assert name == "numpy"
        assert spec is None

    def test_package_with_version(self):
        name, spec = parse_dependency_string("numpy>=1.21.0")
        assert name == "numpy"
        assert spec == ">=1.21.0"

    def test_package_with_extras(self):
        name, spec = parse_dependency_string("torch[cuda]>=2.0")
        assert name == "torch"
        assert spec == ">=2.0"

    def test_package_with_dotted_name(self):
        name, spec = parse_dependency_string("zope.interface>=5")
        assert name == "zope.interface"
        assert spec == ">=5"

    def test_exact_pin(self):
        name, spec = parse_dependency_string("requests==2.28.0")
        assert name == "requests"
        assert spec == "==2.28.0"

    def test_empty_string(self):
        name, spec = parse_dependency_string("")
        assert name == ""
        assert spec is None


class TestExtractAllDependencies:
    def test_main_dependencies(self):
        pyproject_data = {
            "project": {
                "dependencies": ["numpy>=1.21", "requests==2.28.0"]
            }
        }
        result = extract_all_dependencies(pyproject_data)

        assert "numpy" in result
        assert "requests" in result
        assert result["numpy"]["version"] == ">=1.21"
        assert result["requests"]["version"] == "==2.28.0"

    def test_dependency_groups(self):
        pyproject_data = {
            "dependency-groups": {
                "test": ["pytest>=7.0"],
                "dev": ["black", "ruff>=0.1.0"]
            }
        }
        result = extract_all_dependencies(pyproject_data)

        assert "pytest" in result
        assert "black" in result
        assert result["pytest"]["source"] == "group:test"
        assert result["black"]["source"] == "group:dev"

    def test_empty_pyproject(self):
        result = extract_all_dependencies({})
        assert result == {}

    def test_duplicate_packages_most_restrictive(self):
        pyproject_data = {
            "project": {"dependencies": ["numpy>=1.20"]},
            "dependency-groups": {"test": ["numpy==1.24.0"]}
        }
        result = extract_all_dependencies(pyproject_data)

        assert result["numpy"]["version"] == "==1.24.0"  # Exact pin wins


class TestIsMeaningfulVersionChange:
    def test_no_change_both_none(self):
        assert not is_meaningful_version_change(None, None)

    def test_no_change_identical(self):
        assert not is_meaningful_version_change(">=1.0", ">=1.0")

    def test_meaningful_change_none_to_pin(self):
        assert is_meaningful_version_change(None, "==1.0")

    def test_no_change_none_to_lower_bound(self):
        assert not is_meaningful_version_change(None, ">=1.0")

    def test_meaningful_change_pin_to_none(self):
        assert is_meaningful_version_change("==1.0", None)

    def test_meaningful_change_different_versions(self):
        assert is_meaningful_version_change(">=1.0", ">=2.0")


class TestFindMostRestrictiveConstraint:
    def test_empty_list(self):
        assert find_most_restrictive_constraint([]) is None

    def test_exact_pin_wins(self):
        constraints = [">=1.0", "==1.5", "<2.0"]
        assert find_most_restrictive_constraint(constraints) == "==1.5"

    def test_upper_bound_over_lower(self):
        constraints = [">=1.0", "<2.0"]
        assert find_most_restrictive_constraint(constraints) == "<2.0"

    def test_range_over_lower(self):
        constraints = [">=1.0", ">=1.5,<2.0"]
        assert find_most_restrictive_constraint(constraints) == ">=1.5,<2.0"

    def test_filters_none_values(self):
        constraints = [None, ">=1.0", None]
        assert find_most_restrictive_constraint(constraints) == ">=1.0"


class TestCompareDependencySets:
    def test_added_packages(self):
        before = {}
        after = {"numpy": {"version": ">=1.0", "source": "main"}}

        changes = compare_dependency_sets(before, after)

        assert len(changes["added"]) == 1
        assert changes["added"][0]["name"] == "numpy"
        assert len(changes["removed"]) == 0
        assert len(changes["updated"]) == 0

    def test_removed_packages(self):
        before = {"numpy": {"version": ">=1.0"}}
        after = {}

        changes = compare_dependency_sets(before, after)

        assert len(changes["removed"]) == 1
        assert changes["removed"][0]["name"] == "numpy"
        assert len(changes["added"]) == 0
        assert len(changes["updated"]) == 0

    def test_updated_packages(self):
        before = {"numpy": {"version": ">=1.0"}}
        after = {"numpy": {"version": "==1.24.0", "source": "main"}}

        changes = compare_dependency_sets(before, after)

        assert len(changes["updated"]) == 1
        assert changes["updated"][0]["name"] == "numpy"
        assert changes["updated"][0]["old_version"] == ">=1.0"
        assert changes["updated"][0]["new_version"] == "==1.24.0"

    def test_no_meaningful_changes_ignored(self):
        before = {"numpy": {"version": None}}
        after = {"numpy": {"version": ">=1.0", "source": "main"}}

        changes = compare_dependency_sets(before, after)

        # Should not be considered an update (none to lower bound)
        assert len(changes["updated"]) == 0
        assert len(changes["added"]) == 0
        assert len(changes["removed"]) == 0
