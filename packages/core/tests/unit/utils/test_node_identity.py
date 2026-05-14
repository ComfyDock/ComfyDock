"""Tests for installed custom node identity aliases."""

from comfygit_core.models.shared import NodeInfo
from comfygit_core.utils.node_identity import (
    build_installed_node_aliases,
    resolve_installed_node_alias,
)


def test_exact_installed_node_alias_resolves_to_manifest_key():
    installed = {
        "comfyui-deforum": NodeInfo(
            name="ComfyUI-Deforum",
            registry_id="comfyui-deforum",
            repository="https://github.com/deforum/deforum-comfy-nodes.git",
            source="development",
        )
    }

    assert resolve_installed_node_alias("ComfyUI-Deforum", installed) == "comfyui-deforum"
    assert resolve_installed_node_alias("comfyui-deforum", installed) == "comfyui-deforum"
    assert (
        resolve_installed_node_alias("https://github.com/deforum/deforum-comfy-nodes", installed)
        == "comfyui-deforum"
    )


def test_ambiguous_alias_is_not_resolved():
    installed = {
        "package-a": NodeInfo(name="SharedName", source="development"),
        "package-b": NodeInfo(name="SharedName", source="development"),
    }

    aliases = build_installed_node_aliases(installed)

    assert "SharedName" not in aliases
    assert resolve_installed_node_alias("SharedName", installed, aliases) is None
    assert resolve_installed_node_alias("package-a", installed, aliases) == "package-a"


def test_alias_matching_is_case_sensitive():
    installed = {
        "comfyui-deforum": NodeInfo(name="ComfyUI-Deforum", source="development"),
    }

    assert resolve_installed_node_alias("ComfyUI-Deforum", installed) == "comfyui-deforum"
    assert resolve_installed_node_alias("comfyui-deforum", installed) == "comfyui-deforum"
    assert resolve_installed_node_alias("COMFYUI-DEFORUM", installed) is None
