"""Integration tests for node prune functionality.

Tests that the prune command correctly identifies and removes nodes that are
installed but not referenced by any workflow.
"""


from helpers.workflow_builder import WorkflowBuilder


class TestNodePrune:
    """Test node prune identifies and removes unused nodes."""

    def test_prune_finds_unused_node(self, test_env):
        """Prune should detect node not referenced by any workflow.

        Scenario:
        1. Install 3 nodes
        2. Create workflow that uses 2 nodes (with custom_node_map)
        3. Prune should find 1 unused node
        """
        # ARRANGE: Install 3 nodes manually
        config = test_env.pyproject.load()
        config['tool']['comfygit']['nodes'] = {
            'node-a': {'type': 'git', 'url': 'https://github.com/user/node-a'},
            'node-b': {'type': 'git', 'url': 'https://github.com/user/node-b'},
            'node-c': {'type': 'git', 'url': 'https://github.com/user/node-c'}
        }
        test_env.pyproject.save(config)

        # Create filesystem directories for all nodes
        for node_id in ['node-a', 'node-b', 'node-c']:
            node_path = test_env.custom_nodes_path / node_id
            node_path.mkdir(parents=True, exist_ok=True)
            (node_path / ".git").mkdir()
            (node_path / ".git" / "config").write_text("[core]\n")

        # Create workflow with 2 custom nodes
        workflow = (
            WorkflowBuilder()
            .add_custom_node("NodeTypeA")
            .add_custom_node("NodeTypeB")
            .build()
        )

        workflow_path = test_env.comfyui_path / "user" / "default" / "workflows" / "test.json"
        import json
        with open(workflow_path, 'w') as f:
            json.dump(workflow, f)

        # Register workflow with custom_node_map that resolves to node-a and node-b
        # This simulates what happens after resolution
        config = test_env.pyproject.load()
        config['tool']['comfygit']['workflows'] = {
            'test': {
                'nodes': ['node-a', 'node-b'],
                'custom_node_map': {
                    'NodeTypeA': 'node-a',
                    'NodeTypeB': 'node-b'
                }
            }
        }
        test_env.pyproject.save(config)

        # ACT: Get unused nodes
        unused = test_env.get_unused_nodes()

        # ASSERT: Should find node-c as unused
        assert len(unused) == 1, f"Expected 1 unused node, found {len(unused)}: {[n.name for n in unused]}"
        unused_ids = [node.registry_id or node.name for node in unused]
        assert 'node-c' in unused_ids, f"Expected node-c to be unused, got {unused_ids}"
        assert 'node-a' not in unused_ids, "node-a should not be unused (used by workflow)"
        assert 'node-b' not in unused_ids, "node-b should not be unused (used by workflow)"

    def test_prune_when_no_workflows(self, test_env):
        """All installed nodes should be considered unused when no workflows exist."""
        # ARRANGE: Install nodes but no workflows
        config = test_env.pyproject.load()
        config['tool']['comfygit']['nodes'] = {
            'orphan-node': {'type': 'git', 'url': 'https://github.com/user/orphan'}
        }
        test_env.pyproject.save(config)

        node_path = test_env.custom_nodes_path / "orphan-node"
        node_path.mkdir(parents=True, exist_ok=True)
        (node_path / ".git").mkdir()
        (node_path / ".git" / "config").write_text("[core]\n")

        # ACT
        unused = test_env.get_unused_nodes()

        # ASSERT
        assert len(unused) == 1
        assert (unused[0].registry_id or unused[0].name) == 'orphan-node'

    def test_prune_respects_shared_nodes_across_workflows(self, test_env):
        """Node used by multiple workflows should NOT be marked unused."""
        # ARRANGE: Install nodes
        config = test_env.pyproject.load()
        config['tool']['comfygit']['nodes'] = {
            'shared-node': {'type': 'git', 'url': 'https://github.com/user/shared'},
            'workflow1-only': {'type': 'git', 'url': 'https://github.com/user/wf1'},
            'workflow2-only': {'type': 'git', 'url': 'https://github.com/user/wf2'},
            'unused-node': {'type': 'git', 'url': 'https://github.com/user/unused'}
        }
        test_env.pyproject.save(config)

        for node_id in ['shared-node', 'workflow1-only', 'workflow2-only', 'unused-node']:
            node_path = test_env.custom_nodes_path / node_id
            node_path.mkdir(parents=True, exist_ok=True)
            (node_path / ".git").mkdir()
            (node_path / ".git" / "config").write_text("[core]\n")

        # Create two workflows with shared node
        import json
        for wf_name, node_types in [('wf1', ['SharedNode', 'Wf1Node']), ('wf2', ['SharedNode', 'Wf2Node'])]:
            builder = WorkflowBuilder()
            for node_type in node_types:
                builder.add_custom_node(node_type)
            workflow = builder.build()

            workflow_path = test_env.comfyui_path / "user" / "default" / "workflows" / f"{wf_name}.json"
            with open(workflow_path, 'w') as f:
                json.dump(workflow, f)

        # Register workflows with custom_node_map
        config = test_env.pyproject.load()
        config['tool']['comfygit']['workflows'] = {
            'wf1': {
                'nodes': ['shared-node', 'workflow1-only'],
                'custom_node_map': {
                    'SharedNode': 'shared-node',
                    'Wf1Node': 'workflow1-only'
                }
            },
            'wf2': {
                'nodes': ['shared-node', 'workflow2-only'],
                'custom_node_map': {
                    'SharedNode': 'shared-node',
                    'Wf2Node': 'workflow2-only'
                }
            }
        }
        test_env.pyproject.save(config)

        # ACT
        unused = test_env.get_unused_nodes()

        # ASSERT: Only unused-node should be detected
        assert len(unused) == 1
        assert (unused[0].registry_id or unused[0].name) == 'unused-node'

    def test_prune_respects_custom_node_map(self, test_env):
        """Node in workflow's custom_node_map should NOT be marked unused."""
        # ARRANGE: Install nodes
        config = test_env.pyproject.load()
        config['tool']['comfygit']['nodes'] = {
            'custom-mapped': {'type': 'git', 'url': 'https://github.com/user/custom'},
            'truly-unused': {'type': 'git', 'url': 'https://github.com/user/unused'}
        }
        test_env.pyproject.save(config)

        for node_id in ['custom-mapped', 'truly-unused']:
            node_path = test_env.custom_nodes_path / node_id
            node_path.mkdir(parents=True, exist_ok=True)
            (node_path / ".git").mkdir()
            (node_path / ".git" / "config").write_text("[core]\n")

        # Create workflow with custom mapping
        workflow = WorkflowBuilder().add_custom_node("CustomNode").build()
        workflow_path = test_env.comfyui_path / "user" / "default" / "workflows" / "test.json"
        import json
        with open(workflow_path, 'w') as f:
            json.dump(workflow, f)

        # Register workflow with custom_node_map (but empty nodes list to test mapping detection)
        config = test_env.pyproject.load()
        config['tool']['comfygit']['workflows'] = {
            'test': {
                'nodes': [],  # Empty - we're testing that custom_node_map is respected
                'custom_node_map': {
                    'CustomNode': 'custom-mapped'
                }
            }
        }
        test_env.pyproject.save(config)

        # ACT
        unused = test_env.get_unused_nodes()

        # ASSERT: Only truly-unused should be detected
        # Note: This test will initially fail because we need to implement resolution awareness
        assert len(unused) == 1, f"Expected 1 unused, got {len(unused)}"
        assert (unused[0].registry_id or unused[0].name) == 'truly-unused'

    def test_prune_excludes_optional_nodes_from_needed(self, test_env):
        """Optional nodes (custom_node_map = false) should be prunable."""
        # ARRANGE: Install nodes
        config = test_env.pyproject.load()
        config['tool']['comfygit']['nodes'] = {
            'optional-node': {'type': 'git', 'url': 'https://github.com/user/optional'},
            'required-node': {'type': 'git', 'url': 'https://github.com/user/required'}
        }
        test_env.pyproject.save(config)

        for node_id in ['optional-node', 'required-node']:
            node_path = test_env.custom_nodes_path / node_id
            node_path.mkdir(parents=True, exist_ok=True)
            (node_path / ".git").mkdir()
            (node_path / ".git" / "config").write_text("[core]\n")

        # Create workflow
        workflow = (
            WorkflowBuilder()
            .add_custom_node("RequiredNode")
            .add_custom_node("OptionalNode")
            .build()
        )
        workflow_path = test_env.comfyui_path / "user" / "default" / "workflows" / "test.json"
        import json
        with open(workflow_path, 'w') as f:
            json.dump(workflow, f)

        # Register workflow with optional mapping
        config = test_env.pyproject.load()
        config['tool']['comfygit']['workflows'] = {
            'test': {
                'nodes': ['required-node'],
                'custom_node_map': {
                    'RequiredNode': 'required-node',
                    'OptionalNode': False  # Marked as optional
                }
            }
        }
        test_env.pyproject.save(config)

        # ACT
        unused = test_env.get_unused_nodes()

        # ASSERT: optional-node should be prunable (even though in workflow)
        assert len(unused) == 1
        assert (unused[0].registry_id or unused[0].name) == 'optional-node'

    def test_prune_with_exclude_flag(self, test_env):
        """Exclude flag should keep specified nodes even if unused."""
        # ARRANGE: Install unused nodes
        config = test_env.pyproject.load()
        config['tool']['comfygit']['nodes'] = {
            'unused-a': {'type': 'git', 'url': 'https://github.com/user/a'},
            'unused-b': {'type': 'git', 'url': 'https://github.com/user/b'}
        }
        test_env.pyproject.save(config)

        for node_id in ['unused-a', 'unused-b']:
            node_path = test_env.custom_nodes_path / node_id
            node_path.mkdir(parents=True, exist_ok=True)
            (node_path / ".git").mkdir()
            (node_path / ".git" / "config").write_text("[core]\n")

        # ACT: Get unused with exclude
        unused = test_env.get_unused_nodes(exclude=['unused-a'])

        # ASSERT: Only unused-b should appear
        assert len(unused) == 1
        assert (unused[0].registry_id or unused[0].name) == 'unused-b'

    def test_prune_actually_removes_nodes(self, test_env):
        """prune_unused_nodes should actually remove the nodes from filesystem and pyproject."""
        # ARRANGE: Install unused node
        config = test_env.pyproject.load()
        config['tool']['comfygit']['nodes'] = {
            'will-be-pruned': {'type': 'git', 'url': 'https://github.com/user/pruned'}
        }
        test_env.pyproject.save(config)

        node_path = test_env.custom_nodes_path / "will-be-pruned"
        node_path.mkdir(parents=True, exist_ok=True)
        (node_path / ".git").mkdir()
        (node_path / ".git" / "config").write_text("[core]\n")

        # Verify node exists
        assert node_path.exists()
        assert 'will-be-pruned' in test_env.pyproject.nodes.get_existing()

        # ACT: Prune
        success_count, failed = test_env.prune_unused_nodes()

        # ASSERT: Node removed from both filesystem and pyproject
        assert success_count == 1, f"Expected 1 successful removal, got {success_count}"
        assert len(failed) == 0, f"Expected no failures, got {failed}"
        assert not node_path.exists(), "Node directory should be removed"
        assert 'will-be-pruned' not in test_env.pyproject.nodes.get_existing(), "Node should be removed from pyproject"

    def test_prune_returns_zero_when_nothing_to_prune(self, test_env):
        """prune_unused_nodes should return (0, []) when no unused nodes."""
        # ARRANGE: No nodes installed

        # ACT
        success_count, failed = test_env.prune_unused_nodes()

        # ASSERT
        assert success_count == 0
        assert len(failed) == 0
