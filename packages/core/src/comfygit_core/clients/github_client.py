"""GitHub API client for repository operations and metadata retrieval."""

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from comfygit_core.constants import DEFAULT_GITHUB_URL
from comfygit_core.logging.logging_config import get_logger
from comfygit_core.utils.git import parse_github_url
from comfygit_core.utils.retry import RateLimitManager, RetryConfig

logger = get_logger(__name__)


@dataclass
class GitHubRepoInfo:
    """Information about a GitHub repository."""
    owner: str
    name: str
    default_branch: str
    description: str | None = None
    latest_release: str | None = None
    clone_url: str | None = None
    latest_commit: str | None = None


@dataclass
class GitHubRelease:
    """Single GitHub release."""
    tag_name: str
    name: str
    published_at: str
    prerelease: bool
    draft: bool
    html_url: str


class GitHubClient:
    """Client for interacting with GitHub repositories.

    Provides repository cloning, metadata retrieval, and release management.
    Always fetches fresh data from API (no caching) to ensure latest versions.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_GITHUB_URL,
        token: str | None = None,
        token_provider: Callable[[], str | None] | None = None,
    ):
        self.base_url = base_url
        self._token = token
        self._token_provider = token_provider
        self.rate_limiter = RateLimitManager(min_interval=0.05)
        self.retry_config = RetryConfig(
            max_retries=3,
            initial_delay=1.0,
            max_delay=30.0,
            exponential_base=2.0,
            jitter=True,
        )

    def _resolve_token(self) -> str | None:
        if self._token:
            return self._token
        if self._token_provider:
            return self._token_provider()
        return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")

    def _open_json(self, url: str) -> Any:
        request = urllib.request.Request(url)
        request.add_header("Accept", "application/vnd.github+json")
        if token := self._resolve_token():
            request.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read())

    def parse_github_url(self, url: str) -> GitHubRepoInfo | None:
        """Parse a GitHub URL to extract repository information.

        Args:
            url: GitHub repository URL

        Returns:
            GitHubRepoInfo or None if invalid URL
        """
        parsed = parse_github_url(url)
        if not parsed:
            return None

        owner, name, _ = parsed  # Ignore commit for basic parsing
        return GitHubRepoInfo(
            owner=owner,
            name=name,
            default_branch="main",  # Will be updated by get_repository_info
            clone_url=f"https://github.com/{owner}/{name}.git"
        )

    def clone_repository(self, repo_url: str, target_path: Path,
                        ref: str | None = None) -> bool:
        """Clone a GitHub repository to a target path.

        Args:
            repo_url: GitHub repository URL
            target_path: Where to clone the repository
            ref: Optional git ref (branch/tag/commit) to checkout

        Returns:
            True if successful, False otherwise
        """
        # TODO: Use git to clone repository
        # TODO: Checkout specific ref if provided
        # TODO: Handle authentication if needed
        return False

    def get_repository_info(self, repo_url: str, ref: str | None = None) -> GitHubRepoInfo | None:
        """Get information about a GitHub repository.

        Args:
            repo_url: GitHub repository URL
            ref: Optional git ref (branch/tag/commit) to resolve

        Returns:
            Repository information or None if not found
        """
        parsed = parse_github_url(repo_url)
        if not parsed:
            return None

        owner, name, url_commit = parsed

        # ref parameter takes precedence over URL-embedded commit
        target_ref = ref or url_commit

        try:
            # Rate limit API calls
            self.rate_limiter.wait_if_needed("github_api")

            # Get repo metadata
            api_url = f"https://api.github.com/repos/{owner}/{name}"
            repo_data = self._open_json(api_url)

            default_branch = repo_data.get("default_branch", "main")

            # Resolve target ref to commit SHA
            latest_commit = None
            if target_ref:
                # Ref specified - resolve to commit (works for branches, tags, and commits)
                try:
                    commits_url = f"https://api.github.com/repos/{owner}/{name}/commits/{target_ref}"
                    commit_data = self._open_json(commits_url)
                    latest_commit = commit_data.get("sha")
                except urllib.error.HTTPError:
                    logger.warning(f"Could not resolve ref '{target_ref}' for {owner}/{name}")
                    pass
            else:
                # No ref - get latest commit from default branch
                try:
                    commits_url = f"https://api.github.com/repos/{owner}/{name}/commits/{default_branch}"
                    commit_data = self._open_json(commits_url)
                    latest_commit = commit_data.get("sha")
                except urllib.error.HTTPError:
                    pass

            # Get latest release
            latest_release = None
            try:
                releases_url = f"https://api.github.com/repos/{owner}/{name}/releases/latest"
                release_data = self._open_json(releases_url)
                latest_release = release_data.get("tag_name")
            except urllib.error.HTTPError:
                # No releases found, that's okay
                pass

            return GitHubRepoInfo(
                owner=owner,
                name=name,
                default_branch=default_branch,
                description=repo_data.get("description"),
                latest_release=latest_release,
                clone_url=repo_data.get("clone_url"),
                latest_commit=latest_commit
            )

        except (urllib.error.URLError, json.JSONDecodeError) as e:
            logger.warning(f"Failed to get repository info for {repo_url}: {e}")
            return None

    def list_releases(self, repo_url: str, include_prerelease: bool = False,
                     limit: int = 10) -> list[GitHubRelease]:
        """List releases from GitHub API.

        Args:
            repo_url: GitHub repository URL
            include_prerelease: Include pre-release versions
            limit: Maximum number of releases to fetch

        Returns:
            List of GitHubRelease objects, sorted by date (newest first)
        """
        parsed = parse_github_url(repo_url)
        if not parsed:
            return []

        owner, name, _ = parsed

        try:
            # Rate limit API calls
            self.rate_limiter.wait_if_needed("github_api")

            # Get all releases
            api_url = f"https://api.github.com/repos/{owner}/{name}/releases?per_page={min(limit * 2, 100)}"
            releases_data = self._open_json(api_url)

            # Parse into GitHubRelease objects
            releases = []
            for release_data in releases_data:
                # Skip drafts always
                if release_data.get("draft", False):
                    continue

                release = GitHubRelease(
                    tag_name=release_data["tag_name"],
                    name=release_data.get("name", release_data["tag_name"]),
                    published_at=release_data["published_at"],
                    prerelease=release_data.get("prerelease", False),
                    draft=release_data.get("draft", False),
                    html_url=release_data["html_url"]
                )
                releases.append(release)

            # Sort by published date (newest first)
            releases.sort(key=lambda r: r.published_at, reverse=True)

            # Filter and limit
            if not include_prerelease:
                releases = [r for r in releases if not r.prerelease]
            return releases[:limit]

        except (urllib.error.URLError, json.JSONDecodeError) as e:
            logger.warning(f"Failed to list releases for {repo_url}: {e}")
            return []

    def get_release_by_tag(self, repo_url: str, tag: str) -> GitHubRelease | None:
        """Get specific release by tag name.

        Args:
            repo_url: GitHub repository URL
            tag: Release tag (e.g., "v0.3.20")

        Returns:
            GitHubRelease if found, None otherwise
        """
        parsed = parse_github_url(repo_url)
        if not parsed:
            return None

        owner, name, _ = parsed

        try:
            # Rate limit API calls
            self.rate_limiter.wait_if_needed("github_api")

            # Get specific release by tag
            api_url = f"https://api.github.com/repos/{owner}/{name}/releases/tags/{tag}"
            release_data = self._open_json(api_url)

            return GitHubRelease(
                tag_name=release_data["tag_name"],
                name=release_data.get("name", release_data["tag_name"]),
                published_at=release_data["published_at"],
                prerelease=release_data.get("prerelease", False),
                draft=release_data.get("draft", False),
                html_url=release_data["html_url"]
            )

        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            logger.warning(f"Failed to get release {tag} for {repo_url}: {e}")
            return None
        except (urllib.error.URLError, json.JSONDecodeError) as e:
            logger.warning(f"Failed to get release {tag} for {repo_url}: {e}")
            return None

    def validate_version_exists(self, repo_url: str, version: str) -> bool:
        """Check if a version (tag, commit, or branch) exists.

        Args:
            repo_url: GitHub repository URL
            version: Tag name, commit SHA, or branch name

        Returns:
            True if version exists and is accessible
        """
        # If looks like tag (starts with 'v'), check releases
        if version.startswith('v'):
            release = self.get_release_by_tag(repo_url, version)
            return release is not None

        # For branches and commits, we could check other APIs
        # but for simplicity, assume they exist
        # (git clone will fail if they don't)
        return True

    def download_release_asset(self, repo_url: str, asset_name: str,
                              target_path: Path) -> bool:
        """Download a specific release asset from a repository.

        Args:
            repo_url: GitHub repository URL
            asset_name: Name of the asset to download
            target_path: Where to save the downloaded asset

        Returns:
            True if successful, False otherwise
        """
        # TODO: Find release with the asset
        # TODO: Download the asset
        # TODO: Save to target path
        return False
