"""Deep conflict analysis for UV dependency conflicts.

This module provides detailed analysis of dependency conflicts, including:
- Parsing UV error output to identify conflicting packages
- Tracing dependency chains using uv pip tree and uv pip compile
- Generating user-friendly reports with actionable suggestions
- Checking specifier compatibility using UV's resolver
"""

import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from packaging.utils import canonicalize_name

from ..logging.logging_config import get_logger

logger = get_logger(__name__)

# Timeout for UV subprocess calls (seconds)
UV_TIMEOUT = 30


def normalize_package_name_pep503(name: str) -> str:
    """Normalize package name per PEP 503.

    Uses packaging.utils.canonicalize_name which implements the official PEP 503
    normalization: converts to lowercase and replaces runs of separators (-, _, .)
    with single dashes.

    Args:
        name: Package name to normalize

    Returns:
        Normalized package name (e.g., "Hugging_Face.Hub" -> "hugging-face-hub")
    """
    return canonicalize_name(name)


def parse_constraint_string(constraint: str) -> tuple[str, str] | None:
    """Parse a constraint string into package name and version specifier.

    Args:
        constraint: Constraint string like "huggingface_hub<0.37" or "attrs>=17.3.0"

    Returns:
        Tuple of (normalized_package_name, version_specifier) or None if invalid
    """
    constraint = constraint.strip()
    match = re.match(r"^([a-zA-Z0-9._-]+)(.*)$", constraint)
    if not match:
        return None

    pkg_name = normalize_package_name_pep503(match.group(1))
    version_spec = match.group(2).strip()

    if not version_spec:
        return None

    # Skip wildcard constraints like "pkg *" which aren't valid specifiers for UV compile.
    if version_spec == "*":
        return None

    return pkg_name, version_spec


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


def get_existing_requirements(
    pkg: str,
    venv_python: Path,
    uv_path: Path,
) -> list[tuple[str, str]]:
    """Get existing packages that directly require the specified package.

    Uses: uv pip tree --python {venv} --invert --show-version-specifiers --package {pkg}

    Only returns first-level dependents (not nested transitive dependencies).

    Args:
        pkg: Package name to query
        venv_python: Path to the Python executable in the venv
        uv_path: Path to the UV binary

    Returns:
        List of (requiring_package_name, requirement_spec) tuples.
        The requirement_spec includes the package name (e.g., "huggingface-hub>=1.1.0").
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
            timeout=UV_TIMEOUT,
        )

        if result.returncode != 0:
            logger.debug(f"uv pip tree failed for {pkg}: {result.stderr}")
            return []

        requirements = []
        # Parse output like:
        # huggingface-hub v1.1.0
        # └── comfygit-core v0.3.13 [requires: huggingface-hub>=1.1.0]
        #     └── nested-pkg v1.0.0 [requires: comfygit-core>=0.3.0]  <- skip nested
        #
        # Use ^ anchor to only match first-level dependents (no leading spaces)
        req_pattern = r"^[└├]── (\S+) v[^\s]+ \[requires: ([^\]]+)\]"
        for match in re.finditer(req_pattern, result.stdout, re.MULTILINE):
            pkg_name = match.group(1)
            requirement_spec = match.group(2)
            # Skip wildcard specs like "pkg *" - they mean "any version" and
            # aren't valid for uv pip compile.
            #
            # Note: Do not skip valid PEP 440 wildcards like "pkg==1.2.*".
            if re.fullmatch(r"[a-zA-Z0-9._-]+\s+\*", requirement_spec.strip()):
                continue
            requirements.append((pkg_name, requirement_spec))

        return requirements

    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.debug(f"Failed to get existing requirements for {pkg}: {e}")
        return []


# Keep old name as alias for backwards compatibility within this module
_get_existing_requirements = get_existing_requirements


def check_specifier_compatibility(
    existing_spec: str,
    new_spec: str,
    venv_python: Path | None,
    uv_path: Path,
) -> tuple[bool, str]:
    """Check if two version specifiers for the same package are compatible.

    Uses UV's resolver to check if both constraints can be satisfied simultaneously.

    Args:
        existing_spec: Full requirement spec from environment (e.g., "huggingface-hub>=1.1.0")
        new_spec: New requirement spec to check (e.g., "huggingface-hub<0.37")
        uv_path: Path to UV binary

    Returns:
        Tuple of (is_compatible, error_message).
        If compatible, returns (True, "").
        If incompatible, returns (False, stderr_from_uv).
    """
    # Combine both specs - UV will try to find a version satisfying both
    combined_reqs = f"{existing_spec}\n{new_spec}"

    try:
        cmd = [str(uv_path), "pip", "compile", "--no-deps", "--quiet"]
        if venv_python:
            cmd.extend(["--python", str(venv_python)])
        cmd.append("-")

        result = subprocess.run(
            cmd,
            input=combined_reqs,
            capture_output=True,
            text=True,
            timeout=UV_TIMEOUT,
        )

        if result.returncode == 0:
            return True, ""

        # Only treat true unsatisfiable resolutions as incompatibilities.
        # Other failures (network, index auth, transient errors) should not
        # block node installation via false positives.
        stderr = (result.stderr or result.stdout or "").strip()
        stderr_lower = stderr.lower()
        if "unsatisfiable" in stderr_lower or "no solution found" in stderr_lower:
            return False, stderr

        logger.debug(
            "UV compile failed but did not look like an incompatibility: "
            f"{existing_spec} vs {new_spec} ({stderr})"
        )
        return True, ""

    except subprocess.TimeoutExpired:
        logger.debug(f"Timeout checking compatibility: {existing_spec} vs {new_spec}")
        # On timeout, assume compatible to avoid false positives
        return True, ""
    except FileNotFoundError as e:
        logger.debug(f"UV not found: {e}")
        return True, ""


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


def _generate_suggestions(analysis: ConflictAnalysis) -> list[str]:
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
    analysis.suggestions = _generate_suggestions(analysis)

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
