"""Constants and configuration for ComfyUI environment detection."""

# PyTorch-related packages that need special handling
PYTORCH_PACKAGE_NAMES = {
    # Core PyTorch packages
    'torch', 'torchvision', 'torchaudio',

    # Triton packages (PyTorch's fused-kernel compiler)
    'triton', 'triton-windows',

    # NVIDIA CUDA packages
    'cuda-bindings', 'cuda-toolkit',
    'nvidia-cublas-cu11', 'nvidia-cublas-cu12',
    'nvidia-cuda-runtime-cu11', 'nvidia-cuda-runtime-cu12',
    'nvidia-cuda-nvrtc-cu11', 'nvidia-cuda-nvrtc-cu12',
    'nvidia-cudnn-cu11', 'nvidia-cudnn-cu12',
    'nvidia-cufft-cu11', 'nvidia-cufft-cu12',
    'nvidia-curand-cu11', 'nvidia-curand-cu12',
    'nvidia-cusolver-cu11', 'nvidia-cusolver-cu12',
    'nvidia-cusparse-cu11', 'nvidia-cusparse-cu12',
    'nvidia-nccl-cu11', 'nvidia-nccl-cu12',
    'nvidia-nvtx-cu11', 'nvidia-nvtx-cu12',

    # New CUDA packages in PyTorch 2.6+
    'nvidia-cuda-cupti-cu11', 'nvidia-cuda-cupti-cu12',  # CUPTI (profiler)
    'nvidia-cufile-cu11', 'nvidia-cufile-cu12',  # cuFile (GPUDirect Storage)
    'nvidia-cusparselt-cu11', 'nvidia-cusparselt-cu12',  # structured-sparse LT
    'nvidia-nvjitlink-cu11', 'nvidia-nvjitlink-cu12',  # NVJitLink
    'nvidia-nvshmem-cu11', 'nvidia-nvshmem-cu12',  # NVSHMEM

    # NOTE: nvidia-ml-py and nvidia-ml-py3 are NOT included
    # These are optional NVML bindings for monitoring that PyTorch doesn't depend on
}

# Blacklist of directory names that should not be treated as custom nodes
CUSTOM_NODES_BLACKLIST = {
    '__pycache__',
    '.pytest_cache',
    '.mypy_cache',
    '.tox',
    'node_modules',
    '.vscode',
    '.idea',
    'venv',
    '.venv',
    'env',
    '.env',
    'build',
    'dist',
    '.DS_Store',
    'Thumbs.db',
    '.coverage',
    'htmlcov',
    '.git',
    '.svn',
    '.hg',
    'test',
    'tests',
    '__tests__',
    'spec',
    'specs',
    'tmp',
    'temp',
    '.tmp',
    '.temp'
}

# Legacy system custom nodes - used only for migration detection.
# In v1 schema, these nodes were symlinked from workspace-level .metadata/system_nodes/.
# In v2 schema, comfygit-manager is tracked per-environment in pyproject.toml.
# This set is kept only for detecting legacy workspaces that need migration.
LEGACY_SYSTEM_NODES = {
    'comfygit-manager',
}

# The manager node ID - used for environment creation and migration logic.
MANAGER_NODE_ID = 'comfygit-manager'
MANAGER_GITHUB_URL = 'https://github.com/comfygit-ai/comfygit-manager'

# Runtime-only PyTorch backend override used by `cg run --torch-backend`.
# This is intentionally non-persistent: it tells child Manager/UI processes
# which backend policy launched the current ComfyUI process without writing to
# `.pytorch-backend`.
ACTIVE_TORCH_BACKEND_OVERRIDE_ENV = "COMFYGIT_TORCH_BACKEND_OVERRIDE"

# Schema version for environment pyproject.toml format.
# Increment when making breaking changes to the pyproject.toml structure.
# v1: Original format with inline PyTorch config (indexes, sources, constraints)
# v2: PyTorch config moved to .pytorch-backend file, materialized in disposable sync projects
PYPROJECT_SCHEMA_VERSION = 2

# Default values
DEFAULT_REGISTRY_URL = "https://api.comfy.org"
DEFAULT_GITHUB_URL = "https://github.com"
GITHUB_API_BASE = "https://api.github.com"

GITHUB_NODE_MAPPINGS_URL = "https://raw.githubusercontent.com/comfygit-ai/comfygit-registry-data/main/data/node_mappings.json"
GITHUB_COMFYUI_BUILTINS_BY_VERSION_URL = "https://raw.githubusercontent.com/comfygit-ai/comfygit-registry-data/main/data/comfyui_builtins_by_version.json"

MAX_REGISTRY_DATA_AGE_HOURS = 24

# Prevent infinite loops when retrying sync with failing optional groups skipped.
MAX_OPT_GROUP_RETRIES = 10

# PyTorch core packages
PYTORCH_CORE_PACKAGES = ["torch", "torchvision", "torchaudio"]

# PyTorch index base URL
PYTORCH_INDEX_BASE_URL = "https://download.pytorch.org/whl"

SYSTEM_DEPENDENCY_GROUP = "comfygit-system"
SYSTEM_UV_DEPENDENCY = "uv>=0.11.8"
