"""UV dependency conflict parsing utilities.

This module provides utilities for parsing and simplifying UV (uv) package manager
error messages, particularly dependency conflicts.
"""

import re

from ..logging.logging_config import get_logger

logger = get_logger(__name__)


def parse_uv_conflicts(error_text: str, max_lines: int = 3) -> list[str]:
    """Extract specific conflict messages from UV error output.

    Looks for patterns like:
    - "X and Y are incompatible"
    - "X depends on Y but Z needs different version"
    - Conclusion statements about incompatibilities

    Args:
        error_text: Raw UV error output
        max_lines: Maximum number of conflict messages to return

    Returns:
        List of simplified conflict messages
    """
    conflicts = []

    if not error_text:
        return conflicts

    # Pattern: "X and Y are incompatible"
    incompatible_pattern = r"(\S+) and (\S+) are incompatible"
    for match in re.finditer(incompatible_pattern, error_text):
        pkg1, pkg2 = match.groups()
        # Clean up package names (remove version specs)
        pkg1_clean = _clean_package_name(pkg1)
        pkg2_clean = _clean_package_name(pkg2)
        conflicts.append(f"{pkg1_clean} conflicts with {pkg2_clean}")

    # Pattern: "X depends on Y but Z needs different version"
    depends_pattern = r"(\S+) depends on (\S+)"
    dependencies = {}
    for match in re.finditer(depends_pattern, error_text):
        pkg, dep = match.groups()
        if pkg not in dependencies:
            dependencies[pkg] = []
        dependencies[pkg].append(dep)

    # If we found specific conflicts, use those
    if conflicts:
        return conflicts[:max_lines]  # Limit to top 3 for brevity

    # Otherwise, try to extract conclusion lines
    lines = error_text.split('\n')
    for line in lines:
        line = line.strip()
        # Skip empty lines and hints
        if not line or line.startswith('hint:'):
            continue
        # Look for conclusion lines
        if 'conclude that' in line and 'incompatible' in line:
            # Extract the key part
            if 'we can conclude that' in line:
                conclusion = line.split('we can conclude that')[1].strip()
                conflicts.append(conclusion)

    return conflicts[:max_lines]  # Limit output


def parse_uv_resolution(output: str | None) -> dict[str, str]:
    """Parse UV resolution output to extract package versions.

    Args:
        output: UV resolution output text

    Returns:
        Dict mapping package names to resolved versions
    """
    packages = {}

    if not output:
        return packages

    # UV resolution output format varies, this is a simplified parser
    # Look for patterns like: package==version
    for line in output.split('\n'):
        line = line.strip()
        if '==' in line:
            parts = line.split('==')
            if len(parts) == 2:
                name = parts[0].strip()
                version = parts[1].strip()
                # Clean up the name (remove any prefixes)
                name = _clean_package_name(name)
                packages[name] = version

    return packages


def simplify_conflict_message(full_error: str, max_lines: int = 3) -> list[str]:
    """Simplify a full UV conflict error into user-friendly messages.

    Args:
        full_error: Complete UV error message
        max_lines: Maximum number of simplified messages to return

    Returns:
        List of simplified, user-friendly conflict descriptions
    """
    # First try to parse specific conflicts
    conflicts = parse_uv_conflicts(full_error)
    if conflicts:
        return conflicts[:max_lines]

    # If no specific conflicts found, extract key error lines
    simplified = []
    key_phrases = [
        "incompatible",
        "conflict",
        "cannot satisfy",
        "no solution found",
        "requires",
        "depends on"
    ]

    lines = full_error.split('\n')
    for line in lines:
        line = line.strip()
        if any(phrase in line.lower() for phrase in key_phrases):
            # Remove UV-specific prefixes
            line = _clean_error_line(line)
            if line and line not in simplified:
                simplified.append(line)
                if len(simplified) >= max_lines:
                    break

    return simplified


def extract_conflicting_packages(error_text: str) -> list[tuple[str, str]]:
    """Extract pairs of conflicting packages from UV error.

    Args:
        error_text: UV error output

    Returns:
        List of tuples (package1, package2) that conflict
    """
    pairs = []

    # Look for explicit incompatibility statements
    pattern = r"(\S+)==[\d\.]+ and (\S+)==[\d\.]+ are incompatible"
    for match in re.finditer(pattern, error_text):
        pkg1 = _clean_package_name(match.group(1))
        pkg2 = _clean_package_name(match.group(2))
        pairs.append((pkg1, pkg2))

    # Look for version conflict patterns
    pattern = r"(\S+) requires (\S+)==[\d\.]+.*but.*(\S+) requires (\S+)==[\d\.]+"
    for match in re.finditer(pattern, error_text):
        # This pattern suggests pkg1 and pkg3 have conflicting requirements for pkg2/pkg4
        pkg1 = _clean_package_name(match.group(1))
        pkg3 = _clean_package_name(match.group(3))
        if pkg1 != pkg3:
            pairs.append((pkg1, pkg3))

    # Remove duplicates while preserving order
    seen = set()
    unique_pairs = []
    for pair in pairs:
        # Normalize order (alphabetical)
        normalized = tuple(sorted(pair))
        if normalized not in seen:
            seen.add(normalized)
            unique_pairs.append(pair)

    return unique_pairs


def _clean_package_name(name: str) -> str:
    """Clean up a package name by removing version specs and extras.

    Args:
        name: Raw package name (might include version specs)

    Returns:
        Clean package name
    """
    # Remove version specifiers
    for sep in ['==', '>=', '<=', '>', '<', '~=', '!=']:
        if sep in name:
            name = name.split(sep)[0]

    # Remove extras [extra1,extra2]
    if '[' in name:
        name = name.split('[')[0]

    # Remove any remaining whitespace
    return name.strip()


def _clean_error_line(line: str) -> str:
    """Clean up an error line for display.

    Args:
        line: Raw error line

    Returns:
        Cleaned error line
    """
    # Remove common UV prefixes
    prefixes_to_remove = [
        "error:",
        "Error:",
        "ERROR:",
        "  × ",
        "  │ ",
        "  ╰─▶ ",
    ]

    for prefix in prefixes_to_remove:
        if line.startswith(prefix):
            line = line[len(prefix):].strip()

    # Truncate very long lines
    if len(line) > 100:
        line = line[:97] + "..."

    return line
