"""Tests for unmanaged current-environment import scanning and copying."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from comfygit_core.imports import (
    UnmanagedDevelopmentNodeLink,
)
from comfygit_core.imports import (
    import_unmanaged_comfyui_environment as import_current_environment,
)
from comfygit_core.imports import (
    scan_unmanaged_comfyui as scan_current_environment,
)


class FakeEnvironment:
    def __init__(self, path: Path, name: str = "imported") -> None:
        self.name = name
        self.comfyui_path = path / "ComfyUI"
        self.cec_path = path / ".cec"
        self.comfyui_path.mkdir(parents=True)
        self.cec_path.mkdir(parents=True)
        self.linked_nodes: list[tuple[str, Path]] = []
        self.added_nodes: list[str] = []
        self.resolved_workflows: list[str] = []
        self.invalidated_workflows: list[str] = []

    def add_node(self, identifier: str, **kwargs):
        self.added_nodes.append(identifier)
        node_name = identifier.split("@", 1)[0].rstrip("/").split("/")[-1].removesuffix(".git")
        node_path = self.comfyui_path / "custom_nodes" / node_name
        node_path.mkdir(parents=True, exist_ok=True)
        return None

    def link_development_node(self, identifier: str, source_path: Path, **kwargs) -> None:
        self.linked_nodes.append((identifier, source_path))

    def copy_workflows_to_manifest(self):
        source_dir = self.comfyui_path / "user" / "default" / "workflows"
        dest_dir = self.cec_path / "workflows"
        dest_dir.mkdir(parents=True, exist_ok=True)
        results = {}
        for source in source_dir.glob("*.json"):
            dest = dest_dir / source.name
            dest.write_text(source.read_text())
            results[source.stem] = dest
        return results

    def invalidate_workflow_resolution_cache(self, workflow_name: str) -> None:
        self.invalidated_workflows.append(workflow_name)

    def resolve_workflow(self, name: str, fix: bool = True):
        self.resolved_workflows.append(name)
        return None


class FakeWorkspace:
    def __init__(self, path: Path, node_mapping_repository=None) -> None:
        self.path = path
        self.created: dict | None = None
        self.environment = FakeEnvironment(path)
        self.node_mapping_repository = node_mapping_repository

    def create_environment(self, **kwargs):
        self.created = kwargs
        return self.environment


class FakeCallbacks:
    def __init__(self) -> None:
        self.phases: list[tuple[str, str]] = []
        self.logs: list[str] = []
        self.errors: list[str] = []
        self.workflows: list[str] = []
        self.nodes: list[str] = []

    def on_phase(self, phase: str, description: str) -> None:
        self.phases.append((phase, description))

    def on_log(self, message: str) -> None:
        self.logs.append(message)

    def on_error(self, error: str) -> None:
        self.errors.append(error)

    def on_workflow_copied(self, workflow_name: str) -> None:
        self.workflows.append(workflow_name)

    def on_node_installed(self, node_name: str) -> None:
        self.nodes.append(node_name)


class FakeRegistryVersion:
    def __init__(self, version: str, download_url: str = "https://example.com/node.zip") -> None:
        self.version = version
        self.download_url = download_url
        self.deprecated = False


class FakeRegistryPackage:
    def __init__(self, package_id: str, repository: str | None, versions: list[str]) -> None:
        self.id = package_id
        self.repository = repository
        self.versions = {version: FakeRegistryVersion(version) for version in versions}


class FakeNodeRegistryLookup:
    def __init__(self, packages: list[FakeRegistryPackage]) -> None:
        self.packages = {package.id: package for package in packages}

    def get_package(self, package_id: str):
        return self.packages.get(package_id.lower())

    def resolve_github_url(self, github_url: str):
        normalized = github_url.lower().removesuffix(".git")
        for package in self.packages.values():
            if package.repository and package.repository.lower().removesuffix(".git") == normalized:
                return package
        return None


def test_scan_current_environment_reports_workflows_and_nodes(tmp_path: Path) -> None:
    source = _make_comfyui_source(tmp_path / "source")
    _make_git_node(source / "custom_nodes" / "git-node")
    _make_local_node(source / "custom_nodes" / "local-node")

    preview = scan_current_environment(source)

    assert preview.source_path == str(source)
    assert preview.total_workflows == 1
    assert preview.workflows[0].name == "demo"

    nodes = {node.name: node for node in preview.custom_nodes}
    assert nodes["git-node"].source_type == "git"
    assert nodes["git-node"].repository == "https://github.com/example/git-node.git"
    assert nodes["git-node"].pinned_commit
    assert nodes["local-node"].source_type == "local"
    assert "manual provenance review" in " ".join(preview.warnings)


def test_scan_current_environment_reads_comfyui_version_file(tmp_path: Path) -> None:
    source = _make_comfyui_source(tmp_path / "source")
    (source / "comfyui_version.py").write_text('__version__ = "0.22.0"\n')

    preview = scan_current_environment(source)

    assert preview.comfyui_version == "0.22.0"


def test_import_current_environment_normalizes_bare_comfyui_release_tag(tmp_path: Path) -> None:
    source = _make_comfyui_source(tmp_path / "source")
    (source / "comfyui_version.py").write_text('__version__ = "0.22.0"\n')
    workspace = FakeWorkspace(tmp_path / "workspace")

    import_current_environment(
        workspace,
        name="managed-copy",
        source_path=source,
        torch_backend="cpu",
    )

    assert workspace.created is not None
    assert workspace.created["comfyui_version"] == "v0.22.0"


def test_scan_current_environment_reads_pyproject_version_when_version_file_missing(tmp_path: Path) -> None:
    source = _make_comfyui_source(tmp_path / "source")
    (source / "pyproject.toml").write_text(
        "\n".join([
            "[project]",
            'name = "comfyui"',
            'version = "0.21.3"',
            "",
        ])
    )

    preview = scan_current_environment(source)

    assert preview.comfyui_version == "0.21.3"


def test_scan_current_environment_reports_workflow_model_references(tmp_path: Path) -> None:
    source = _make_comfyui_source(tmp_path / "source")
    workflow_path = source / "user" / "default" / "workflows" / "demo.json"
    workflow_path.write_text(json.dumps({
        "nodes": [
            {
                "id": 1,
                "type": "CheckpointLoaderSimple",
                "widgets_values": ["sdxl_base.safetensors"],
                "inputs": [
                    {
                        "name": "ckpt_name",
                        "type": "COMBO",
                        "widget": {"name": "ckpt_name"},
                    }
                ],
            },
            {
                "id": 2,
                "type": "VAELoader",
                "properties": {
                    "models": [
                        {
                            "name": "vae-ft-mse.safetensors",
                            "directory": "vae",
                            "url": "https://huggingface.co/example/vae/resolve/main/vae-ft-mse.safetensors",
                        }
                    ]
                },
                "widgets_values": ["vae-ft-mse.safetensors"],
            },
        ],
        "links": [],
    }))

    preview = scan_current_environment(source)

    assert preview.models_scanned is True
    assert preview.total_model_references == 2
    assert preview.workflows[0].models_required == 2

    refs = {ref.filename: ref for ref in preview.model_references}
    assert refs["sdxl_base.safetensors"].category == "checkpoints"
    assert refs["sdxl_base.safetensors"].node_type == "CheckpointLoaderSimple"
    assert refs["vae-ft-mse.safetensors"].category == "vae"
    assert refs["vae-ft-mse.safetensors"].source_url == "https://huggingface.co/example/vae/resolve/main/vae-ft-mse.safetensors"


def test_scan_current_environment_uses_source_model_loader_metadata(tmp_path: Path) -> None:
    source = _make_comfyui_source(tmp_path / "source")
    (source / "folder_paths.py").write_text(
        "\n".join([
            "import os",
            'models_dir = "models"',
            "folder_names_and_paths = {}",
            "supported_pt_extensions = set()",
            'folder_names_and_paths["diffusion_models"] = ([os.path.join(models_dir, "diffusion_models")], supported_pt_extensions)',
            "",
        ])
    )
    (source / "nodes.py").write_text(
        "\n".join([
            "import folder_paths",
            "",
            "class QwenGGUFLoader:",
            "    @classmethod",
            "    def INPUT_TYPES(cls):",
            "        return {",
            "            'required': {",
            "                'gguf_name': (folder_paths.get_filename_list('diffusion_models'),),",
            "            }",
            "        }",
            "",
            'NODE_CLASS_MAPPINGS = {"QwenGGUFLoader": QwenGGUFLoader}',
            "",
        ])
    )
    workflow_path = source / "user" / "default" / "workflows" / "demo.json"
    workflow_path.write_text(json.dumps({
        "nodes": [
            {
                "id": 1,
                "type": "QwenGGUFLoader",
                "widgets_values": ["qwen-image-edit.gguf"],
            }
        ],
        "links": [],
    }))

    preview = scan_current_environment(source)

    assert preview.models_scanned is True
    assert preview.total_model_references == 1
    ref = preview.model_references[0]
    assert ref.filename == "qwen-image-edit.gguf"
    assert ref.node_type == "QwenGGUFLoader"
    assert ref.category == "diffusion_models"


def test_scan_current_environment_does_not_inherit_parent_comfyui_git_remote(tmp_path: Path) -> None:
    source = _make_comfyui_source(tmp_path / "source")
    _make_local_node(source / "custom_nodes" / "nested-node")
    _git(source, "init")
    _git(source, "config", "user.email", "test@example.com")
    _git(source, "config", "user.name", "Test User")
    _git(source, "remote", "add", "origin", "https://github.com/comfyanonymous/ComfyUI.git")
    _git(source, "add", "main.py")
    _git(source, "commit", "-m", "comfyui")

    preview = scan_current_environment(source)

    nodes = {node.name: node for node in preview.custom_nodes}
    assert nodes["nested-node"].source_type == "local"
    assert nodes["nested-node"].repository is None


def test_scan_current_environment_uses_pyproject_registry_provenance(tmp_path: Path) -> None:
    source = _make_comfyui_source(tmp_path / "source")
    node = source / "custom_nodes" / "ComfyUI-KJNodes"
    _make_pyproject_node(
        node,
        project_name="comfyui-kjnodes",
        version="1.4.1",
        repository="https://github.com/kijai/ComfyUI-KJNodes",
        display_name="ComfyUI-KJNodes",
    )
    registry = FakeNodeRegistryLookup([
        FakeRegistryPackage(
            "comfyui-kjnodes",
            "https://github.com/kijai/comfyui-kjnodes",
            ["1.4.0", "1.4.1"],
        )
    ])

    preview = scan_current_environment(source, node_registry_lookup=registry)

    scanned = {node.name: node for node in preview.custom_nodes}["ComfyUI-KJNodes"]
    assert scanned.source_type == "registry"
    assert scanned.registry_id == "comfyui-kjnodes"
    assert scanned.version == "1.4.1"
    assert scanned.install_spec == "comfyui-kjnodes@1.4.1"
    assert scanned.warning is None


def test_scan_current_environment_uses_pyproject_repository_when_registry_version_missing(tmp_path: Path) -> None:
    source = _make_comfyui_source(tmp_path / "source")
    node = source / "custom_nodes" / "ComfyUI-KJNodes"
    _make_pyproject_node(
        node,
        project_name="comfyui-kjnodes",
        version="1.4.1",
        repository="https://github.com/kijai/ComfyUI-KJNodes",
        display_name="ComfyUI-KJNodes",
    )
    registry = FakeNodeRegistryLookup([
        FakeRegistryPackage(
            "comfyui-kjnodes",
            "https://github.com/kijai/comfyui-kjnodes",
            ["1.4.0"],
        )
    ])

    preview = scan_current_environment(source, node_registry_lookup=registry)

    scanned = {node.name: node for node in preview.custom_nodes}["ComfyUI-KJNodes"]
    assert scanned.source_type == "git"
    assert scanned.install_spec == "https://github.com/kijai/ComfyUI-KJNodes"
    assert "no matching registry version" in " ".join(preview.warnings)


def test_import_current_environment_creates_managed_copy(tmp_path: Path) -> None:
    source = _make_comfyui_source(tmp_path / "source")
    _make_local_node(source / "custom_nodes" / "local-node")
    workspace = FakeWorkspace(tmp_path / "workspace")

    result = import_current_environment(
        workspace,
        name="managed-copy",
        source_path=source,
        torch_backend="cpu",
    )

    assert workspace.created == {
        "name": "managed-copy",
        "python_version": result_python_minor(),
        "comfyui_version": None,
        "torch_backend": "cpu",
    }
    assert result.environment_name == "imported"
    assert result.workflows_copied == 1
    assert result.custom_nodes_copied == 1

    copied_workflow = workspace.environment.comfyui_path / "user" / "default" / "workflows" / "demo.json"
    copied_node = workspace.environment.comfyui_path / "custom_nodes" / "local-node"
    assert copied_workflow.exists()
    assert (workspace.environment.cec_path / "workflows" / "demo.json").exists()
    assert copied_node.exists()
    assert workspace.environment.linked_nodes == [("local-node", copied_node)]
    assert workspace.environment.invalidated_workflows == ["demo"]
    assert workspace.environment.resolved_workflows == ["demo"]

    # The unmanaged source remains in place.
    assert (source / "user" / "default" / "workflows" / "demo.json").exists()
    assert (source / "custom_nodes" / "local-node").exists()


def test_import_current_environment_tracks_symlinked_manager_as_dev_node(tmp_path: Path) -> None:
    source = _make_comfyui_source(tmp_path / "source")
    manager_repo = tmp_path / "manager-repo"
    _make_local_node(manager_repo)
    (source / "custom_nodes" / "comfygit-manager").symlink_to(
        manager_repo,
        target_is_directory=True,
    )
    workspace = FakeWorkspace(tmp_path / "workspace")

    result = import_current_environment(
        workspace,
        name="managed-copy",
        source_path=source,
        torch_backend="cpu",
        ignored_custom_node_names=("comfygit-manager",),
        development_node_links=(
            UnmanagedDevelopmentNodeLink(
                identifier="comfygit-manager",
                source_path=manager_repo.resolve(),
                name="comfygit-manager",
            ),
        ),
    )

    assert result.custom_nodes_copied == 0
    assert workspace.environment.linked_nodes == [
        ("comfygit-manager", manager_repo.resolve()),
    ]


def test_import_current_environment_forwards_create_progress_and_logs(tmp_path: Path) -> None:
    source = _make_comfyui_source(tmp_path / "source")
    workspace = FakeWorkspace(tmp_path / "workspace")
    callbacks = FakeCallbacks()

    import_current_environment(
        workspace,
        name="managed-copy",
        source_path=source,
        torch_backend="cpu",
        callbacks=callbacks,
    )

    assert workspace.created is not None
    progress = workspace.created["progress"]
    progress.on_phase("install_dependencies", "Installing dependencies", 40)
    progress.on_log("Downloading torch (1.1GiB)")

    assert ("install_dependencies", "Installing dependencies") in callbacks.phases
    assert "Downloading torch (1.1GiB)" in callbacks.logs


def test_import_current_environment_installs_registry_nodes_and_tracks_workflows(tmp_path: Path) -> None:
    source = _make_comfyui_source(tmp_path / "source")
    _make_pyproject_node(
        source / "custom_nodes" / "ComfyUI-KJNodes",
        project_name="comfyui-kjnodes",
        version="1.4.1",
        repository="https://github.com/kijai/ComfyUI-KJNodes",
        display_name="ComfyUI-KJNodes",
    )
    registry = FakeNodeRegistryLookup([
        FakeRegistryPackage(
            "comfyui-kjnodes",
            "https://github.com/kijai/comfyui-kjnodes",
            ["1.4.1"],
        )
    ])
    workspace = FakeWorkspace(tmp_path / "workspace", node_mapping_repository=registry)

    result = import_current_environment(
        workspace,
        name="managed-copy",
        source_path=source,
        torch_backend="cpu",
    )

    assert result.workflows_copied == 1
    assert result.custom_nodes_copied == 1
    assert workspace.environment.added_nodes == ["comfyui-kjnodes@1.4.1"]
    assert workspace.environment.linked_nodes == []
    assert (workspace.environment.cec_path / "workflows" / "demo.json").exists()


def _make_comfyui_source(path: Path) -> Path:
    (path / "user" / "default" / "workflows").mkdir(parents=True)
    (path / "custom_nodes").mkdir(parents=True)
    (path / "main.py").write_text("print('comfyui')\n")
    (path / "user" / "default" / "workflows" / "demo.json").write_text(json.dumps({"nodes": []}))
    return path


def _make_local_node(path: Path) -> None:
    path.mkdir(parents=True)
    (path / "__init__.py").write_text("")


def _make_pyproject_node(
    path: Path,
    *,
    project_name: str,
    version: str,
    repository: str,
    display_name: str,
) -> None:
    _make_local_node(path)
    (path / "pyproject.toml").write_text(
        "\n".join([
            "[project]",
            f'name = "{project_name}"',
            f'version = "{version}"',
            "",
            "[project.urls]",
            f'Repository = "{repository}"',
            "",
            "[tool.comfy]",
            f'DisplayName = "{display_name}"',
            'PublisherId = "kijai"',
            "",
        ])
    )


def _make_git_node(path: Path) -> None:
    _make_local_node(path)
    _git(path, "init")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test User")
    _git(path, "remote", "add", "origin", "https://github.com/example/git-node.git")
    _git(path, "add", "__init__.py")
    _git(path, "commit", "-m", "init")


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def result_python_minor() -> str:
    import sys

    return f"{sys.version_info.major}.{sys.version_info.minor}"
