"""Global node mappings table dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field

""" example mappings:
"mappings": {
    "(Down)Load Hibiki Model::_": {
        "package_id": "comfyui-hibiki",
        "versions": [
            "1.0.0"
        ]
    },
    "(Down)Load Kokoro Model::_": {
        "package_id": "comfyui-jhj-kokoro-onnx",
        "versions": [],
        "source": "manager"
    },
    "Test::_": [ # TODO: Multiple mappings possible for same node type, order by downloads/stars
        {
            "package_id": "comfyui-jhj-kokoro-onnx",
            "versions": [...],
            "source": "registry",
            "rank": 1
        },
        {
            "package_id": "comfyui-some-node",
            "versions": [...],
            "source": "manager",
            "rank": 2
        },
        ...
    ],
"""


@dataclass
class PackageMapping:
    """Single package mapping entry within a node key."""
    package_id: str
    versions: list[str]
    rank: int  # 1-based popularity ranking
    source: str | None = None  # "manager" or None (Registry default)


@dataclass
class GlobalNodeMapping:
    """Mapping from node type to list of package options (ranked)."""

    id: str  # Compound key (e.g. "NodeType::<input list hash>")
    packages: list[PackageMapping]  # List of package options, ranked by popularity


""" example package:
"comfyui-hibiki": {
    "display_name": "ComfyUI-hibiki",
    "author": "",
    "description": "ComfyUI wrapper for Speech-to-Speech translation, hibiki: https://github.com/kyutai-labs/hibiki",
    "repository": "https://github.com/jhj0517/ComfyUI-hibiki.git",
    "downloads": 909,
    "github_stars": 0,
    "rating": 0,
    "license": "{\"file\": \"LICENSE\"}",
    "category": "",
    "tags": [],
    "status": "NodeStatusActive",
    "created_at": "2025-02-09T12:51:54.479852Z",
    "versions": {
        "1.0.0": {
            "version": "1.0.0",
            "changelog": "",
            "release_date": "2025-02-09T12:51:54.912872Z",
            "dependencies": [
                "git+https://github.com/jhj0517/moshi_comfyui_wrapper.git@main#subdirectory=moshi"
            ],
            "deprecated": false,
            "download_url": "https://cdn.comfy.org/jhj0517/comfyui-hibiki/1.0.0/node.zip",
            "status": "NodeVersionStatusFlagged",
            "supported_accelerators": null,
            "supported_comfyui_version": "",
            "supported_os": null
        }
    }
},
...
"github_zzw5516_comfyui-zw-tools": {
    "display_name": "comfyui-zw-tools",
    "author": "zzw5516",
    "description": "",
    "repository": "https://github.com/zzw5516/ComfyUI-zw-tools",
    "synthetic": true,
    "source": "manager",
    "versions": {}
}
"""

@dataclass
class GlobalNodePackageVersion:
    """Package version data."""
    version: str  # Version (required)
    # Core fields used by CLI
    download_url: str | None = None  # Download URL
    deprecated: bool | None = None  # Deprecated
    dependencies: list[str] | None = None  # Dependencies
    # Unused fields (kept for potential future use, omitted from minimal schema)
    changelog: str | None = None  # Changelog
    release_date: str | None = None  # Release date
    status: str | None = None  # Status
    supported_accelerators: list[str] | None = None  # Supported accelerators
    supported_comfyui_version: str | None = None  # Supported ComfyUI version
    supported_os: list[str] | None = None  # Supported OS

    def __repr__(self) -> str:
        """Concise representation showing version and key flags."""
        parts = [f"v{self.version}"]
        if self.deprecated:
            parts.append("deprecated")
        if self.dependencies:
            parts.append(f"{len(self.dependencies)} deps")
        return f"GlobalNodePackageVersion({', '.join(parts)})"

@dataclass
class GlobalNodePackage:
    """Global standard package data."""

    id: str  # Package ID (required)
    # Core fields used by CLI
    display_name: str | None = None  # Display name
    description: str | None = None  # Description
    repository: str | None = None  # Repository
    github_stars: int | None = None  # GitHub stars
    versions: dict[str, GlobalNodePackageVersion] | None = None  # Versions
    source: str | None = None  # Source of the package (None = Registry, "manager" = Manager-only)
    # Unused fields (kept for potential future use, omitted from minimal schema)
    author: str | None = None  # Author
    downloads: int | None = None  # Downloads
    rating: int | None = None  # Rating
    license: str | None = None  # License
    category: str | None = None  # Category
    icon: str | None = None  # Icon URL
    tags: list[str] | None = None  # Tags
    status: str | None = None  # Status
    created_at: str | None = None  # Created at

    def __repr__(self) -> str:
        """Concise representation showing key package info and version list."""
        version_str = ""
        if self.versions:
            version_list = list(self.versions.keys())
            if len(version_list) <= 3:
                version_str = f", versions=[{', '.join(version_list)}]"
            else:
                version_str = f", versions=[{', '.join(version_list[:3])}, ... +{len(version_list) - 3} more]"

        repo_short = ""
        if self.repository:
            # Extract just the repo name from URL
            repo_parts = self.repository.rstrip('/').split('/')
            repo_short = f", repo={repo_parts[-1] if repo_parts else self.repository}"

        return f"GlobalNodePackage(id={self.id!r}{repo_short}{version_str})"


""" example full mappings file:
"version": "2025.09.19",
"generated_at": "2025-09-19T18:25:18.347947",
"stats": {
    "packages": 3398,
    "signatures": 34049,
    "total_nodes": 15280,
    "augmented": true,
    "augmentation_date": "2025-09-19T18:26:03.820776",
    "nodes_from_manager": 19402,
    "synthetic_packages": 485
},
"mappings": {...},
"packages": {...},
"""


@dataclass
class GlobalNodeMappingsStats:
    packages: int | None = None
    signatures: int | None = None
    total_nodes: int | None = None
    augmented: bool | None = None
    augmentation_date: str | None = None
    nodes_from_manager: int | None = None
    manager_packages: int | None = None


@dataclass
class GlobalNodeMappings:
    """Global node mappings table."""

    version: str
    generated_at: str
    stats: GlobalNodeMappingsStats | None
    mappings: dict[str, GlobalNodeMapping] = field(default_factory=dict)
    packages: dict[str, GlobalNodePackage] = field(default_factory=dict)
    package_aliases: dict[str, str] = field(default_factory=dict)
