"""End-to-end integration test for requirements.txt inline comments bug.

BUG: facerestore_cf node has 'gdown # supports downloading...' which caused
UV to reject the pyproject.toml with PEP 508 validation error during resolution testing.

This integration test validates the complete fix works through the entire pipeline:
CustomNodeScanner -> NodeManager -> ResolutionTester -> UV validation

Unit tests for the actual parsing logic are in: tests/unit/analyzers/test_custom_node_scanner.py
"""
from unittest.mock import patch

from comfygit_core.models.shared import NodeInfo


def test_node_with_inline_comments_installs_successfully(test_env):
    """End-to-end test: Node with inline comments in requirements.txt installs successfully.

    This reproduces the exact facerestore_cf scenario:
    - requirements.txt has inline comments like 'gdown # supports downloading...'
    - Scanner strips the comments before passing to resolution tester
    - UV validates the clean PEP 508 requirements
    - Node installs successfully through the entire pipeline

    Without the fix, this test would fail with:
        configuration error: `project.dependencies[X]` must be pep508
    """
    mock_node_info = NodeInfo(
        name="facerestore-test",
        registry_id="facerestore-test",
        source="registry",
        version="1.0.0",
        download_url="https://example.com/node.zip"
    )

    # Create a cached node with requirements.txt that has inline comments
    cache_node = test_env.workspace_paths.cache / "custom_nodes" / "store" / "facerestore-hash" / "content"
    cache_node.mkdir(parents=True, exist_ok=True)
    (cache_node / "__init__.py").write_text("# Test node")

    # Replicate facerestore_cf requirements with inline comments
    requirements_content = """numpy>=1.20.0
opencv-python>=4.5.0
# Full line comment should be ignored
gdown # supports downloading the large file from Google Drive
requests>=2.25.0  # For API calls
pillow  # Image processing
"""
    (cache_node / "requirements.txt").write_text(requirements_content)

    with patch.object(test_env.node_manager.node_lookup, 'get_node', return_value=mock_node_info), \
         patch.object(test_env.node_manager.node_lookup, 'download_to_cache', return_value=cache_node):

        # This should succeed - inline comments are stripped before UV validation
        result = test_env.node_manager.add_node("facerestore-test", no_test=False)

        # Verify node installed successfully through entire pipeline
        assert result.name == "facerestore-test"

        existing_nodes = test_env.node_manager.pyproject.nodes.get_existing()
        assert "facerestore-test" in existing_nodes

        node_path = test_env.comfyui_path / "custom_nodes" / "facerestore-test"
        assert node_path.exists()
