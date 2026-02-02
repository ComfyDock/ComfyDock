"""Tests for GitHub URL normalization utilities."""

from comfygit_core.utils.git import normalize_github_url


class TestGitHubUrlNormalization:
    """Test GitHub URL normalization functionality."""

    def test_https_url_no_changes_needed(self):
        url = "https://github.com/owner/repo"
        result = normalize_github_url(url)
        assert result == "https://github.com/owner/repo"

    def test_https_url_with_git_suffix(self):
        url = "https://github.com/owner/repo.git"
        result = normalize_github_url(url)
        assert result == "https://github.com/owner/repo"

    def test_ssh_url_git_at_format(self):
        url = "git@github.com:owner/repo.git"
        result = normalize_github_url(url)
        assert result == "https://github.com/owner/repo"

    def test_ssh_url_git_at_format_no_git_suffix(self):
        url = "git@github.com:owner/repo"
        result = normalize_github_url(url)
        assert result == "https://github.com/owner/repo"

    def test_ssh_url_full_format(self):
        url = "ssh://git@github.com/owner/repo.git"
        result = normalize_github_url(url)
        assert result == "https://github.com/owner/repo"

    def test_ssh_url_full_format_no_git_suffix(self):
        url = "ssh://git@github.com/owner/repo"
        result = normalize_github_url(url)
        assert result == "https://github.com/owner/repo"

    def test_www_github_url(self):
        url = "https://www.github.com/owner/repo"
        result = normalize_github_url(url)
        assert result == "https://github.com/owner/repo"

    def test_complex_github_url_with_extra_path_parts(self):
        url = "https://github.com/owner/repo/tree/main"
        result = normalize_github_url(url)
        assert result == "https://github.com/owner/repo"

    def test_empty_url(self):
        result = normalize_github_url("")
        assert result == ""

    def test_none_url(self):
        result = normalize_github_url(None)
        assert result == ""

    def test_non_github_url(self):
        url = "https://gitlab.com/owner/repo.git"
        result = normalize_github_url(url)
        # Non-GitHub URLs still get .git removed
        assert result == "https://gitlab.com/owner/repo"

    def test_invalid_github_url_format(self):
        url = "https://github.com/owner"  # Missing repo
        result = normalize_github_url(url)
        # Should return original URL since it doesn't have enough path parts
        assert result == "https://github.com/owner"
