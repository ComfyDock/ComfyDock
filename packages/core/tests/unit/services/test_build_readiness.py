"""Tests for core build-readiness dependency proof generation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from comfygit_core.build_readiness import (
    build_readiness_from_manifest_snapshot,
    build_readiness_from_pyproject_toml,
)
from comfygit_core.models import EnvironmentManifestSnapshot

NODE_SOURCE = "https://github.com/example/test-node.git"


class HashAssetCatalog:
    def __init__(self, hashes: dict[str, dict[str, Any]]) -> None:
        self.hashes = hashes

    def lookup_by_hash(
        self,
        *,
        content_hash: str,
        category: str | None = None,
    ) -> Mapping[str, Any] | None:
        return self.hashes.get(content_hash)


class SourceValidationResult:
    def __init__(
        self,
        *,
        status: str,
        detail: str,
        http_status: int | None = None,
        content_length: int | None = None,
    ) -> None:
        self.status = status
        self.detail = detail
        self.http_status = http_status
        self.content_length = content_length

    def to_dict(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "status": self.status,
                "detail": self.detail,
                "http_status": self.http_status,
                "content_length": self.content_length,
            }.items()
            if value is not None
        }


class MappingSourceValidator:
    def __init__(self, results: dict[str, SourceValidationResult]) -> None:
        self.results = results

    def validate_source(
        self,
        *,
        source: str,
        kind: str,
        metadata: Mapping[str, Any],
    ) -> SourceValidationResult:
        return self.results.get(
            source,
            SourceValidationResult(status="unverified", detail="not configured"),
        )


def _base_manifest(*, model_block: str, node_block: str | None = None) -> str:
    return f"""
[project]
name = "comfygit-env-test-env"
version = "0.1.0"
requires-python = "==3.11.*"
dependencies = ["torch", "comfygit-core"]

[tool.comfygit]
schema_version = 2
comfyui_version = "v0.19.3"
python_version = "3.11"

{node_block or '''
[tool.comfygit.nodes.test-node]
name = "test-node"
repository = "https://github.com/example/test-node.git"
version = "dev"
source = "development"
'''}

[tool.comfygit.workflows.simple_txt2img]
path = "workflows/simple_txt2img.json"

{model_block}

[tool.comfygit.workflows.simple_txt2img.execution_contract]
version = 1
default_contract = "default"

[[tool.comfygit.workflows.simple_txt2img.execution_contract.contracts.default.inputs]]
name = "prompt"
type = "string"
required = true
node_id = "6"
widget_idx = 0

[[tool.comfygit.workflows.simple_txt2img.execution_contract.contracts.default.outputs]]
name = "image"
type = "image"
node_id = "9"
selector = "primary"
"""


def _proofs_by_kind(readiness: Any, kind: str) -> list[Any]:
    return [item for item in readiness.dependency_proof if item.kind == kind]


def test_build_readiness_marks_source_resolvable_model_ready():
    readiness = build_readiness_from_pyproject_toml(
        _base_manifest(
            model_block="""
[[tool.comfygit.workflows.simple_txt2img.models]]
filename = "model.safetensors"
category = "checkpoints"
criticality = "required"
sources = ["https://huggingface.co/example/repo/resolve/main/model.safetensors"]
"""
        )
    )

    model = _proofs_by_kind(readiness, "model")[0]
    assert readiness.status == "ready"
    assert readiness.environment_name == "test-env"
    assert model.status == "available_source"
    assert model.source == "https://huggingface.co/example/repo/resolve/main/model.safetensors"
    assert readiness.workflows[0].execution_contract.input_count == 1
    assert readiness.workflows[0].execution_contract.output_count == 1


def test_build_readiness_can_verify_sources_with_injected_validator():
    source = "https://huggingface.co/example/repo/resolve/main/model.safetensors"
    validator = MappingSourceValidator(
        {
            NODE_SOURCE: SourceValidationResult(
                status="verified",
                detail="node ok",
                http_status=200,
            ),
            source: SourceValidationResult(
                status="verified",
                detail="ok",
                http_status=200,
                content_length=123,
            ),
        }
    )
    readiness = build_readiness_from_pyproject_toml(
        _base_manifest(
            model_block=f"""
[[tool.comfygit.workflows.simple_txt2img.models]]
filename = "model.safetensors"
category = "checkpoints"
criticality = "required"
sources = ["{source}"]
"""
        ),
        source_validator=validator,
    )

    model = _proofs_by_kind(readiness, "model")[0]
    assert readiness.status == "ready"
    assert model.status == "available_source"
    assert model.source_validation["status"] == "verified"
    assert model.source_validation["selected"]["http_status"] == 200


def test_build_readiness_blocks_required_model_when_source_validation_fails():
    source = "https://huggingface.co/example/repo/resolve/main/missing.safetensors"
    validator = MappingSourceValidator(
        {
            NODE_SOURCE: SourceValidationResult(
                status="verified",
                detail="node ok",
                http_status=200,
            ),
            source: SourceValidationResult(
                status="unverified",
                detail="Source URL was not found.",
                http_status=404,
            ),
        }
    )
    readiness = build_readiness_from_pyproject_toml(
        _base_manifest(
            model_block=f"""
[[tool.comfygit.workflows.simple_txt2img.models]]
filename = "missing.safetensors"
category = "checkpoints"
criticality = "required"
sources = ["{source}"]
"""
        ),
        source_validator=validator,
    )

    model = _proofs_by_kind(readiness, "model")[0]
    assert readiness.status == "blocked"
    assert model.status == "blocked_unverified"
    assert model.source_validation["attempts"][0]["http_status"] == 404
    assert "missing.safetensors" in readiness.blockers[0]


def test_build_readiness_uses_later_source_when_first_fails_validation():
    bad_source = "https://huggingface.co/example/repo/resolve/main/missing.safetensors"
    good_source = "https://huggingface.co/example/repo/resolve/main/model.safetensors"
    validator = MappingSourceValidator(
        {
            NODE_SOURCE: SourceValidationResult(
                status="verified",
                detail="node ok",
                http_status=200,
            ),
            bad_source: SourceValidationResult(
                status="unverified",
                detail="Source URL was not found.",
                http_status=404,
            ),
            good_source: SourceValidationResult(
                status="verified",
                detail="ok",
                http_status=200,
            ),
        }
    )
    readiness = build_readiness_from_pyproject_toml(
        _base_manifest(
            model_block=f"""
[[tool.comfygit.workflows.simple_txt2img.models]]
filename = "model.safetensors"
category = "checkpoints"
criticality = "required"
sources = ["{bad_source}", "{good_source}"]
"""
        ),
        source_validator=validator,
    )

    model = _proofs_by_kind(readiness, "model")[0]
    assert readiness.status == "ready"
    assert model.source == good_source
    assert [item["http_status"] for item in model.source_validation["attempts"]] == [404, 200]


def test_build_readiness_blocks_required_hash_only_model_when_cache_misses():
    readiness = build_readiness_from_pyproject_toml(
        _base_manifest(
            model_block="""
[[tool.comfygit.workflows.simple_txt2img.models]]
filename = "v1-5-pruned-emaonly-fp16.safetensors"
category = "checkpoints"
criticality = "flexible"
status = "resolved"
hash = "1fd237d4d78fa19f"

[tool.comfygit.models]
1fd237d4d78fa19f = {filename = "v1-5-pruned-emaonly-fp16.safetensors", size = 2132696762, relative_path = "checkpoints/v1-5-pruned-emaonly-fp16.safetensors", category = "checkpoints"}
"""
        )
    )

    model = _proofs_by_kind(readiness, "model")[0]
    assert readiness.status == "blocked"
    assert model.status == "blocked_missing_source"
    assert model.required is True
    assert "not present in managed cache" in model.detail


def test_build_readiness_merges_global_model_catalog_metadata_into_workflow_models():
    source = "https://huggingface.co/example/repo/resolve/main/upscaler.safetensors"
    readiness = build_readiness_from_pyproject_toml(
        _base_manifest(
            model_block=f"""
[[tool.comfygit.workflows.simple_txt2img.models]]
criticality = "required"
status = "resolved"
hash = "abc123"

[tool.comfygit.models]
abc123 = {{filename = "upscaler.safetensors", size = 995743560, relative_path = "latent_upscale_models/upscaler.safetensors", category = "unknown", sources = ["{source}"]}}
"""
        )
    )

    model = readiness.workflows[0].models[0]
    assert readiness.status == "ready"
    assert model.filename == "upscaler.safetensors"
    assert model.size_bytes == 995743560
    assert model.relative_path == "latent_upscale_models/upscaler.safetensors"
    assert model.sources == (source,)


def test_build_readiness_marks_hash_only_model_ready_when_cache_hits():
    readiness = build_readiness_from_pyproject_toml(
        _base_manifest(
            model_block="""
[[tool.comfygit.workflows.simple_txt2img.models]]
filename = "model.safetensors"
category = "checkpoints"
criticality = "required"
hash = "abc123"
"""
        ),
        asset_catalog=HashAssetCatalog({"abc123": {"asset_id": "asset-1", "storage": "cache"}}),
    )

    model = _proofs_by_kind(readiness, "model")[0]
    assert readiness.status == "ready"
    assert model.status == "available_cached"
    assert model.cache_hit == {"asset_id": "asset-1", "storage": "cache"}


def test_build_readiness_allows_optional_missing_model_without_blocking():
    readiness = build_readiness_from_pyproject_toml(
        _base_manifest(
            model_block="""
[[tool.comfygit.workflows.simple_txt2img.models]]
filename = "optional-lora.safetensors"
category = "loras"
criticality = "optional"
"""
        )
    )

    model = _proofs_by_kind(readiness, "model")[0]
    assert readiness.status == "ready"
    assert model.status == "missing_optional"
    assert "optional-lora.safetensors" in readiness.warnings[0]


def test_build_readiness_blocks_required_custom_node_without_source():
    readiness = build_readiness_from_pyproject_toml(
        _base_manifest(
            node_block="""
[tool.comfygit.nodes.local-dev-node]
name = "local-dev-node"
version = "dev"
source = "development"
""",
            model_block="""
[[tool.comfygit.workflows.simple_txt2img.models]]
filename = "model.safetensors"
category = "checkpoints"
criticality = "required"
sources = ["https://huggingface.co/example/repo/resolve/main/model.safetensors"]
""",
        )
    )

    node = _proofs_by_kind(readiness, "custom_node")[0]
    assert readiness.status == "blocked"
    assert node.status == "blocked_missing_source"
    assert "no repository" in node.detail


def test_build_readiness_warns_for_optional_custom_node_without_source():
    readiness = build_readiness_from_pyproject_toml(
        _base_manifest(
            node_block="""
[tool.comfygit.nodes.optional-node]
name = "optional-node"
version = "dev"
source = "development"
criticality = "optional"
""",
            model_block="""
[[tool.comfygit.workflows.simple_txt2img.models]]
filename = "model.safetensors"
category = "checkpoints"
criticality = "required"
sources = ["https://huggingface.co/example/repo/resolve/main/model.safetensors"]
""",
        )
    )

    node = _proofs_by_kind(readiness, "custom_node")[0]
    assert readiness.status == "ready"
    assert node.status == "missing_optional"
    assert "optional-node" in readiness.warnings[0]


def test_build_readiness_includes_python_dependency_plan_from_project_and_groups():
    readiness = build_readiness_from_pyproject_toml(
        _base_manifest(
            model_block="""
[[tool.comfygit.workflows.simple_txt2img.models]]
filename = "model.safetensors"
category = "checkpoints"
criticality = "required"
sources = ["https://huggingface.co/example/repo/resolve/main/model.safetensors"]

[dependency-groups]
comfygit-system = ["uv>=0.7"]
"""
        )
    )

    assert "torch" in readiness.python_dependencies
    assert "comfygit-core" in readiness.python_dependencies
    assert "uv>=0.7" in readiness.python_dependencies
    python_proofs = _proofs_by_kind(readiness, "python_package")
    assert {item.status for item in python_proofs} == {"available_registry"}


def test_build_readiness_blocks_local_uv_python_sources():
    readiness = build_readiness_from_pyproject_toml(
        f"""
[project]
name = "comfygit-env-test-env"
version = "0.1.0"
requires-python = "==3.11.*"
dependencies = ["local-package"]

[tool.comfygit]
schema_version = 2
comfyui_version = "v0.19.3"
python_version = "3.11"

[tool.comfygit.nodes.test-node]
name = "test-node"
repository = "{NODE_SOURCE}"
version = "dev"
source = "development"

[tool.comfygit.workflows.simple_txt2img]
path = "workflows/simple_txt2img.json"

[[tool.comfygit.workflows.simple_txt2img.models]]
filename = "model.safetensors"
category = "checkpoints"
criticality = "required"
sources = ["https://huggingface.co/example/repo/resolve/main/model.safetensors"]

[tool.uv.sources]
local-package = {{ path = "../local-package", editable = true }}
"""
    )

    local_package = [
        item
        for item in _proofs_by_kind(readiness, "python_package")
        if item.name == "local-package"
    ][0]
    assert readiness.status == "blocked"
    assert local_package.status == "blocked_incompatible"
    assert local_package.source == "../local-package"
    assert "local uv source" in local_package.detail


def test_build_readiness_classifies_remote_uv_python_sources():
    readiness = build_readiness_from_pyproject_toml(
        f"""
[project]
name = "comfygit-env-test-env"
version = "0.1.0"
requires-python = "==3.11.*"
dependencies = ["remote-package"]

[tool.comfygit]
schema_version = 2
comfyui_version = "v0.19.3"
python_version = "3.11"

[tool.comfygit.nodes.test-node]
name = "test-node"
repository = "{NODE_SOURCE}"
version = "dev"
source = "development"

[tool.comfygit.workflows.simple_txt2img]
path = "workflows/simple_txt2img.json"

[[tool.comfygit.workflows.simple_txt2img.models]]
filename = "model.safetensors"
category = "checkpoints"
criticality = "required"
sources = ["https://huggingface.co/example/repo/resolve/main/model.safetensors"]

[tool.uv.sources]
remote-package = {{ git = "https://github.com/example/remote-package.git", rev = "abc123" }}
"""
    )

    remote_package = [
        item
        for item in _proofs_by_kind(readiness, "python_package")
        if item.name == "remote-package"
    ][0]
    assert readiness.status == "ready"
    assert remote_package.status == "available_source"
    assert remote_package.source == "https://github.com/example/remote-package.git"


def test_build_readiness_blocks_local_direct_python_sources():
    readiness = build_readiness_from_pyproject_toml(
        _base_manifest(
            model_block="""
[[tool.comfygit.workflows.simple_txt2img.models]]
filename = "model.safetensors"
category = "checkpoints"
criticality = "required"
sources = ["https://huggingface.co/example/repo/resolve/main/model.safetensors"]
""",
        ).replace(
            'dependencies = ["torch", "comfygit-core"]',
            'dependencies = ["local-package @ file:///home/user/local-package"]',
        )
    )

    local_package = _proofs_by_kind(readiness, "python_package")[0]
    assert readiness.status == "blocked"
    assert local_package.status == "blocked_incompatible"
    assert local_package.source == "file:///home/user/local-package"
    assert "non-portable direct source" in local_package.detail


def test_build_readiness_can_start_from_snapshot():
    snapshot = EnvironmentManifestSnapshot.from_toml_dict(
        {
            "project": {"name": "comfygit-env-empty", "requires-python": "==3.12.*"},
            "tool": {"comfygit": {"schema_version": 2, "python_version": "3.12"}},
        }
    )

    readiness = build_readiness_from_manifest_snapshot(snapshot)

    assert readiness.environment_name == "empty"
    assert readiness.python_version == "3.12"
    assert readiness.status == "ready"
    assert "No workflows are declared" in readiness.warnings[0]


def test_build_readiness_reports_invalid_toml_as_failed():
    readiness = build_readiness_from_pyproject_toml("[project")

    assert readiness.status == "failed"
    assert "not valid TOML" in readiness.blockers[0]


def test_build_readiness_reports_malformed_manifest_shape_as_failed():
    readiness = build_readiness_from_pyproject_toml(
        """
[project]
name = "comfygit-env-bad"
requires-python = "==3.11.*"

[tool.comfygit]
schema_version = 2
python_version = "3.11"

[tool.comfygit.models]
abc123 = {filename = "bad.safetensors"}
"""
    )

    assert readiness.status == "failed"
    assert readiness.environment_name == "bad"
    assert readiness.python_version == "3.11"
    assert "manifest could not be interpreted" in readiness.blockers[0]
