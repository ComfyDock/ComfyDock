"""Requirements parsing utilities."""

import re
from pathlib import Path

import requirements
import tomlkit

from ..logging.logging_config import get_logger

logger = get_logger(__name__)

COMFYUI_RUNTIME_SUPPLEMENTAL_REQUIREMENTS = ("requests",)


def read_comfyui_requirements_with_supplements(requirements_path: Path) -> list[str]:
    """Read ComfyUI requirements and add runtime imports missing from older releases."""
    lines = _read_requirement_lines(requirements_path)
    present_packages = {
        package_name
        for package_name in (_extract_requirement_name(line) for line in lines)
        if package_name
    }

    for package in COMFYUI_RUNTIME_SUPPLEMENTAL_REQUIREMENTS:
        if package not in present_packages:
            lines.append(package)

    return lines


def _read_requirement_lines(requirements_path: Path) -> list[str]:
    if not requirements_path.exists():
        return []

    requirement_lines: list[str] = []
    with open(requirements_path, encoding="utf-8") as requirements_file:
        for line in requirements_file:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            if "#" in line:
                line = line.split("#", 1)[0].strip()
            if line:
                requirement_lines.append(line)
    return requirement_lines


def _extract_requirement_name(requirement: str) -> str | None:
    requirement = requirement.split(";", 1)[0].strip()
    if " @ " in requirement:
        requirement = requirement.split(" @ ", 1)[0].strip()

    match = re.match(r"^([A-Za-z0-9_.-]+)", requirement)
    if not match:
        return None

    return match.group(1).lower().replace("_", "-")


def parse_requirements_file(requirements_path: Path) -> dict[str, list[str]]:
    """Parse a requirements.txt file and return package requirements."""
    parsed_requirements = {}

    if not requirements_path.exists():
        return parsed_requirements

    try:
        with open(requirements_path, encoding='utf-8') as f:
            original_lines = f.readlines()

        # Try iterative parsing to isolate and remove problematic lines
        valid_lines = _get_valid_requirements_lines(original_lines, requirements_path)

        # Parse the valid lines
        if valid_lines:
            valid_content = '\n'.join(valid_lines)
            try:
                for req in requirements.parse(valid_content):
                    # Only process regular package requirements (not VCS, local files, etc.)
                    if req.name and req.specifier:
                        package_name = req.name.lower()

                        if package_name not in parsed_requirements:
                            parsed_requirements[package_name] = []

                        # Convert specs to version constraints
                        if req.specs:
                            # Join all version specs into a single constraint string
                            version_spec = ",".join([f"{op}{ver}" for op, ver in req.specs])
                            parsed_requirements[package_name].append(version_spec)
                        else:
                            parsed_requirements[package_name].append("")

                    elif req.name and not req.specifier:
                        # Package without version constraints
                        package_name = req.name.lower()
                        if package_name not in parsed_requirements:
                            parsed_requirements[package_name] = []
                        parsed_requirements[package_name].append("")

                    # Skip VCS requirements, local files, etc. - they'll be handled elsewhere
                    elif req.vcs or req.local_file or req.uri:
                        logger.debug(f"Skipping non-standard requirement: {req.line}")

            except Exception as e:
                logger.error(f"Failed to parse even filtered requirements from {requirements_path}: {e}")

    except Exception as e:
        logger.error(f"Error reading {requirements_path}: {e}")

    return parsed_requirements


def _get_valid_requirements_lines(original_lines: list[str], requirements_path: Path) -> list[str]:
    """
    Iteratively remove problematic lines from requirements until we can parse successfully.
    Returns a list of valid requirement lines.
    """
    # Start with all non-empty, non-comment lines
    candidate_lines = []
    for line in original_lines:
        line = line.strip()
        if line and not line.startswith('#') and not line.startswith('-'):
            candidate_lines.append(line)

    if not candidate_lines:
        return []

    max_attempts = len(candidate_lines)
    removed_lines = []

    for _ in range(max_attempts):
        try:
            # Try to parse current candidate lines
            test_content = '\n'.join(candidate_lines)
            list(requirements.parse_requirements_file(test_content))  # This will raise if there's an error

            # If we get here, parsing succeeded
            if removed_lines:
                logger.info(f"Successfully parsed {requirements_path} after removing {len(removed_lines)} problematic lines")
                for removed in removed_lines:
                    logger.debug(f"  Removed: {removed}")

            return candidate_lines

        except Exception:
            # Parse failed, try to identify the problematic line
            problematic_line = None

            # Try to extract line content from error message or find it by testing each line
            for i, line in enumerate(candidate_lines):
                try:
                    list(requirements.parse(line))
                except Exception:
                    # This line causes an error
                    problematic_line = line
                    candidate_lines.pop(i)
                    removed_lines.append(line)
                    logger.warning(f"Removed problematic requirement line: {line}")
                    break

            if problematic_line is None:
                # Couldn't identify the specific line, remove the first line and try again
                if candidate_lines:
                    removed_line = candidate_lines.pop(0)
                    removed_lines.append(removed_line)
                    logger.warning(f"Could not identify specific problematic line, removed: {removed_line}")
                else:
                    break

    # If we exhausted all attempts
    if removed_lines:
        logger.warning(f"Could not parse {requirements_path} even after removing all lines")

    return candidate_lines


def parse_pyproject_toml(pyproject_path: Path) -> dict | None:
    """Parse pyproject.toml file and extract project information."""
    try:
        with open(pyproject_path, encoding='utf-8') as f:
            data = tomlkit.load(f)

        # Extract project information
        project_info = {}

        # Check different possible locations for project metadata
        if 'project' in data:
            project = data['project']
            project_info['name'] = project.get('name', '')
            project_info['version'] = project.get('version', '')
            project_info['description'] = project.get('description', '')
            project_info['authors'] = project.get('authors', [])
            project_info['urls'] = project.get('urls', {})

        # Also check tool.poetry section (for Poetry projects)
        if 'tool' in data and 'poetry' in data['tool']:
            poetry = data['tool']['poetry']
            if not project_info.get('name'):
                project_info['name'] = poetry.get('name', '')
            if not project_info.get('version'):
                project_info['version'] = poetry.get('version', '')
            if not project_info.get('description'):
                project_info['description'] = poetry.get('description', '')
            if not project_info.get('authors'):
                project_info['authors'] = poetry.get('authors', [])

        # Extract dependencies if present
        if 'dependencies' in data.get('project', {}):
            project_info['dependencies'] = data['project']['dependencies']
        elif 'tool' in data and 'poetry' in data['tool'] and 'dependencies' in data['tool']['poetry']:
            project_info['dependencies'] = data['tool']['poetry']['dependencies']

        return project_info if project_info.get('name') else None

    except Exception as e:
        logger.error(f"Error parsing pyproject.toml: {e}")
        return None


def save_requirements_txt(requirements: dict[str, str], system_info: dict, comfyui_path: Path):
    """Save the resolved requirements to a requirements.txt file."""
    req_path = Path("comfyui_requirements.txt")

    with open(req_path, 'w', encoding='utf-8') as f:
        f.write("# ComfyUI Environment Requirements\n")
        f.write(f"# Generated from: {comfyui_path}\n")
        f.write(f"# Python version: {system_info.get('python_version')}\n")
        if system_info.get('cuda_version'):
            f.write(f"# CUDA version: {system_info.get('cuda_version')}\n")
        if system_info.get('torch_version'):
            f.write(f"# PyTorch version: {system_info.get('torch_version')}\n")
        f.write("\n")
        f.write("# NOTE: PyTorch packages are managed by ComfyGit local runtime configuration\n")
        f.write("# Install with: pip install -r comfyui_requirements.txt\n")
        f.write("\n")

        # Sort packages for consistency
        for package in sorted(requirements.keys()):
            version = requirements[package]
            if version:
                f.write(f"{package}=={version}\n")
            else:
                f.write(f"{package}\n")

        # Add editable and git requirements at the end
        if system_info.get('editable_installs'):
            f.write("\n# Editable installs\n")
            for install in system_info['editable_installs']:
                f.write(f"{install}\n")

        if system_info.get('git_requirements'):
            f.write("\n# Git requirements\n")
            for req in system_info['git_requirements']:
                f.write(f"{req}\n")

    logger.info(f"Requirements saved to {req_path}")
    logger.info(f"Requirements saved to {req_path}")
