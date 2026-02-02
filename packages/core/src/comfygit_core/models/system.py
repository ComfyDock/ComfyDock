import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .exceptions import ComfyDockError


@dataclass
class Package:
    """Represents an installed Python package."""

    name: str
    version: str
    is_editable: bool = False

    def validate(self) -> None:
        """Validate package information."""
        if not self.name:
            raise ComfyDockError("Package name cannot be empty")
        if not self.version:
            raise ComfyDockError("Package version cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'Package':
        """Create instance from dictionary."""
        return cls(**data)

@dataclass
class SystemRequirements:
    """System requirements for the environment."""

    python_version: str
    cuda_version: str | None = None
    platform: str = "linux"
    architecture: str | None = None
    comfyui_version: str = ""

    def validate(self) -> None:
        """Validate system info fields."""
        if not self._is_valid_version(self.python_version):
            raise ComfyDockError(f"Invalid Python version format: {self.python_version}")

        if self.cuda_version and not self._is_valid_cuda_version(self.cuda_version):
            raise ComfyDockError(f"Invalid CUDA version format: {self.cuda_version}")

        # Platform validation
        valid_platforms = {'linux', 'darwin', 'win32'}
        if self.platform not in valid_platforms:
            raise ComfyDockError(f"Invalid platform: {self.platform}. Must be one of: {', '.join(valid_platforms)}")

        # ComfyUI version validation (required)
        if not self.comfyui_version:
            raise ComfyDockError("ComfyUI version is required")

    @staticmethod
    def _is_valid_version(version: str) -> bool:
        """Check if version follows M.m.p format."""
        pattern = r'^\d+\.\d+\.\d+$'
        return bool(re.match(pattern, version))

    @staticmethod
    def _is_valid_cuda_version(version: str) -> bool:
        """Check if CUDA version is valid (M.m format)."""
        pattern = r'^\d+\.\d+$'
        return bool(re.match(pattern, version))


    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            'python_version': self.python_version,
            'cuda_version': self.cuda_version,
            'platform': self.platform,
            'comfyui_version': self.comfyui_version
        }
        if self.architecture:
            result['architecture'] = self.architecture
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'SystemRequirements':
        """Create instance from dictionary."""
        return cls(**data)

@dataclass
class PyTorchSpec:
    """PyTorch packages configuration with index URL."""

    index_url: str
    packages: dict[str, str] = field(default_factory=dict)

    def validate(self) -> None:
        """Validate PyTorch specification."""
        if not self._is_valid_url(self.index_url):
            raise ComfyDockError(f"Invalid PyTorch index URL: {self.index_url}")

        if not self.packages:
            raise ComfyDockError("PyTorch packages cannot be empty")

        for package, version in self.packages.items():
            if not self._is_valid_package_name(package):
                raise ComfyDockError(f"Invalid package name: {package}")
            if not self._is_valid_version(version):
                raise ComfyDockError(f"Invalid version for {package}: {version}")

    @staticmethod
    def _is_valid_url(url: str) -> bool:
        """Check if URL is absolute with scheme."""
        try:
            result = urlparse(url)
            return bool(result.scheme and result.netloc)
        except Exception:
            return False

    @staticmethod
    def _is_valid_package_name(name: str) -> bool:
        """Check if package name follows PEP 508."""
        # Basic validation: alphanumeric with dash, underscore, dot
        pattern = r'^[a-zA-Z0-9\-_\.]+$'
        return bool(re.match(pattern, name))

    @staticmethod
    def _is_valid_version(version: str) -> bool:
        """Check if version is valid (basic semver with optional suffix like +cu126)."""
        pattern = r'^\d+\.\d+(\.\d+)?(\+[a-zA-Z0-9]+)?$'
        return bool(re.match(pattern, version))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'PyTorchSpec':
        """Create instance from dictionary."""
        return cls(**data)

def create_system_requirements_from_detection(
    python_version: str,
    cuda_version: str | None = None,
    platform: str = "linux",
    architecture: str | None = None,
    comfyui_version: str = ""
) -> SystemRequirements:
    """Create SystemRequirements from detection results."""
    info = SystemRequirements(
        python_version=python_version,
        cuda_version=cuda_version,
        platform=platform,
        architecture=architecture,
        comfyui_version=comfyui_version
    )
    info.validate()
    return info


@dataclass
class SystemInfo:
    """System information detected from a ComfyUI installation.

    This dataclass represents all system-level information needed
    to recreate a ComfyUI environment.
    """

    # Python information
    python_version: str
    python_executable: Path | None = None
    python_major_minor: str | None = None

    # CUDA/GPU information
    cuda_version: str | None = None
    cuda_torch_version: str | None = None  # CUDA version PyTorch was built with

    # PyTorch information
    torch_version: str | None = None
    pytorch_info: dict | None = None  # Full PyTorch detection results

    # Platform information
    platform: str = ""
    architecture: str = ""

    def to_dict(self) -> dict:
        """Convert to dictionary for compatibility with existing code."""
        result = {
            'python_version': self.python_version,
            'cuda_version': self.cuda_version,
            'torch_version': self.torch_version,
            'cuda_torch_version': self.cuda_torch_version,
            'platform': self.platform,
            'architecture': self.architecture,
            'pytorch_info': self.pytorch_info
        }

        # Include optional fields if present
        if self.python_executable:
            result['python_executable'] = str(self.python_executable)
        if self.python_major_minor:
            result['python_major_minor'] = self.python_major_minor

        return result
