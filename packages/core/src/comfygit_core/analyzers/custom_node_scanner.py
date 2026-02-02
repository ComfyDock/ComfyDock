"""Simple custom node scanner for finding dependencies in nodes."""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class NodeDependencies:
    """Dependencies found in a custom node."""
    requirements_file: Path | None = None
    requirements: list[str] | None = None
    pyproject_file: Path | None = None
    has_install_script: bool = False


class CustomNodeScanner:
    """Scans custom nodes for dependencies and metadata."""

    def scan_node(self, node_path: Path) -> NodeDependencies:
        """Scan a custom node directory for dependencies.

        Args:
            node_path: Path to the custom node directory

        Returns:
            NodeDependencies with found requirements
        """
        result = NodeDependencies()

        if not node_path.exists() or not node_path.is_dir():
            return result

        # Look for requirements.txt (primary source)
        req_file = node_path / "requirements.txt"
        if req_file.exists():
            result.requirements_file = req_file
            result.requirements = self._read_requirements(req_file)

        # Check for pyproject.toml (secondary)
        pyproject_file = node_path / "pyproject.toml"
        if pyproject_file.exists():
            result.pyproject_file = pyproject_file

        # Check for install scripts
        for script_name in ["install.py", "install.sh", "setup.py"]:
            if (node_path / script_name).exists():
                result.has_install_script = True
                break

        return result

    def _read_requirements(self, req_file: Path) -> list[str]:
        """Read and parse requirements.txt file.

        Strips inline comments (e.g., 'gdown # comment') to ensure PEP 508 compliance.

        Args:
            req_file: Path to requirements.txt

        Returns:
            List of requirement strings with inline comments removed
        """
        requirements = []

        try:
            with open(req_file, encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    # Skip full-line comments and empty lines
                    if line and not line.startswith('#'):
                        # Handle -r includes (just note them for now)
                        if line.startswith('-r '):
                            # TODO: Handle recursive requirements
                            continue

                        # Strip inline comments (everything after #)
                        # Example: "gdown # supports downloading" -> "gdown"
                        if '#' in line:
                            line = line.split('#', 1)[0].strip()

                        # Only add if there's content after stripping
                        if line:
                            requirements.append(line)
        except Exception:
            # Return empty list on any read error
            pass

        return requirements

    def find_all_requirements(self, node_path: Path) -> list[Path]:
        """Find all requirements files in a node (including subdirectories).

        Args:
            node_path: Path to the custom node directory

        Returns:
            List of paths to requirements files
        """
        if not node_path.exists() or not node_path.is_dir():
            return []

        # Look for requirements files
        patterns = ["requirements*.txt", "requirements/*.txt"]
        req_files = []

        for pattern in patterns:
            req_files.extend(node_path.glob(pattern))

        return req_files
