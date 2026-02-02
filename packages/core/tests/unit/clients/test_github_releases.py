"""Tests for GitHub release fetching functionality.

Tests the new list_releases, get_release_by_tag, and validate_version_exists methods
that enable fetching and validating ComfyUI release tags from GitHub API.
"""

import pytest
from comfygit_core.clients.github_client import GitHubClient


@pytest.fixture
def github_client():
    """GitHub client for testing."""
    return GitHubClient()


@pytest.fixture
def comfyui_repo_url():
    """ComfyUI repository URL."""
    return "https://github.com/comfyanonymous/ComfyUI.git"


def test_github_client_has_list_releases_method(github_client):
    """SHOULD have list_releases method."""
    assert hasattr(github_client, 'list_releases'), "Should have list_releases method"


def test_github_client_has_get_release_by_tag_method(github_client):
    """SHOULD have get_release_by_tag method."""
    assert hasattr(github_client, 'get_release_by_tag'), "Should have get_release_by_tag method"


def test_github_client_has_validate_version_exists_method(github_client):
    """SHOULD have validate_version_exists method."""
    assert hasattr(github_client, 'validate_version_exists'), "Should have validate_version_exists method"


def test_list_releases_returns_list(github_client, comfyui_repo_url):
    """SHOULD return a list of releases."""
    releases = github_client.list_releases(comfyui_repo_url, limit=5)
    assert isinstance(releases, list), "Should return a list"


def test_list_releases_excludes_drafts(github_client):
    """SHOULD exclude draft releases from results."""
    # Using a known public repo
    repo_url = "https://github.com/microsoft/vscode"
    releases = github_client.list_releases(repo_url, limit=5)

    # Should not have any drafts
    for release in releases:
        assert hasattr(release, 'draft'), "Release should have draft field"
        assert release.draft is False, "Should exclude draft releases"


def test_list_releases_excludes_prereleases_by_default(github_client):
    """SHOULD exclude pre-releases unless requested."""
    # Using a known public repo
    repo_url = "https://github.com/microsoft/vscode"
    releases = github_client.list_releases(repo_url, include_prerelease=False, limit=10)

    # Should not have any prereleases
    for release in releases:
        assert hasattr(release, 'prerelease'), "Release should have prerelease field"
        assert release.prerelease is False, "Should exclude pre-releases by default"


def test_list_releases_includes_prereleases_when_requested(github_client):
    """SHOULD include pre-releases when include_prerelease=True."""
    # This test may pass or fail depending on whether prereleases exist
    repo_url = "https://github.com/microsoft/vscode"
    releases_all = github_client.list_releases(repo_url, include_prerelease=True, limit=20)
    releases_stable = github_client.list_releases(repo_url, include_prerelease=False, limit=20)

    # Either prereleases exist or they don't, but the API should accept the parameter
    assert len(releases_all) >= len(releases_stable), "Including prereleases should not reduce count"


def test_list_releases_respects_limit(github_client, comfyui_repo_url):
    """SHOULD respect the limit parameter."""
    limit = 3
    releases = github_client.list_releases(comfyui_repo_url, limit=limit)
    assert len(releases) <= limit, f"Should return at most {limit} releases"


def test_list_releases_returns_sorted_by_date(github_client, comfyui_repo_url):
    """SHOULD return releases sorted by published date (newest first)."""
    releases = github_client.list_releases(comfyui_repo_url, limit=5)

    if len(releases) >= 2:
        # Check that dates are descending (newest first)
        from datetime import datetime
        for i in range(len(releases) - 1):
            date1 = datetime.fromisoformat(releases[i].published_at.replace('Z', '+00:00'))
            date2 = datetime.fromisoformat(releases[i+1].published_at.replace('Z', '+00:00'))
            assert date1 >= date2, "Releases should be sorted newest first"


def test_list_releases_includes_required_fields(github_client, comfyui_repo_url):
    """SHOULD include all required fields in GitHubRelease objects."""
    releases = github_client.list_releases(comfyui_repo_url, limit=1)

    if len(releases) > 0:
        release = releases[0]
        assert hasattr(release, 'tag_name'), "Should have tag_name"
        assert hasattr(release, 'name'), "Should have name"
        assert hasattr(release, 'published_at'), "Should have published_at"
        assert hasattr(release, 'prerelease'), "Should have prerelease"
        assert hasattr(release, 'draft'), "Should have draft"
        assert hasattr(release, 'html_url'), "Should have html_url"


def test_get_release_by_tag_returns_none_for_invalid(github_client, comfyui_repo_url):
    """SHOULD return None for non-existent tags."""
    result = github_client.get_release_by_tag(comfyui_repo_url, "v999.999.999")
    assert result is None, "Should return None for non-existent release"


def test_get_release_by_tag_returns_release_for_valid_tag(github_client):
    """SHOULD return release object for valid tags."""
    # Use a known stable release from a popular repo
    repo_url = "https://github.com/microsoft/vscode"

    # First get a valid tag
    releases = github_client.list_releases(repo_url, limit=1)
    if len(releases) > 0:
        tag = releases[0].tag_name

        # Now fetch it by tag
        release = github_client.get_release_by_tag(repo_url, tag)
        assert release is not None, "Should return release for valid tag"
        assert release.tag_name == tag, "Should return correct release"


def test_validate_version_exists_for_release_tag(github_client):
    """SHOULD validate release tags via API."""
    # Use a known public repo with releases
    repo_url = "https://github.com/microsoft/vscode"

    # Get a real release tag
    releases = github_client.list_releases(repo_url, limit=1)
    if len(releases) > 0:
        valid_tag = releases[0].tag_name
        is_valid = github_client.validate_version_exists(repo_url, valid_tag)
        assert is_valid is True, "Should validate existing release tag"


def test_validate_version_exists_returns_false_for_invalid(github_client, comfyui_repo_url):
    """SHOULD return False for non-existent versions."""
    is_valid = github_client.validate_version_exists(comfyui_repo_url, "v999.999.999")
    assert is_valid is False, "Should return False for non-existent version"


