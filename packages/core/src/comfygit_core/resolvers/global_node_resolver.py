"""Global node resolver using prebuilt mappings."""

from __future__ import annotations

import re

from comfygit_core.models.workflow import (
    NodeResolutionContext,
    ResolvedNodePackage,
    ScoredPackageMatch,
    WorkflowNode,
)

from ..logging.logging_config import get_logger
from ..repositories.node_mappings_repository import NodeMappingsRepository
from ..utils.input_signature import create_node_key, normalize_workflow_inputs

logger = get_logger(__name__)

BUILTIN_CNR_IDS = {"comfy-core"}


class GlobalNodeResolver:
    """Resolves unknown nodes using global mappings repository.

    This class is responsible for resolution logic only - data access
    is delegated to NodeMappingsRepository.
    """

    def __init__(self, repository: NodeMappingsRepository):
        """Initialize resolver with repository.

        Args:
            repository: NodeMappingsRepository for data access
        """
        self.repository = repository

    # Convenience properties for backward compatibility
    @property
    def global_mappings(self):
        """Access global mappings from repository."""
        return self.repository.global_mappings

    def resolve_github_url(self, github_url: str):
        """Resolve GitHub URL to registry package."""
        return self.repository.resolve_github_url(github_url)

    def get_github_url_for_package(self, package_id: str) -> str | None:
        """Get GitHub URL for a package ID."""
        return self.repository.get_github_url_for_package(package_id)

    def resolve_single_node_from_mapping(self, node: WorkflowNode) -> list[ResolvedNodePackage] | None:
        """Resolve a single node type using global mappings.

        Returns all ranked packages for this node from the registry.
        Packages are sorted by rank (1 = most popular).
        """
        mappings = self.repository.global_mappings.mappings
        packages = self.repository.global_mappings.packages

        node_type = node.type
        inputs = node.inputs

        # Strategy 1: Try exact match with input signature
        if inputs:
            input_signature = normalize_workflow_inputs(inputs)
            logger.debug(f"Input signature for {node_type}: {input_signature}")
            if input_signature:
                exact_key = create_node_key(node_type, input_signature)
                logger.debug(f"Exact key for {node_type}: {exact_key}")
                if exact_key in mappings:
                    mapping = mappings[exact_key]
                    logger.debug(f"Exact match for {node_type}: {len(mapping.packages)} package(s)")

                    # Empty packages list = not found
                    if not mapping.packages:
                        return None

                    # Return ALL packages from this mapping, sorted by rank
                    resolved_packages = []
                    for pkg_mapping in sorted(mapping.packages, key=lambda x: x.rank):
                        pkg_data = packages.get(pkg_mapping.package_id)
                        resolved_packages.append(ResolvedNodePackage(
                            package_id=pkg_mapping.package_id,
                            package_data=pkg_data,
                            node_type=node_type,
                            versions=pkg_mapping.versions,
                            match_type="exact",
                            match_confidence=1.0,
                            rank=pkg_mapping.rank,
                            source=pkg_mapping.source or (pkg_data.source if pkg_data else None)
                        ))

                    return resolved_packages

        # Strategy 2: Try type-only match
        type_only_key = create_node_key(node_type, "_")
        if type_only_key in mappings:
            mapping = mappings[type_only_key]
            logger.debug(f"Type-only match for {node_type}: {len(mapping.packages)} package(s)")

            # Empty packages list = not found
            if not mapping.packages:
                return None

            # Return ALL packages from this mapping, sorted by rank
            resolved_packages = []
            for pkg_mapping in sorted(mapping.packages, key=lambda x: x.rank):
                pkg_data = packages.get(pkg_mapping.package_id)
                resolved_packages.append(ResolvedNodePackage(
                    package_id=pkg_mapping.package_id,
                    package_data=pkg_data,
                    node_type=node_type,
                    versions=pkg_mapping.versions,
                    match_type="type_only",
                    match_confidence=0.9,
                    rank=pkg_mapping.rank,
                    source=pkg_mapping.source or (pkg_data.source if pkg_data else None)
                ))

            return resolved_packages

        logger.debug(f"No match found for {node_type}")
        return None

    def resolve_single_node_with_context(
        self,
        node: WorkflowNode,
        context: NodeResolutionContext | None = None
    ) -> list[ResolvedNodePackage] | None:
        """Enhanced resolution with context awareness.

        Resolution priority:
        1. Custom mappings from pyproject
        2. Properties field (cnr_id from workflow)
        3. Global mapping table (existing logic)
        4. None (trigger interactive resolution)

        Args:
            node: WorkflowNode to resolve
            context: Optional resolution context for caching and custom mappings

        Returns:
            List of resolved packages, empty list for skip, or None for unresolved
        """
        node_type = node.type

        # Priority 1: Custom mappings
        if context and node_type in context.custom_mappings:
            mapping = context.custom_mappings[node_type]
            if isinstance(mapping, bool):  # Node marked as optional
                logger.debug(f"Found optional {node_type} (user-configured optional)")
                return [
                    ResolvedNodePackage(
                        node_type=node_type,
                        is_optional=True,
                        match_type="custom_mapping"
                    )
                ]
            assert isinstance(mapping, str)  # Should be Package ID
            logger.debug(f"Custom mapping for {node_type}: {mapping}")
            return [self._create_resolved_package_from_id(mapping, node_type, "custom_mapping")]

        # Priority 2: Properties field (cnr_id from ComfyUI)
        raw_cnr_id = node.properties.get('cnr_id') if node.properties else None
        ver = node.properties.get('ver') if node.properties else None
        cnr_id = self.repository.canonicalize_package_id(raw_cnr_id)

        if cnr_id:
            logger.debug(f"Found cnr_id in properties: {raw_cnr_id} -> {cnr_id} @ {ver}")

            # Builtins are never superseded by registry mappings.
            # package_data=None is fine — downstream falls back to package_id.
            if cnr_id in BUILTIN_CNR_IDS:
                return [ResolvedNodePackage(
                    package_id=cnr_id,
                    package_data=None,
                    node_type=node_type,
                    versions=[ver] if ver else [],
                    match_type="properties",
                    match_confidence=1.0
                )]

            # Canonical cnr_id wins when it resolves to known package metadata.
            pkg_data = self.repository.get_package(cnr_id)
            if pkg_data:
                return [ResolvedNodePackage(
                    package_id=cnr_id,
                    package_data=pkg_data,
                    node_type=node_type,
                    versions=[ver] if ver else [],
                    match_type="properties",
                    match_confidence=1.0,
                    source=pkg_data.source if pkg_data else None
                )]
            logger.warning(f"cnr_id {raw_cnr_id} (canonical: {cnr_id}) from properties not in registry")

        # Priority 3: Global table (existing logic)
        result = self.resolve_single_node_from_mapping(node)
        if result:
            result = self._prefer_installable_candidates(result)
            # Apply auto-selection logic if enabled and multiple packages found
            if context and context.auto_select_ambiguous and len(result) > 1:
                selected = self._auto_select_best_package(result, context.installed_packages)
                return [selected]
            return result

        # Priority 4: No match - return None to trigger interactive strategy with unified search
        logger.debug(f"No resolution found for {node_type} - will use interactive strategy")
        return None

    def _auto_select_best_package(
        self,
        packages: list[ResolvedNodePackage],
        installed_packages: dict
    ) -> ResolvedNodePackage:
        """Auto-select best package from ranked list based on installed state.

        Selection priority:
        1. If any packages are installed, pick the one with best (lowest) rank
        2. If none installed, pick rank 1 (most popular)

        Args:
            packages: List of ranked packages from registry
            installed_packages: Dict of installed packages {package_id: NodeInfo}

        Returns:
            Single best package
        """
        # Find installed packages from the candidates
        installed_candidates = [
            pkg for pkg in packages
            if pkg.package_id in installed_packages
        ]

        if installed_candidates:
            # Pick installed package with best rank (lowest number)
            best = min(installed_candidates, key=lambda x: x.rank or 999)
            logger.debug(
                f"Auto-selected {best.package_id} (rank {best.rank}, installed) "
                f"over {len(packages)-1} other option(s)"
            )
            return best

        # No installed packages - pick rank 1 (most popular)
        best = min(packages, key=lambda x: x.rank or 999)
        logger.debug(
            f"Auto-selected {best.package_id} (rank {best.rank}, most popular) "
            f"from {len(packages)} option(s)"
        )
        return best

    def _create_resolved_package_from_id(
        self,
        pkg_id: str,
        node_type: str,
        match_type: str
    ) -> ResolvedNodePackage:
        """Create ResolvedNodePackage from package ID.

        Args:
            pkg_id: Package ID to create package for
            node_type: Node type being resolved
            match_type: Type of match (session_cache, custom_mapping, properties, etc.)

        Returns:
            ResolvedNodePackage instance
        """
        canonical_pkg_id = self.repository.canonicalize_package_id(pkg_id) or pkg_id
        pkg_data = self.repository.get_package(canonical_pkg_id)

        return ResolvedNodePackage(
            package_id=canonical_pkg_id,
            package_data=pkg_data,
            node_type=node_type,
            versions=[],
            match_type=match_type,
            match_confidence=1.0,
            source=pkg_data.source if pkg_data else None
        )

    def _prefer_installable_candidates(
        self,
        packages: list[ResolvedNodePackage]
    ) -> list[ResolvedNodePackage]:
        """Filter manager-only empty-version candidates when installable options exist."""
        installable = [
            pkg for pkg in packages
            if not pkg.is_manager_only_uninstallable
        ]
        if installable:
            if len(installable) != len(packages):
                logger.debug(
                    "Filtered %s manager-only uninstallable candidate(s)",
                    len(packages) - len(installable)
                )
            return installable
        return packages

    def search_packages(
        self,
        node_type: str,
        installed_packages: dict = None,
        include_registry: bool = True,
        limit: int = 10
    ) -> list[ScoredPackageMatch]:
        """Unified search with heuristic boosting.

        Combines fuzzy matching with hint pattern detection to rank packages.
        Installed packages receive priority boosting.

        Args:
            node_type: Node type to search for
            installed_packages: Already installed packages (prioritized)
            include_registry: Also search full registry
            limit: Maximum results

        Returns:
            Scored matches sorted by relevance (highest first)
        """

        if installed_packages is None:
            installed_packages = {}
        if not node_type:
            return []

        scored = []
        node_type_lower = node_type.lower()

        # Build candidate pool
        candidates = {}

        # Phase 1: Installed packages (always checked first)
        for pkg_id in installed_packages.keys():
            pkg_data = self.repository.get_package(pkg_id)
            if pkg_data:
                candidates[pkg_id] = (pkg_data, True)  # True = installed

        # Phase 2: Registry packages
        if include_registry:
            for pkg_id, pkg_data in self.repository.get_all_packages().items():
                if pkg_id not in candidates:
                    candidates[pkg_id] = (pkg_data, False)  # False = not installed

        # Score each candidate
        for pkg_id, (pkg_data, is_installed) in candidates.items():
            score = self._calculate_match_score(
                node_type=node_type,
                node_type_lower=node_type_lower,
                pkg_id=pkg_id,
                pkg_data=pkg_data,
                is_installed=is_installed
            )

            if score > 0.3:  # Minimum threshold
                confidence = self._score_to_confidence(score)
                scored.append(ScoredPackageMatch(
                    package_id=pkg_id,
                    package_data=pkg_data,
                    score=score,
                    confidence=confidence
                ))

        # Sort by (score, stars) descending - stars act as tiebreaker for similar scores
        scored.sort(key=lambda x: (x.score, x.package_data.github_stars or 0), reverse=True)
        return scored[:limit]

    def _calculate_match_score(
        self,
        node_type: str,
        node_type_lower: str,
        pkg_id: str,
        pkg_data,
        is_installed: bool
    ) -> float:
        """Calculate comprehensive match score with bonuses.

        Scoring pipeline:
        1. Base fuzzy score (SequenceMatcher)
        2. Keyword overlap bonus
        3. Hint pattern bonuses (heuristics!)
        4. Installed package bonus
        5. Popularity bonus (GitHub stars on log scale)
        """
        from difflib import SequenceMatcher

        pkg_id_lower = pkg_id.lower()

        # 1. Base fuzzy score (ID and display name only)
        base_score = SequenceMatcher(None, node_type_lower, pkg_id_lower).ratio()

        # Also check display name
        if pkg_data.display_name:
            name_score = SequenceMatcher(
                None, node_type_lower, pkg_data.display_name.lower()
            ).ratio()
            base_score = max(base_score, name_score)

        # 2. Keyword overlap bonus (ID, display name, AND description for better recall)
        # Split on underscores, hyphens, and whitespace to extract individual keywords
        node_keywords = set(re.findall(r'[a-z0-9]+', node_type_lower))
        pkg_keywords = set(re.findall(r'[a-z0-9]+', pkg_id_lower))
        if pkg_data.display_name:
            pkg_keywords.update(re.findall(r'[a-z0-9]+', pkg_data.display_name.lower()))

        # Add description keywords but with limited weight
        desc_keywords = set()
        if pkg_data.description:
            desc_keywords = set(re.findall(r'[a-z0-9]+', pkg_data.description.lower()))

        # Calculate overlap for ID/name vs description separately
        id_overlap = len(node_keywords & pkg_keywords) / max(len(node_keywords), 1)
        desc_overlap = len(node_keywords & desc_keywords) / max(len(node_keywords), 1)

        # Combine with weighted importance:
        # - ID/name match is primary (0.50 max bonus - increased to dominate over fuzzy)
        # - Description match is secondary boost (0.15 max bonus)
        keyword_bonus = (id_overlap * 0.50) + (desc_overlap * 0.15)

        # 3. Hint pattern bonuses (THE HEURISTICS!)
        hint_bonus = self._detect_hint_patterns(node_type, pkg_id_lower)

        # 4. Installed package bonus
        installed_bonus = 0.10 if is_installed else 0.0

        # 5. Popularity bonus (log scale to prevent overwhelming text relevance)
        # 10 stars → 0.01, 100 stars → 0.02, 1000 stars → 0.03, 10000 stars → 0.04
        import math
        popularity_bonus = 0.0
        if pkg_data.github_stars and pkg_data.github_stars > 0:
            popularity_bonus = math.log10(pkg_data.github_stars) * 0.1

        # Combine - don't cap at 1.0 so popularity can differentiate high-scoring packages
        final_score = base_score + keyword_bonus + hint_bonus + installed_bonus + popularity_bonus
        return final_score

    def _detect_hint_patterns(
        self,
        node_type: str,
        pkg_id_lower: str
    ) -> float:
        """Detect hint patterns and return bonus score.

        This is where heuristics live - as score boosters!
        These bonuses are now more conservative to prevent score inflation.
        """
        max_bonus = 0.0

        # Pattern 1: Parenthetical/Bracket hint (STRONG signal)
        # "Node Name (package)" → "package" OR "Node Name [package]" → "package"
        for open_char, close_char in [("(", ")"), ("[", "]")]:
            if open_char in node_type and close_char in node_type:
                hint = node_type.split(open_char)[-1].rstrip(close_char).strip().lower()
                if len(hint) >= 3:  # Minimum length to avoid false positives
                    if hint == pkg_id_lower:
                        max_bonus = max(max_bonus, 0.50)  # Exact match
                    elif hint in pkg_id_lower:
                        max_bonus = max(max_bonus, 0.40)  # Substring match

        # Pattern 2: Pipe separator
        # "Node Name | PackageName" → "PackageName"
        if "|" in node_type:
            parts = node_type.split("|")
            if len(parts) == 2:
                hint = parts[1].strip().lower()
                if hint in pkg_id_lower:
                    max_bonus = max(max_bonus, 0.35)  # Reduced from 0.55

        # Pattern 3: Dash/Colon separator
        # "Node Name - Package" or "Node: Package"
        for sep in [" - ", ": "]:
            if sep in node_type:
                parts = node_type.split(sep)
                if len(parts) >= 2:
                    hint = parts[-1].strip().lower()
                    if len(hint) >= 3 and hint in pkg_id_lower:
                        max_bonus = max(max_bonus, 0.30)  # Reduced from 0.50
                        break

        # Pattern 4: Fragment match (weakest) - removed to reduce noise
        # This was adding too many false positives

        return max_bonus

    def _score_to_confidence(self, score: float) -> str:
        """Convert numeric score to confidence label."""
        if score >= 0.85:
            return "high"
        elif score >= 0.65:
            return "good"
        elif score >= 0.45:
            return "possible"
        else:
            return "low"
