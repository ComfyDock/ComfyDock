"""NodeLookupService - Pure stateless service for finding nodes and analyzing requirements."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from packaging.requirements import InvalidRequirement, Requirement

from comfygit_core.models.exceptions import CDNodeNotFoundError, CDRegistryError
from comfygit_core.models.shared import NodeInfo

from ..analyzers.custom_node_scanner import CustomNodeScanner
from ..caching import CustomNodeCacheManager
from ..clients import ComfyRegistryClient, GitHubClient
from ..logging.logging_config import get_logger
from ..utils.git import is_git_url

if TYPE_CHECKING:
    from comfygit_core.configs.package_config import PackageConfigManager
    from comfygit_core.repositories.node_mappings_repository import NodeMappingsRepository
    from comfygit_core.repositories.workspace_config_repository import WorkspaceConfigRepository

logger = get_logger(__name__)


GIT_ACQUISITION_VERSION_ALIASES = {"nightly", "dev"}
GIT_NODE_DOWNLOAD_TIMEOUT_SECONDS = 300


def _repository_name_from_url(url: str) -> str:
    """Return a best-effort repository directory name from a git URL."""
    candidate = url.rstrip("/").rsplit("/", 1)[-1]
    if ":" in candidate:
        candidate = candidate.rsplit(":", 1)[-1]
    if candidate.endswith(".git"):
        candidate = candidate[:-4]
    return candidate or "custom-node"


def _is_valid_git_ref(version: str | None) -> bool:
    """Check if a version string is a valid git ref (tag, branch, or commit hash).

    Semver versions like "1.11.1" are NOT valid git refs unless prefixed with 'v'.
    Git refs include:
    - Tags: v1.0.0, release-1.0
    - Branches: main, master, dev, feature/foo
    - Commit hashes: 40 hex characters

    Args:
        version: Version string to check

    Returns:
        True if version looks like a valid git ref, False otherwise
    """
    if not version:
        return False

    # Commit hash: 40 hex characters
    if len(version) == 40 and all(c in '0123456789abcdef' for c in version.lower()):
        return True

    # Git-style tag: starts with 'v' followed by number
    if version.startswith('v') and len(version) > 1 and version[1].isdigit():
        return True

    # Branch names or other refs: contain letters but don't look like pure semver
    # Pure semver: digits and dots only (e.g., "1.11.1")
    is_pure_semver = all(c.isdigit() or c == '.' for c in version)
    if is_pure_semver:
        return False

    # Everything else (branch names like "main", "dev", "feature/foo") is valid
    return True


def _is_explicit_git_acquisition_version(version: str | None) -> bool:
    """Return whether a registry version label means explicit git acquisition."""
    return (version or "").lower() in GIT_ACQUISITION_VERSION_ALIASES


def _requirement_applies_to_current_environment(requirement: str) -> bool:
    """Return whether a PEP 508 requirement applies to this interpreter/platform.

    Requirement files can include environment markers, for example:
    ``jetson-stats; platform_machine == 'aarch64'``. uv/pip skip those when the
    marker is false; ComfyGit should do the same before adding node dependency
    requirements to the managed manifest.
    """
    try:
        parsed = Requirement(requirement)
    except InvalidRequirement:
        # Keep pip options, URL forms, and non-standard lines rather than
        # guessing. Downstream install tooling can decide whether they are valid.
        return True

    if parsed.marker is None:
        return True

    try:
        return bool(parsed.marker.evaluate())
    except Exception as exc:
        logger.debug(
            "Could not evaluate requirement marker for '%s': %s",
            requirement,
            exc,
        )
        return True


class NodeLookupService:
    """Pure stateless service for finding nodes and analyzing their requirements.

    Responsibilities:
    - Registry lookup (API-first, cache fallback)
    - GitHub API calls (validating repos, getting commit info)
    - Requirement scanning (analyzing node directories)
    - Cache management (API responses, downloaded node archives)
    """

    def __init__(
        self,
        cache_path: Path,
        node_mappings_repository: NodeMappingsRepository | None = None,
        workspace_config: WorkspaceConfigRepository | None = None,
    ):
        """Initialize the node lookup service.

        Args:
            cache_path: Required path to workspace cache directory
            node_mappings_repository: Repository for cached node mappings (fallback when API fails)
            workspace_config: Optional workspace config for git/GitHub credentials
        """
        self.workspace_config = workspace_config
        self.scanner = CustomNodeScanner()
        self.custom_node_cache = CustomNodeCacheManager(cache_base_path=cache_path)
        self.registry_client = ComfyRegistryClient()
        self.github_client = GitHubClient(token_provider=self.get_git_token)
        self.node_mappings_repository = node_mappings_repository

    def get_git_token(self) -> str | None:
        """Return the configured git host token, if one is available."""
        if not self.workspace_config:
            return None
        return self.workspace_config.get_github_token()

    def find_node(self, identifier: str) -> NodeInfo | None:
        """Find node info from registry API, git URL, or local cache.

        API-first strategy:
        1. Git URLs → query GitHub API directly
        2. Registry IDs → query live registry API first
        3. If API fails → fall back to local node mappings cache

        Args:
            identifier: Registry ID, git URL, or name. Supports @version/@ref syntax:
                       - registry-id@1.0.0 (registry version)
                       - https://github.com/user/repo@v1.2.3 (git tag)
                       - https://github.com/user/repo@main (git branch)
                       - https://github.com/user/repo@abc123 (git commit)

        Returns:
            NodeInfo with metadata, or None if not found
        """
        # Parse version/ref from identifier (e.g., "package-id@1.2.3" or "https://...@branch")
        requested_version = None
        base_identifier = identifier

        if '@' in identifier:
            parts = identifier.rsplit('@', 1)  # rsplit to handle URLs with @
            base_identifier = parts[0]
            requested_version = parts[1]

        # Check if it's a git URL - these go directly to GitHub API
        if is_git_url(base_identifier):
            try:
                if repo_info := self.github_client.get_repository_info(base_identifier, ref=requested_version):
                    return NodeInfo(
                        name=repo_info.name,
                        repository=repo_info.clone_url,
                        source="git",
                        version=repo_info.latest_commit  # This will be the requested ref's commit
                    )
            except Exception as e:
                logger.warning(
                    "Could not query GitHub metadata for %s: %s. "
                    "Falling back to direct git clone metadata.",
                    base_identifier,
                    e,
                )

            return NodeInfo(
                name=_repository_name_from_url(base_identifier),
                repository=base_identifier,
                source="git",
                version=requested_version,
            )

        # Strategy: API first, cache fallback
        try:
            registry_node = self.registry_client.get_node(base_identifier)
            if registry_node:
                if requested_version:
                    version = requested_version
                    logger.debug(f"Using requested version: {version}")
                else:
                    version = registry_node.latest_version.version if registry_node.latest_version else None
                node_version = self.registry_client.install_node(registry_node.id, version)
                if node_version:
                    registry_node.latest_version = node_version
                elif _is_explicit_git_acquisition_version(requested_version) and registry_node.repository:
                    repo_info = self.github_client.get_repository_info(registry_node.repository)
                    if repo_info:
                        return NodeInfo(
                            name=repo_info.name,
                            registry_id=registry_node.id,
                            repository=repo_info.clone_url,
                            source="git",
                            version=repo_info.latest_commit,
                        )
                return NodeInfo.from_registry_node(registry_node)
        except CDRegistryError as e:
            logger.warning(f"Cannot reach registry: {e}")
            # Fall back to local cache
            if self.node_mappings_repository:
                logger.debug(f"Trying local cache for '{base_identifier}'...")
                package = self.node_mappings_repository.get_package(base_identifier)
                if package:
                    logger.debug(f"Found '{base_identifier}' in local cache")
                    node_info = NodeInfo.from_global_package(package, version=requested_version)
                    if node_info.download_url:
                        return node_info
                    logger.debug(
                        f"Cache has '{base_identifier}' but missing download_url for version "
                        f"'{requested_version}'"
                    )

        logger.debug(f"Node '{base_identifier}' not found")
        return None

    def get_node(self, identifier: str) -> NodeInfo:
        """Get a node - raises if not found.

        Args:
            identifier: Registry ID, node name, or git URL

        Returns:
            NodeInfo with metadata

        Raises:
            CDNodeNotFoundError: If node not found in any source
        """
        node = self.find_node(identifier)
        if not node:
            # Build context-aware error based on what was tried
            if is_git_url(identifier):
                msg = f"Node '{identifier}' not found. GitHub repository is invalid or inaccessible."
            else:
                msg = f"Node '{identifier}' not found in registry API or local cache"

            raise CDNodeNotFoundError(msg)
        return node

    def scan_requirements(
        self,
        node_path: Path,
        package_config: PackageConfigManager | None = None,
    ) -> list[str]:
        """Scan a node directory for Python requirements.

        Args:
            node_path: Path to node directory
            package_config: Optional package config for substitutions

        Returns:
            List of requirement strings (empty if none found)
        """
        deps = self.scanner.scan_node(node_path)
        if deps and deps.requirements:
            requirements: list[str] = []
            for req in deps.requirements:
                if _requirement_applies_to_current_environment(req):
                    requirements.append(req)
                else:
                    logger.debug(
                        "Skipping requirement with non-matching environment marker: %s",
                        req,
                    )

            # Apply package substitutions if config provided
            if package_config:
                requirements = [
                    package_config.apply_substitution(req)
                    for req in requirements
                ]

            logger.info(f"Found {len(requirements)} requirements in {node_path.name}")
            return requirements
        logger.info(f"No requirements found in {node_path.name}")
        return []

    def download_to_cache(self, node_info: NodeInfo) -> Path | None:
        """Download a node to cache and return the cached path.

        Args:
            node_info: Node information

        Returns:
            Path to cached node directory, or None if download failed
        """
        import tempfile

        from ..utils.download import download_and_extract_archive
        from ..utils.git import git_clone

        # Check if already cached
        if cache_path := self.custom_node_cache.get_cached_path(node_info):
            logger.debug(f"Node '{node_info.name}' already in cache")
            return cache_path

        # Download to temp location
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir) / node_info.name

            try:
                if node_info.source == "registry":
                    if not node_info.download_url:
                        logger.error(
                            f"Cannot download registry node '{node_info.name}': "
                            f"no registry artifact is available. "
                            f"Choose an explicit git install if repository acquisition is acceptable."
                        )
                        return None
                    try:
                        download_and_extract_archive(node_info.download_url, temp_path)
                    except Exception as artifact_error:
                        if not node_info.repository:
                            raise

                        logger.warning(
                            "Registry artifact download failed for '%s'; "
                            "falling back to repository clone from %s: %s",
                            node_info.name,
                            node_info.repository,
                            artifact_error,
                        )
                        if temp_path.exists():
                            from ..utils.filesystem import rmtree

                            rmtree(temp_path)
                        ref = node_info.version if _is_valid_git_ref(node_info.version) else None
                        git_clone(
                            node_info.repository,
                            temp_path,
                            depth=1,
                            ref=ref,
                            timeout=GIT_NODE_DOWNLOAD_TIMEOUT_SECONDS,
                            token=self.get_git_token(),
                        )
                elif node_info.source == "git":
                    if not node_info.repository:
                        logger.error(f"No repository URL for git node '{node_info.name}'")
                        return None
                    # Only use version as ref if it's a valid git ref
                    ref = node_info.version if _is_valid_git_ref(node_info.version) else None
                    git_clone(
                        node_info.repository,
                        temp_path,
                        depth=1,
                        ref=ref,
                        timeout=GIT_NODE_DOWNLOAD_TIMEOUT_SECONDS,
                        token=self.get_git_token(),
                    )
                else:
                    logger.error(f"Unsupported source: '{node_info.source}'")
                    return None

                # Cache it
                logger.info(f"Caching node '{node_info.name}'")
                return self.custom_node_cache.cache_node(node_info, temp_path)

            except Exception as e:
                logger.error(f"Failed to download node '{node_info.name}': {e}")
                return None

    def search_nodes(self, query: str, limit: int = 10) -> list[NodeInfo] | None:
        """Search for nodes in the registry.

        Args:
            query: Search term
            limit: Maximum results

        Returns:
            List of matching NodeInfo objects or None
        """
        try:
            nodes = self.registry_client.search_nodes(query)
            if nodes:
                return [NodeInfo.from_registry_node(node) for node in nodes[:limit]]
        except CDRegistryError as e:
            logger.warning(f"Failed to search registry: {e}")
        return None
