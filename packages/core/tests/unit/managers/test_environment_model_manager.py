from unittest.mock import Mock

from comfygit_core.managers.environment_model_manager import EnvironmentModelManager
from comfygit_core.models.manifest import ManifestModel, ManifestWorkflowModel
from comfygit_core.models.shared import ModelWithLocation


def test_manual_workflow_model_requires_exact_indexed_path():
    pyproject = Mock()
    pyproject.workflows.get_all_with_resolutions.return_value = {"manual_workflow": {}}
    pyproject.workflows.get_workflow_models.return_value = [
        ManifestWorkflowModel(
            hash="abc123",
            filename="manual.safetensors",
            category="custom_loader",
            criticality="required",
            status="resolved",
            nodes=[],
            relative_path="custom_loader/manual.safetensors",
            declared_by="manual",
        )
    ]
    pyproject.models.get_by_hash.return_value = ManifestModel(
        hash="abc123",
        filename="manual.safetensors",
        size=1024,
        relative_path="custom_loader/manual.safetensors",
        category="custom_loader",
        sources=["https://example.test/manual.safetensors"],
    )
    pyproject.models.get_all.return_value = []

    repository = Mock()
    repository.find_by_exact_path.return_value = None
    repository.get_model.return_value = ModelWithLocation(
        hash="abc123",
        filename="manual.safetensors",
        file_size=1024,
        relative_path="other/manual.safetensors",
        mtime=0,
        last_seen=0,
    )

    manager = EnvironmentModelManager(
        pyproject=pyproject,
        model_repository=repository,
        model_downloader=Mock(),
    )

    missing = manager.detect_missing_models()

    assert len(missing) == 1
    assert missing[0].model.hash == "abc123"
    assert missing[0].workflow_names == ["manual_workflow"]
    assert missing[0].criticality == "required"
    assert missing[0].can_download is True


def test_manual_workflow_model_present_when_exact_path_hash_matches():
    pyproject = Mock()
    pyproject.workflows.get_all_with_resolutions.return_value = {"manual_workflow": {}}
    pyproject.workflows.get_workflow_models.return_value = [
        ManifestWorkflowModel(
            hash="abc123",
            filename="manual.safetensors",
            category="custom_loader",
            criticality="required",
            status="resolved",
            nodes=[],
            relative_path="custom_loader/manual.safetensors",
            declared_by="manual",
        )
    ]
    pyproject.models.get_all.return_value = []

    repository = Mock()
    repository.find_by_exact_path.return_value = ModelWithLocation(
        hash="abc123",
        filename="manual.safetensors",
        file_size=1024,
        relative_path="custom_loader/manual.safetensors",
        mtime=0,
        last_seen=0,
    )

    manager = EnvironmentModelManager(
        pyproject=pyproject,
        model_repository=repository,
        model_downloader=Mock(),
    )

    assert manager.detect_missing_models() == []
