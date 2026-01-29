"""Deep conflict analysis for UV dependency conflicts.

This module provides detailed analysis of dependency conflicts, including:
- Parsing UV error output to identify conflicting packages
- Tracing dependency chains using uv pip tree and uv pip compile
- Generating user-friendly reports with actionable suggestions
"""

import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from ..logging.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class ConflictChain:
    """A dependency chain leading to a conflicting package."""

    root_package: str  # e.g., "depthflow"
    chain: list[str]  # e.g., ["depthflow", "transformers", "huggingface-hub"]
    constraint: str | None  # e.g., "huggingface-hub<1.0,>=0.30.0"
    constraint_source: str  # Package that imposes the constraint


@dataclass
class ConflictAnalysis:
    """Complete analysis of a dependency conflict."""

    conflicting_package: str  # e.g., "huggingface-hub"
    existing_constraints: list[tuple[str, str]]  # [(pkg, constraint), ...]
    new_package_chains: list[ConflictChain] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


def parse_conflict_from_stderr(stderr: str) -> tuple[str | None, list[dict]]:
    """Parse UV error output to extract conflicting package and constraints.

    Args:
        stderr: UV error output

    Returns:
        Tuple of (conflicting_package_name, list of constraint dicts)
        Returns (None, []) if no conflict detected
    """
    if not stderr:
        return None, []

    constraints = []

    # Pattern: "X depends on Y<version,>=version" or "X requires Y>=version"
    # Looking for the package that appears in multiple constraints
    dep_pattern = r"(\S+)==[\d\.]+ (?:depends on|requires) (\S+?)([<>=!~].+?)(?:\s|$)"
    matches = list(re.finditer(dep_pattern, stderr))

    if not matches:
        # Try alternate pattern for "requires" without version on source
        dep_pattern2 = r"(\S+) requires (\S+?)([<>=!~][^\s\n]+)"
        matches = list(re.finditer(dep_pattern2, stderr))

    # Count package occurrences to find the conflicting one
    pkg_counts: dict[str, int] = defaultdict(int)
    for match in matches:
        source_pkg = match.group(1).split("==")[0]
        target_pkg = match.group(2).rstrip("<>=!~,")
        constraint_str = match.group(2) + match.group(3)

        pkg_counts[target_pkg] += 1
        constraints.append({
            "source": source_pkg,
            "package": target_pkg,
            "constraint": constraint_str,
        })

    # The conflicting package is the one mentioned multiple times
    if pkg_counts:
        conflicting_pkg = max(pkg_counts, key=lambda k: pkg_counts[k])
        if pkg_counts[conflicting_pkg] >= 2:
            return conflicting_pkg, constraints

    # Fallback: look for explicit conflict statement
    conflict_pattern = r"(\S+)==[\d\.]+ and (\S+)==[\d\.]+ are incompatible"
    match = re.search(conflict_pattern, stderr)
    if match:
        # Return first package as conflicting (arbitrary but consistent)
        return match.group(1).split("==")[0], constraints

    return None, []


def _get_existing_requirements(
    pkg: str,
    venv_python: Path,
    uv_path: Path,
) -> list[tuple[str, str]]:
    """Get existing packages that require the conflicting package.

    Uses: uv pip tree --python {venv} --invert --show-version-specifiers --package {pkg}

    Returns:
        List of (package_name, constraint) tuples
    """
    try:
        result = subprocess.run(
            [
                str(uv_path),
                "pip",
                "tree",
                "--python",
                str(venv_python),
                "--invert",
                "--show-version-specifiers",
                "--package",
                pkg,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            logger.debug(f"uv pip tree failed: {result.stderr}")
            return []

        requirements = []
        # Parse output like:
        # huggingface-hub v1.1.0
        # └── comfygit-core v0.3.13 [requires: huggingface-hub>=1.1.0]
        req_pattern = r"[└├]── (\S+) v[\d.]+ \[requires: ([^\]]+)\]"
        for match in re.finditer(req_pattern, result.stdout):
            pkg_name = match.group(1)
            constraint = match.group(2)
            requirements.append((pkg_name, constraint))

        return requirements

    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.debug(f"Failed to get existing requirements: {e}")
        return []


def _get_new_package_chains(
    new_pkg: str,
    target: str,
    uv_path: Path,
) -> list[ConflictChain]:
    """Trace how the new package depends on the conflicting package.

    Uses: echo "{new_pkg}" | uv pip compile --annotation-style=line -

    Returns:
        List of ConflictChain objects showing paths from new_pkg to target
    """
    try:
        result = subprocess.run(
            [
                str(uv_path),
                "pip",
                "compile",
                "--annotation-style=line",
                "-",
            ],
            input=new_pkg,
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            logger.debug(f"uv pip compile failed: {result.stderr}")
            return []

        # Build dependency graph from annotations
        # Format:
        # package==version
        #     # via other-package
        graph: dict[str, list[str]] = defaultdict(list)
        current_pkg = None

        for line in result.stdout.split("\n"):
            line = line.strip()
            if not line:
                continue

            # Check for "# via" annotation BEFORE skipping general comments
            if line.startswith("# via"):
                # Dependency annotation
                via_pkgs = line.replace("# via", "").strip()
                if via_pkgs == "-r -":
                    # Direct requirement
                    via_pkgs = new_pkg.split("==")[0]

                for via in via_pkgs.split(","):
                    via = via.strip().lower()
                    if via and current_pkg:
                        graph[via].append(current_pkg)
            elif line.startswith("#"):
                # Skip other comments
                continue
            elif "==" in line:
                # Package line
                current_pkg = line.split("==")[0].lower()

        # BFS to find all paths from root to target
        chains = []
        target_lower = target.lower()
        root = new_pkg.split("==")[0].lower()

        if target_lower not in graph.values() and target_lower not in [
            item for sublist in graph.values() for item in sublist
        ]:
            return []

        # BFS for shortest path
        queue = [(root, [root])]
        visited = {root}

        while queue:
            node, path = queue.pop(0)

            if node == target_lower:
                # Find the constraint source (second to last in chain)
                constraint_source = path[-2] if len(path) > 1 else root
                chains.append(
                    ConflictChain(
                        root_package=root,
                        chain=path,
                        constraint=None,  # Could be extracted from compile output
                        constraint_source=constraint_source,
                    )
                )
                continue

            for neighbor in graph.get(node, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))

        return chains

    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.debug(f"Failed to trace new package chains: {e}")
        return []


def _generate_suggestions(
    analysis: ConflictAnalysis,
    stderr: str,
) -> list[str]:
    """Generate actionable suggestions based on the conflict analysis."""
    suggestions = []

    if analysis.new_package_chains:
        chain = analysis.new_package_chains[0]
        if len(chain.chain) > 2:
            intermediate = chain.chain[-2]  # Package before the conflict
            suggestions.append(
                f"Check if a newer version of '{intermediate}' supports "
                f"'{analysis.conflicting_package}' at the required version"
            )
            suggestions.append(
                f"Add to pyproject.toml [tool.uv]: "
                f"override-dependencies = [\"{intermediate}>=<newer-version>\"]"
            )

    if analysis.existing_constraints:
        for pkg, _ in analysis.existing_constraints:
            suggestions.append(
                f"Contact the maintainer of '{pkg}' to relax the "
                f"'{analysis.conflicting_package}' constraint"
            )

    return suggestions


def analyze_conflict(
    stderr: str,
    new_package: str,
    venv_python: Path | None = None,
    uv_path: Path | None = None,
) -> ConflictAnalysis | None:
    """Analyze a UV dependency conflict.

    Args:
        stderr: UV error output
        new_package: The package being installed (e.g., "depthflow==0.9.1")
        venv_python: Path to environment's Python (for uv pip tree)
        uv_path: Path to uv executable

    Returns:
        ConflictAnalysis with chains and suggestions, or None if not a conflict error
    """
    conflicting_pkg, constraints = parse_conflict_from_stderr(stderr)

    if not conflicting_pkg:
        return None

    # Extract constraints from parsed data
    existing_constraints: list[tuple[str, str]] = []
    for c in constraints:
        if c["package"] == conflicting_pkg:
            existing_constraints.append((c["source"], c["constraint"]))

    new_package_chains: list[ConflictChain] = []

    # Run deeper analysis if we have venv and uv
    if venv_python and uv_path:
        # Get what existing packages require this dep
        tree_requirements = _get_existing_requirements(
            conflicting_pkg, venv_python, uv_path
        )
        if tree_requirements:
            existing_constraints = tree_requirements

        # Trace how new package depends on conflicting pkg
        new_package_chains = _get_new_package_chains(
            new_package, conflicting_pkg, uv_path
        )

    analysis = ConflictAnalysis(
        conflicting_package=conflicting_pkg,
        existing_constraints=existing_constraints,
        new_package_chains=new_package_chains,
        suggestions=[],
    )

    # Generate suggestions
    analysis.suggestions = _generate_suggestions(analysis, stderr)

    return analysis


def format_conflict_report(analysis: ConflictAnalysis) -> str:
    """Format analysis as user-friendly report.

    Args:
        analysis: The conflict analysis to format

    Returns:
        Formatted multi-line report string
    """
    lines = [
        "=" * 60,
        "DEPENDENCY CONFLICT ANALYSIS",
        "=" * 60,
        "",
        f"Conflicting package: {analysis.conflicting_package}",
        "",
    ]

    if analysis.existing_constraints:
        lines.append("EXISTING environment requires:")
        for pkg, constraint in analysis.existing_constraints:
            lines.append(f"  {pkg} [requires: {constraint}]")
        lines.append("")

    if analysis.new_package_chains:
        lines.append("NEW package would install:")
        for chain in analysis.new_package_chains:
            chain_str = " → ".join(chain.chain)
            lines.append(f"  {chain_str}")
            if chain.constraint:
                lines.append(
                    f"  └─ {chain.constraint_source} requires: {chain.constraint}"
                )
        lines.append("")

    if analysis.suggestions:
        lines.append("SOLUTIONS:")
        for i, suggestion in enumerate(analysis.suggestions, 1):
            lines.append(f"  {i}. {suggestion}")
        lines.append("")

    lines.append("=" * 60)

    return "\n".join(lines)
