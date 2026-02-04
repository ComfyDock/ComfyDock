"""Tests for LocalUVConfigManager."""

from pathlib import Path
from tempfile import TemporaryDirectory

from comfygit_core.managers.local_uv_config_manager import LocalUVConfigManager


def test_local_uv_config_parses_sources_and_indexes():
    """Should parse sources and indexes from .local-uv-config."""
    with TemporaryDirectory() as tmpdir:
        cec_path = Path(tmpdir) / ".cec"
        cec_path.mkdir()

        config_path = cec_path / ".local-uv-config"
        config_path.write_text(
            """
[sources]
comfygit-core = { path = "/data/projects/comfygit-ai/comfygit/packages/core", editable = true }

[[index]]
name = "corporate-pypi"
url = "https://pypi.corp.internal/simple/"
""".lstrip()
        )

        manager = LocalUVConfigManager(cec_path)
        uv_config = manager.get_uv_config()

        sources = uv_config.get("sources", {})
        indexes = uv_config.get("indexes", [])

        assert "comfygit-core" in sources
        assert sources["comfygit-core"]["path"].endswith("packages/core")
        assert indexes and indexes[0]["name"] == "corporate-pypi"

        # Ensure gitignore entry is added
        gitignore_path = cec_path / ".gitignore"
        assert gitignore_path.exists()
        assert ".local-uv-config" in gitignore_path.read_text()
