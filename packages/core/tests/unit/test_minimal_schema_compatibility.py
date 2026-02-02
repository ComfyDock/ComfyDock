"""Test that minimal schema (omitting unused fields) works with dataclasses."""
from comfygit_core.models.node_mapping import (
    GlobalNodePackage,
    GlobalNodePackageVersion,
)


class TestMinimalSchemaCompatibility:
    """Verify dataclasses work with minimal JSON schema."""

    def test_package_with_minimal_fields(self):
        """Package can be created with only core fields (no unused metadata)."""
        # Simulate **dict unpacking from minimal JSON
        minimal_data = {
            "id": "test-package",
            "display_name": "Test Package",
            "description": "A test package",
            "repository": "https://github.com/test/package",
            "github_stars": 100,
            "versions": {},
            "source": None,
        }

        pkg = GlobalNodePackage(**minimal_data)

        assert pkg.id == "test-package"
        assert pkg.display_name == "Test Package"
        assert pkg.description == "A test package"
        assert pkg.repository == "https://github.com/test/package"
        assert pkg.github_stars == 100
        assert pkg.versions == {}
        assert pkg.source is None
        # Unused fields should default to None
        assert pkg.author is None
        assert pkg.downloads is None
        assert pkg.rating is None
        assert pkg.license is None
        assert pkg.category is None
        assert pkg.icon is None
        assert pkg.tags is None
        assert pkg.status is None
        assert pkg.created_at is None

    def test_version_with_minimal_fields(self):
        """Version can be created with only core fields (no unused metadata)."""
        # Simulate **dict unpacking from minimal JSON
        minimal_data = {
            "version": "1.0.0",
            "download_url": "https://cdn.example.com/package.zip",
            "deprecated": False,
            "dependencies": ["numpy>=1.0"],
        }

        version = GlobalNodePackageVersion(**minimal_data)

        assert version.version == "1.0.0"
        assert version.download_url == "https://cdn.example.com/package.zip"
        assert version.deprecated is False
        assert version.dependencies == ["numpy>=1.0"]
        # Unused fields should default to None
        assert version.changelog is None
        assert version.release_date is None
        assert version.status is None
        assert version.supported_accelerators is None
        assert version.supported_comfyui_version is None
        assert version.supported_os is None

    def test_package_with_only_id(self):
        """Package can be created with just ID (extreme minimal case)."""
        pkg = GlobalNodePackage(id="minimal-pkg")

        assert pkg.id == "minimal-pkg"
        # All optional fields should be None
        assert pkg.display_name is None
        assert pkg.description is None
        assert pkg.repository is None
        assert pkg.github_stars is None
        assert pkg.versions is None
        assert pkg.author is None

    def test_version_with_only_version_string(self):
        """Version can be created with just version string (extreme minimal case)."""
        version = GlobalNodePackageVersion(version="2.0.0")

        assert version.version == "2.0.0"
        # All optional fields should be None
        assert version.download_url is None
        assert version.deprecated is None
        assert version.dependencies is None
        assert version.changelog is None

    def test_package_dict_unpacking_with_mixed_fields(self):
        """Unpacking works when some fields present, some missing."""
        # Simulate real-world scenario: some unused fields present, others omitted
        mixed_data = {
            "id": "mixed-package",
            "display_name": "Mixed Package",
            "repository": "https://github.com/test/mixed",
            # github_stars omitted
            # description omitted
            "author": "Someone",  # Unused field included
            # Other unused fields omitted
        }

        pkg = GlobalNodePackage(**mixed_data)

        assert pkg.id == "mixed-package"
        assert pkg.display_name == "Mixed Package"
        assert pkg.repository == "https://github.com/test/mixed"
        assert pkg.author == "Someone"  # Present in data
        assert pkg.github_stars is None  # Omitted from data
        assert pkg.description is None  # Omitted from data
        assert pkg.downloads is None  # Omitted from data
