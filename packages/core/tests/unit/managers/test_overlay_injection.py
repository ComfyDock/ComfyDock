"""Tests for overlay-based pyproject injection."""

from pathlib import Path

import pytest
import tomlkit
from comfygit_core.managers.overlay_manager import OverlayManager
from comfygit_core.managers.pyproject_manager import PyprojectManager
from comfygit_core.models.overlay import OverlayConfig


def _create_pyproject(pyproject_path: Path) -> None:
    config = {
        "project": {
            "name": "test-env",
            "version": "0.1.0",
            "requires-python": ">=3.11",
            "dependencies": ["numpy>=1.0"],
        },
        "tool": {
            "comfygit": {
                "python_version": "3.11",
            },
            "uv": {
                "constraint-dependencies": ["numpy>=1.0"],
                "sources": {
                    "torch": {"index": "pytorch-cu121"},
                },
                "index": [
                    {
                        "name": "pytorch-cu121",
                        "url": "https://download.pytorch.org/whl/cu121",
                        "explicit": True,
                    }
                ],
            },
        },
    }
    with open(pyproject_path, "w", encoding="utf-8") as f:
        tomlkit.dump(config, f)


def test_overlay_injection_supports_all_fields_and_restores_file(tmp_path):
    pyproject_path = tmp_path / "pyproject.toml"
    _create_pyproject(pyproject_path)
    manager = PyprojectManager(pyproject_path)

    overlay = OverlayConfig(
        name="sageattention",
        path=tmp_path / "sageattention.toml",
        dependencies=["sageattention>=2.0"],
        sources={"sageattention": {"git": "https://github.com/thu-ml/SageAttention.git"}},
        settings={
            "no-build-isolation-package": ["sageattention"],
            "override-dependencies": ["triton==3.4.0"],
            "environments": ["sys_platform == 'linux'"],
        },
        dependency_metadata=[{"name": "sageattention", "version": "2.1.1"}],
        constraints=["sageattention>=2.0"],
        indexes=[{"name": "custom", "url": "https://example.com/simple", "explicit": True}],
    )

    original = pyproject_path.read_text(encoding="utf-8")
    with manager.uv_injection_context(overlays=[overlay]):
        injected = manager.load(force_reload=True)
        deps = injected["project"]["dependencies"]
        uv_cfg = injected["tool"]["uv"]

        assert "numpy>=1.0" in deps
        assert "sageattention>=2.0" in deps
        assert uv_cfg["sources"]["sageattention"]["git"].startswith("https://")
        assert uv_cfg["no-build-isolation-package"] == ["sageattention"]
        assert uv_cfg["override-dependencies"] == ["triton==3.4.0"]
        assert uv_cfg["environments"] == ["sys_platform == 'linux'"]
        assert uv_cfg["dependency-metadata"][0]["name"] == "sageattention"
        assert uv_cfg["constraint-dependencies"][-1] == "sageattention>=2.0"
        assert any(idx["name"] == "custom" for idx in uv_cfg["index"])

    restored = pyproject_path.read_text(encoding="utf-8")
    assert restored == original


def test_apply_uv_overlays_persists_materialized_config(tmp_path):
    pyproject_path = tmp_path / "pyproject.toml"
    _create_pyproject(pyproject_path)
    manager = PyprojectManager(pyproject_path)

    overlay = OverlayConfig(
        name="direct",
        path=tmp_path / "direct.toml",
        dependencies=["requests>=2.31"],
        sources={"requests": {"index": "custom"}},
        indexes=[{"name": "custom", "url": "https://example.com/simple", "explicit": True}],
    )

    manager.apply_uv_overlays([overlay])

    materialized = manager.load(force_reload=True)
    deps = materialized["project"]["dependencies"]
    uv_cfg = materialized["tool"]["uv"]

    assert "requests>=2.31" in deps
    assert uv_cfg["sources"]["requests"]["index"] == "custom"
    assert any(index["name"] == "custom" for index in uv_cfg["index"])


def test_overlay_injection_last_wins_with_pep503_normalization(tmp_path):
    pyproject_path = tmp_path / "pyproject.toml"
    _create_pyproject(pyproject_path)
    manager = PyprojectManager(pyproject_path)

    overlay1 = OverlayConfig(
        name="one",
        path=tmp_path / "one.toml",
        sources={"SageAttention": {"url": "https://first.example/whl"}},
        dependency_metadata=[{"name": "SageAttention", "version": "1.0.0"}],
        constraints=["SageAttention==1.0.0"],
    )
    overlay2 = OverlayConfig(
        name="two",
        path=tmp_path / "two.toml",
        sources={"sageattention": {"url": "https://second.example/whl"}},
        dependency_metadata=[{"name": "sage_attention", "version": "2.0.0"}],
        constraints=["sage_attention==2.0.0"],
    )

    with manager.uv_injection_context(overlays=[overlay1, overlay2]):
        injected = manager.load(force_reload=True)
        uv_cfg = injected["tool"]["uv"]

        source_keys = list(uv_cfg["sources"].keys())
        matching = [key for key in source_keys if key.lower().replace("_", "").replace("-", "") == "sageattention"]
        assert len(matching) == 1
        assert uv_cfg["sources"][matching[0]]["url"] == "https://second.example/whl"
        assert uv_cfg["constraint-dependencies"][-1] == "sage_attention==2.0.0"
        assert uv_cfg["dependency-metadata"][-1]["version"] == "2.0.0"


def test_pytorch_overlay_strips_existing_pytorch_before_inject(tmp_path):
    pyproject_path = tmp_path / "pyproject.toml"
    _create_pyproject(pyproject_path)
    manager = PyprojectManager(pyproject_path)

    pytorch_overlay = OverlayConfig(
        name=".pytorch",
        path=tmp_path / ".pytorch.toml",
        kind="pytorch",
        is_local=True,
        sources={
            "torch": {"index": "pytorch-cu128"},
            "torchvision": {"index": "pytorch-cu128"},
            "torchaudio": {"index": "pytorch-cu128"},
        },
        constraints=[
            "torch==2.6.0+cu128",
            "torchvision==0.21.0+cu128",
            "torchaudio==2.6.0+cu128",
        ],
        indexes=[
            {
                "name": "pytorch-cu128",
                "url": "https://download.pytorch.org/whl/cu128",
                "explicit": True,
            }
        ],
    )

    with manager.uv_injection_context(overlays=[pytorch_overlay]):
        injected = manager.load(force_reload=True)
        uv_cfg = injected["tool"]["uv"]

        index_names = [index.get("name") for index in uv_cfg.get("index", [])]
        assert "pytorch-cu121" not in index_names
        assert "pytorch-cu128" in index_names
        assert uv_cfg["sources"]["torch"]["index"] == "pytorch-cu128"
        assert "numpy>=1.0" in uv_cfg["constraint-dependencies"]
        assert any("cu128" in item for item in uv_cfg["constraint-dependencies"])


def test_extract_dependency_key_handles_dotted_distribution_names(tmp_path):
    pyproject_path = tmp_path / "pyproject.toml"
    _create_pyproject(pyproject_path)
    manager = PyprojectManager(pyproject_path)

    assert manager._extract_dependency_key("zope.interface>=5") == "zope-interface"
    assert manager._extract_dependency_key("jaraco.functools") == "jaraco-functools"
    assert manager._extract_dependency_key("requests>=2.31") == "requests"


def test_overlay_dependency_replaces_base_when_name_is_dotted(tmp_path):
    pyproject_path = tmp_path / "pyproject.toml"
    _create_pyproject(pyproject_path)
    manager = PyprojectManager(pyproject_path)

    config = manager.load()
    config["project"]["dependencies"] = ["zope.interface>=4", "requests>=2.31"]
    manager.save(config)

    overlay = OverlayConfig(
        name="dotted",
        path=tmp_path / "dotted.toml",
        dependencies=["zope.interface>=5"],
    )

    with manager.uv_injection_context(overlays=[overlay]):
        injected = manager.load(force_reload=True)
        deps = injected["project"]["dependencies"]
        assert "zope.interface>=5" in deps
        assert "zope.interface>=4" not in deps
        assert "requests>=2.31" in deps


def test_stock_triton_overlay_marker_survives_and_replaces_base_dep(tmp_path):
    cec = tmp_path / ".cec"
    cec.mkdir()
    pyproject_path = cec / "pyproject.toml"
    _create_pyproject(pyproject_path)
    manager = PyprojectManager(pyproject_path)

    config = manager.load()
    config["project"]["dependencies"] = ["triton", "numpy>=1.0"]
    manager.save(config)

    overlay_manager = OverlayManager(cec)
    stock_overlay = overlay_manager.load_overlay("triton")

    with manager.uv_injection_context(overlays=[stock_overlay]):
        injected = manager.load(force_reload=True)
        deps = injected["project"]["dependencies"]
        assert "triton>=3.0 ; sys_platform == 'linux'" in deps
        assert "triton" not in deps
        assert "numpy>=1.0" in deps


def test_overlay_dependency_last_wins_for_same_canonical_name(tmp_path):
    pyproject_path = tmp_path / "pyproject.toml"
    _create_pyproject(pyproject_path)
    manager = PyprojectManager(pyproject_path)

    overlay = OverlayConfig(
        name="canonical",
        path=tmp_path / "canonical.toml",
        dependencies=["Torch==2.1.0", "torch>=2.2.0"],
    )

    with manager.uv_injection_context(overlays=[overlay]):
        injected = manager.load(force_reload=True)
        deps = injected["project"]["dependencies"]
        assert "torch>=2.2.0" in deps
        assert "Torch==2.1.0" not in deps


def test_injection_snapshot_restore_round_trips_non_ascii_content(tmp_path):
    pyproject_path = tmp_path / "pyproject.toml"
    _create_pyproject(pyproject_path)
    manager = PyprojectManager(pyproject_path)

    config = manager.load()
    config["tool"]["comfygit"]["note"] = "cafe - cafe - テスト"
    manager.save(config)

    original = pyproject_path.read_text(encoding="utf-8")
    overlay = OverlayConfig(
        name="transient",
        path=tmp_path / "transient.toml",
        dependencies=["requests>=2.31"],
    )

    with manager.uv_injection_context(overlays=[overlay]):
        injected_text = pyproject_path.read_text(encoding="utf-8")
        assert "requests>=2.31" in injected_text

    restored = pyproject_path.read_text(encoding="utf-8")
    assert restored == original
    assert "テスト" in restored


def test_injection_failure_logs_redacted_summary_without_secret_leak(tmp_path, caplog):
    pyproject_path = tmp_path / "pyproject.toml"
    _create_pyproject(pyproject_path)
    manager = PyprojectManager(pyproject_path)

    overlay = OverlayConfig(
        name="private-overlay",
        path=tmp_path / "private-overlay.toml",
        dependencies=["privatepkg>=1.0"],
        sources={"privatepkg": {"index": "private"}},
        indexes=[
            {
                "name": "private",
                "url": "https://token-user:secret-token@example.internal/simple",
                "explicit": True,
            }
        ],
    )

    caplog.set_level("ERROR")

    with pytest.raises(RuntimeError, match="forced failure"):
        with manager.uv_injection_context(overlays=[overlay]):
            raise RuntimeError("forced failure")

    log_output = "\n".join(record.getMessage() for record in caplog.records)
    assert "Overlays:" in log_output
    assert "private-overlay" in log_output
    assert "Overlay field summary:" in log_output
    assert "Overlay application error: RuntimeError: forced failure" in log_output
    assert "secret-token" not in log_output
    assert "Injected config:" not in log_output
    assert "[project]" not in log_output
