"""System detector for Python, CUDA, and PyTorch detection."""
import json
import platform
import re
import sys
from pathlib import Path

from ..logging.logging_config import get_logger
from ..models.system import SystemInfo
from .common import run_command


class SystemDetector:
    """Detects system-level dependencies like Python, CUDA, and PyTorch."""

    def __init__(self, comfyui_path: Path, python_hint: Path | None = None):
        self.logger = get_logger(__name__)
        self.comfyui_path = Path(comfyui_path).resolve()
        # Don't resolve the Python hint - keep the original path the user provided
        # This preserves venv paths instead of following symlinks
        self.python_hint = Path(python_hint) if python_hint else None

        # Log the python hint for debugging
        if self.python_hint:
            self.logger.info(f"System detector initialized with python hint: {self.python_hint}")
            # Remove debug print statement
        else:
            self.logger.info("System detector initialized without python hint")


    def detect_all(self) -> SystemInfo:
        """Detect all system information and return typed result.

        Returns:
            SystemInfo: Structured system information
        """
        self.logger.info("Starting system detection...")

        # Find Python executable
        python_exe = self._find_python_executable()

        # Detect Python version
        python_info = self._detect_python_version(python_exe)

        # Detect CUDA version
        cuda_version = self._detect_cuda_version()

        # Detect PyTorch version
        pytorch_info = self._detect_pytorch_version(python_exe)

        # Create SystemInfo object
        system_info = SystemInfo(
            python_executable=python_exe,
            python_version=python_info['python_version'],
            python_major_minor=python_info.get('python_major_minor'),
            cuda_version=cuda_version,
            torch_version=pytorch_info.get('torch') if pytorch_info else None,
            cuda_torch_version=pytorch_info.get('cuda_torch_version') if pytorch_info else None,
            pytorch_info=pytorch_info,
            platform=platform.platform(),
            architecture=platform.machine()
        )

        return system_info

    def _find_python_executable(self) -> Path:
        """
        Find the Python executable and virtual environment used by ComfyUI.

        Args:
            comfyui_path: Path to ComfyUI directory
            python_hint: Direct path to Python executable (if provided by user)

        Returns:
            Path to python_executable
        """
        # 1. If user provided python path, validate and use it
        if self.python_hint and self.python_hint.exists():
            self.logger.info(f"Validating user-provided Python executable: {self.python_hint}")
            # For user-provided path, be more lenient - just check it's a valid Python
            try:
                result = run_command(
                    [str(self.python_hint), "-c", "import sys; print(sys.executable)"],
                    timeout=5
                )
                if result.returncode == 0:
                    self.logger.info(f"User-provided Python executable is valid: {self.python_hint}")
                    return self.python_hint
                else:
                    self.logger.warning(f"User-provided Python executable failed validation: {self.python_hint}")
            except Exception as e:
                self.logger.warning(f"Error validating user-provided Python: {e}")

        # 2. Check for virtual environments in standard locations relative to ComfyUI
        # Check common venv locations
        venv_candidates = [
            self.comfyui_path / "venv",
            self.comfyui_path / ".venv",
            self.comfyui_path / "env",
            self.comfyui_path.parent / "venv",
            self.comfyui_path.parent / ".venv",
        ]

        for venv_path in venv_candidates:
            # Check for Python in different locations based on OS
            if platform.system() == "Windows":
                python_paths = [
                    venv_path / "Scripts" / "python.exe",
                    venv_path / "python.exe",
                ]
            else:
                python_paths = [
                    venv_path / "bin" / "python",
                    venv_path / "bin" / "python3",
                ]

            for python_path in python_paths:
                if python_path.exists():
                    self.logger.info(f"Found Python executable: {python_path}")
                    self.logger.info(f"Found virtual environment: {venv_path}")
                    return python_path

        # Check if there's a .venv file pointing to a venv
        venv_file = self.comfyui_path / ".venv"
        if venv_file.exists() and venv_file.is_file():
            try:
                venv_path = Path(venv_file.read_text(encoding='utf-8').strip())
                if venv_path.exists():
                    if platform.system() == "Windows":
                        python_executable = venv_path / "Scripts" / "python.exe"
                    else:
                        python_executable = venv_path / "bin" / "python"
                    if python_executable.exists():
                        self.logger.info(f"Found Python executable via .venv file: {python_executable}")
                        self.logger.info(f"Found virtual environment: {venv_path}")
                        return python_executable
            except Exception:
                pass

        # If no venv found, check if ComfyUI can run with system Python
        self.logger.warning("No virtual environment found, checking system Python...")

        # Try to run ComfyUI's main.py with --help to see if it works
        try:
            result = run_command(
                [sys.executable, str(self.comfyui_path / "main.py"), "--help"],
                timeout=5
            )
            if result.returncode == 0:
                python_executable = Path(sys.executable)
                self.logger.info(f"ComfyUI appears to work with system Python: {sys.executable}")
                return python_executable
        except Exception:
            pass

        self.logger.warning("Could not determine Python executable for ComfyUI")
        return Path(sys.executable)

    def _run_python_command(self, code: str, python_executable: Path) -> str | None:
        """Run Python code in the ComfyUI environment and return output."""
        try:
            result = run_command(
                [str(python_executable), "-c", code],
                cwd=self.comfyui_path,
                timeout=10
            )
            if result.returncode == 0:
                return result.stdout.strip()
            else:
                self.logger.error(f"Error running Python command: {result.stderr}")
                return None
        except Exception as e:
            self.logger.error(f"Exception running Python command: {e}")
            return None


    def _detect_python_version(self, python_executable: Path) -> dict[str, str]:
        """Detect the Python version being used by ComfyUI."""
        code = "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
        python_version = self._run_python_command(code, python_executable)

        assert python_version is not None

        major_minor = '.'.join(python_version.split('.')[:2])
        self.logger.info(f"Python version: {python_version}")

        return {
            'python_version': python_version,
            'python_major_minor': major_minor
        }

    def _detect_cuda_version(self) -> str | None:
        """Detect CUDA version using nvidia-smi."""
        try:
            result = run_command(['nvidia-smi'])
            if result.returncode == 0:
                # Parse CUDA version from nvidia-smi output
                match = re.search(r'CUDA Version:\s*(\d+\.\d+)', result.stdout)
                if match:
                    cuda_version = match.group(1)
                    self.logger.info(f"CUDA version: {cuda_version}")
                    return cuda_version
        except Exception as e:
            self.logger.debug(f"Could not detect CUDA: {e}")

        self.logger.info("No CUDA detected (CPU-only mode)")
        return None

    def _detect_pytorch_version(self, python_executable: Path) -> dict[str, str] | None:
        """Detect PyTorch and related library versions in ComfyUI environment."""
        # Log which Python we're checking for PyTorch
        self.logger.info(f"Checking for PyTorch using Python: {python_executable}")

        # Check if PyTorch is installed in the ComfyUI environment
        code = """
import json
try:
    import torch
    info = {
        'torch': torch.__version__,
        'cuda_available': torch.cuda.is_available(),
        'cuda_torch_version': torch.version.cuda if torch.cuda.is_available() else None
    }

    # Try to detect torchvision and torchaudio
    try:
        import torchvision
        info['torchvision'] = torchvision.__version__
    except ImportError:
        pass

    try:
        import torchaudio
        info['torchaudio'] = torchaudio.__version__
    except ImportError:
        pass

    print(json.dumps(info))
except ImportError:
    print(json.dumps({'error': 'PyTorch not installed'}))
"""

        output = self._run_python_command(code, python_executable)
        if output:
            try:
                pytorch_info = json.loads(output)
                if 'error' not in pytorch_info:
                    self.logger.info(f"PyTorch version: {pytorch_info.get('torch')}")
                    if pytorch_info.get('cuda_torch_version'):
                        self.logger.info(f"PyTorch CUDA: {pytorch_info.get('cuda_torch_version')}")
                else:
                    self.logger.warning("PyTorch not found in ComfyUI environment")
                    return None
                return pytorch_info
            except json.JSONDecodeError:
                self.logger.warning("Could not parse PyTorch information")

        return None
