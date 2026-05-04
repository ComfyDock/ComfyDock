"""Tests for dev node rename detection."""

from pathlib import Path
from unittest.mock import Mock

import pytest
from comfygit_core.analyzers.status_scanner import StatusScanner
from comfygit_core.models.environment import EnvironmentState, NodeState


@pytest.fixture
def status_scanner(tmp_path):
    """Create a StatusScanner with mocked dependencies."""
    comfyui_path = tmp_path / "ComfyUI"
    comfyui_path.mkdir()
    custom_nodes = comfyui_path / "custom_nodes"
    custom_nodes.mkdir()

    uv_mock = Mock()
    pyproject_mock = Mock()
    venv_path = tmp_path / ".venv"

    return StatusScanner(uv_mock, pyproject_mock, venv_path, comfyui_path)


def test_no_rename_detection_when_no_missing_nodes(status_scanner):
    """No rename warning when there are no missing nodes."""
    current = EnvironmentState(
        custom_nodes={'node-a': NodeState(name='node-a', path=Path('node-a'))},
        packages={},
        python_version='3.11'
    )
    expected = EnvironmentState(
        custom_nodes={'node-a': NodeState(name='node-a', path=Path('node-a'), source='development')},
        packages={},
        python_version='3.11'
    )

    comparison = status_scanner.compare_states(current, expected)
    assert not comparison.potential_dev_rename


def test_no_rename_detection_when_no_extra_nodes(status_scanner):
    """No rename warning when there are no extra nodes."""
    current = EnvironmentState(
        custom_nodes={},
        packages={},
        python_version='3.11'
    )
    expected = EnvironmentState(
        custom_nodes={'node-a': NodeState(name='node-a', path=Path('node-a'), source='development')},
        packages={},
        python_version='3.11'
    )

    comparison = status_scanner.compare_states(current, expected)
    assert not comparison.potential_dev_rename


def test_no_rename_detection_when_missing_is_not_dev_node(status_scanner):
    """No rename warning when missing node is not a dev node."""
    current = EnvironmentState(
        custom_nodes={'node-b': NodeState(name='node-b', path=Path('node-b'))},
        packages={},
        python_version='3.11'
    )
    expected = EnvironmentState(
        custom_nodes={'node-a': NodeState(name='node-a', path=Path('node-a'), source='registry')},
        packages={},
        python_version='3.11'
    )

    comparison = status_scanner.compare_states(current, expected)
    assert not comparison.potential_dev_rename


def test_git_node_version_comparison_uses_commit(status_scanner):
    """Git-sourced nodes should compare manifest versions against the checked-out commit."""
    current = EnvironmentState(
        custom_nodes={
            'comfyui-qweneditutils': NodeState(
                name='comfyui-qweneditutils',
                path=Path('comfyui-qweneditutils'),
                git_commit='cdd4d028c6491d27a40092d7795158668cec9189',
                version='2.0.7',
            )
        },
        packages={},
        python_version='3.11',
    )
    expected = EnvironmentState(
        custom_nodes={
            'comfyui-qweneditutils': NodeState(
                name='comfyui-qweneditutils',
                path=Path('comfyui-qweneditutils'),
                source='git',
                version='cdd4d028c6491d27a40092d7795158668cec9189',
            )
        },
        packages={},
        python_version='3.11',
    )

    comparison = status_scanner.compare_states(current, expected)
    assert comparison.version_mismatches == []


def test_registry_node_version_comparison_uses_package_version_semantics(status_scanner):
    """Registry node metadata can omit insignificant trailing version segments."""
    current = EnvironmentState(
        custom_nodes={
            'CG Use Everywhere': NodeState(
                name='CG Use Everywhere',
                path=Path('CG Use Everywhere'),
                version='7.8',
            )
        },
        packages={},
        python_version='3.11',
    )
    expected = EnvironmentState(
        custom_nodes={
            'CG Use Everywhere': NodeState(
                name='CG Use Everywhere',
                path=Path('CG Use Everywhere'),
                source='registry',
                version='7.8.0',
            )
        },
        packages={},
        python_version='3.11',
    )

    comparison = status_scanner.compare_states(current, expected)
    assert comparison.version_mismatches == []


def test_registry_node_version_comparison_still_reports_real_mismatch(status_scanner):
    """Semver normalization must not hide actual registry node version drift."""
    current = EnvironmentState(
        custom_nodes={
            'CG Use Everywhere': NodeState(
                name='CG Use Everywhere',
                path=Path('CG Use Everywhere'),
                version='7.7',
            )
        },
        packages={},
        python_version='3.11',
    )
    expected = EnvironmentState(
        custom_nodes={
            'CG Use Everywhere': NodeState(
                name='CG Use Everywhere',
                path=Path('CG Use Everywhere'),
                source='registry',
                version='7.8.0',
            )
        },
        packages={},
        python_version='3.11',
    )

    comparison = status_scanner.compare_states(current, expected)
    assert comparison.version_mismatches == [
        {
            "name": "CG Use Everywhere",
            "expected": "7.8.0",
            "actual": "7.7",
        }
    ]


def test_rename_detection_with_dev_node_and_git_repo(status_scanner, tmp_path):
    """Detect potential rename when missing dev node and extra git repo."""
    # Create a git repo in custom_nodes
    custom_nodes = tmp_path / "ComfyUI" / "custom_nodes"
    extra_node = custom_nodes / "node-b"
    extra_node.mkdir()
    git_dir = extra_node / ".git"
    git_dir.mkdir()

    current = EnvironmentState(
        custom_nodes={'node-b': NodeState(name='node-b', path=extra_node)},
        packages={},
        python_version='3.11'
    )
    expected = EnvironmentState(
        custom_nodes={'node-a': NodeState(name='node-a', path=Path('node-a'), source='development')},
        packages={},
        python_version='3.11'
    )

    comparison = status_scanner.compare_states(current, expected)
    assert comparison.potential_dev_rename


def test_no_rename_detection_when_extra_is_not_git_repo(status_scanner, tmp_path):
    """No rename warning when extra node is not a git repo."""
    # Create a regular directory (no .git)
    custom_nodes = tmp_path / "ComfyUI" / "custom_nodes"
    extra_node = custom_nodes / "node-b"
    extra_node.mkdir()

    current = EnvironmentState(
        custom_nodes={'node-b': NodeState(name='node-b', path=extra_node)},
        packages={},
        python_version='3.11'
    )
    expected = EnvironmentState(
        custom_nodes={'node-a': NodeState(name='node-a', path=Path('node-a'), source='development')},
        packages={},
        python_version='3.11'
    )

    comparison = status_scanner.compare_states(current, expected)
    assert not comparison.potential_dev_rename
