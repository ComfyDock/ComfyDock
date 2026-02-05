"""Tests for local UV config injection context."""

from pathlib import Path
from tempfile import TemporaryDirectory

import tomlkit
from comfygit_core.managers.local_uv_config_manager import LocalUVConfigManager
from comfygit_core.managers.pyproject_manager import PyprojectManager


def test_uv_injection_includes_local_uv_config():
    """Should inject local UV config during context and restore afterward."""
    with TemporaryDirectory() as tmpdir:
        env_path = Path(tmpdir)
        cec_path = env_path / ".cec"
        cec_path.mkdir()

        pyproject_path = cec_path / "pyproject.toml"
        initial_config = {
            "project": {
                "name": "test-env",
                "version": "0.1.0",
                "requires-python": ">=3.11",
                "dependencies": [],
            },
            "tool": {
                "comfygit": {
                    "comfyui_version": "v0.3.60",
                    "python_version": "3.11",
                }
            },
        }
        with open(pyproject_path, "w") as f:
            tomlkit.dump(initial_config, f)

        local_config_path = cec_path / ".local-uv-config"
        local_config_path.write_text(
            """
[sources]
comfygit-core = { path = "/data/projects/comfygit-ai/comfygit/packages/core", editable = true }

[[index]]
name = "corporate-pypi"
url = "https://pypi.corp.internal/simple/"
""".lstrip()
        )

        pyproject = PyprojectManager(pyproject_path)
        local_manager = LocalUVConfigManager(cec_path)

        original_content = pyproject_path.read_text()

        with pyproject.uv_injection_context(local_uv_config_manager=local_manager):
            injected_content = pyproject_path.read_text()
            assert "corporate-pypi" in injected_content
            assert "comfygit-core" in injected_content

        restored_content = pyproject_path.read_text()
        assert restored_content == original_content
