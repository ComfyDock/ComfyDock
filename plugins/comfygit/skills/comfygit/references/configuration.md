# Configuration Files

Structure and usage of ComfyGit configuration files.

## Table of Contents
- [Workspace Structure](#workspace-structure)
- [pyproject.toml](#pyprojecttoml)
- [package_config.toml](#package_configtoml)
- [workspace.json](#workspacejson)
- [Machine-Specific Files](#machine-specific-files)

---

## Workspace Structure

```
~/comfygit/                          # Workspace root (or COMFYGIT_HOME)
├── .metadata/
│   ├── workspace.json               # Workspace config
│   └── version                      # Schema version (v2)
├── environments/
│   └── <env_name>/
│       ├── .cec/                    # Core Environment Content (git-tracked)
│       │   ├── pyproject.toml       # Main config file
│       │   ├── package_config.toml  # Package substitutions/exclusions
│       │   ├── workflows/           # Workflow JSON files
│       │   ├── .python-version      # Python version pin
│       │   ├── .pytorch-backend     # PyTorch backend (gitignored)
│       │   ├── .gitignore
│       │   ├── uv.lock              # UV lockfile (gitignored)
│       │   └── .git/                # Environment git repo
│       └── ComfyUI/
│           ├── custom_nodes/ → symlink
│           ├── models/ → symlink to ~/comfygit/models/
│           ├── input/ → symlink
│           └── output/ → symlink
├── models/                          # Global model storage
├── comfygit_cache/
│   ├── models.db                    # SQLite model index
│   ├── registry_data/               # Cached registry JSON
│   └── comfyui_cache/               # Cached ComfyUI versions
├── input/<env_name>/                # Per-environment input
├── output/<env_name>/               # Per-environment output
└── logs/                            # Workspace logs
```

---

## pyproject.toml

Main environment configuration file at `.cec/pyproject.toml`.

### Project Section

```toml
[project]
name = "comfygit-env-production"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    # Python dependencies (added via cg py add)
    "requests>=2.28.0",
]
```

### ComfyGit Section

```toml
[tool.comfygit]
schema_version = 2
comfyui_version = "snapshot"         # "snapshot", tag, or commit
comfyui_version_type = "branch"      # "branch", "tag", "commit"
comfyui_commit_sha = "abc123..."     # Actual commit SHA

python_version = "3.12"
```

### Nodes Section

```toml
[tool.comfygit.nodes]

[tool.comfygit.nodes.comfyui-manager]
name = "comfyui-manager"
package_id = "comfyui-manager"
version = "1.2.3"
source_type = "registry"             # "registry", "git", "dev"
github_url = "https://github.com/..."
requirements = ["aiohttp", "packaging"]

[tool.comfygit.nodes."my-dev-node"]
name = "my-dev-node"
version = "dev"
source_type = "dev"
local_path = "/path/to/source"
tracked_branch = "main"
tracked_commit = "abc123"
```

### Workflows Section

```toml
[tool.comfygit.workflows]

[tool.comfygit.workflows."my_workflow.json"]
# Custom node mappings (user-confirmed resolutions)
custom_node_map = {
    "CustomNode1" = "package-id",
    "OptionalNode" = false           # Marked as optional
}

# Model resolutions
[[tool.comfygit.workflows."my_workflow.json".models]]
filename = "sd_xl.safetensors"
hash = "abc123"
category = "checkpoints"
criticality = "required"             # "required", "flexible", "optional"
status = "resolved"                  # "resolved", "unresolved"
nodes = [
    { node_id = "1", widget_index = 0 }
]

# Unresolved model (download intent)
[[tool.comfygit.workflows."my_workflow.json".models]]
filename = "lora_model.safetensors"
status = "unresolved"
criticality = "required"
sources = ["https://civitai.com/api/download/..."]
relative_path = "loras/lora_model.safetensors"
```

### Global Models Section

```toml
[tool.comfygit.models]

[tool.comfygit.models."abc123"]      # Keyed by short hash
hash = "abc123"
filename = "sd_xl.safetensors"
category = "checkpoints"
file_size = 6938166272
blake3_hash = "..."
sources = [
    "https://civitai.com/api/download/...",
    "https://huggingface.co/..."
]
```

### UV Section

```toml
[tool.uv]
# Managed automatically - don't edit manually
exclude-newer = "2025-01-01T00:00:00Z"  # Reproducibility lock
```

### Dependency Groups

```toml
[dependency-groups]
dev = ["pytest", "ruff"]
optional = ["tensorrt"]
```

---

## package_config.toml

Package substitutions and exclusions at `.cec/package_config.toml`.

```toml
# Substitutions: Replace package requests with alternatives
[substitutions]
opencv-python = "opencv-python-headless"    # Avoid GUI dependency
pillow = "pillow-simd"                      # Faster alternative

# Exclusions: Never install these packages
[exclude]
packages = [
    "torch",                  # Managed by PyTorch backend
    "torchvision",
    "torchaudio",
]
```

**When substitutions apply:**
- During node requirement scanning
- Package requested → substitution installed instead

**When exclusions apply:**
- Synced to pyproject.toml `[tool.uv.override-dependencies]`
- UV will never install these packages

---

## workspace.json

Workspace-level configuration at `.metadata/workspace.json`.

```json
{
  "version": 1,
  "active_environment": "production",
  "created_at": "2025-01-24T10:30:00Z",
  "global_model_directory": {
    "path": "/path/to/models",
    "added_at": "2025-01-24T10:30:00Z",
    "last_sync": "2025-01-24T12:00:00Z"
  },
  "api_credentials": {
    "civitai_token": "...",
    "runpod_api_key": "..."
  },
  "external_uv_cache": null
}
```

**Fields:**
- `active_environment`: Default when `-e` not specified
- `global_model_directory`: Custom models location (default: `~/comfygit/models/`)
- `api_credentials`: API keys (also check env vars)
- `external_uv_cache`: Override UV cache location (for testing)

**API key priority:**
1. Environment variable (`CIVITAI_API_KEY`)
2. Config file value

---

## Machine-Specific Files

These files are gitignored (not tracked in environment git):

### .pytorch-backend

```
cu121
```

Single line with backend name. Options:
- `auto` - Auto-detect
- `cpu` - CPU only
- `cu118` - CUDA 11.8
- `cu121` - CUDA 12.1
- `cu124` - CUDA 12.4

Set via: `cg env-config torch-backend set cu121`

**Why gitignored:** Different machines have different GPUs.

### uv.lock

UV lockfile with exact dependency versions.

**Why gitignored:** Platform-specific (wheels differ per OS/arch).

### .complete

Empty marker file indicating successful environment creation.

**Why gitignored:** Creation state, not content.

---

## Git Tracking

### Tracked Files (.cec/)

- `pyproject.toml` - Dependencies, nodes, workflows
- `package_config.toml` - Substitutions, exclusions
- `workflows/*.json` - Workflow files
- `.python-version` - Python version
- `.gitignore` - Git ignore rules

### Gitignored Files

```gitignore
# In .cec/.gitignore
staging/
metadata/
logs/
__pycache__/
*.pyc
*.tmp
*.bak
.complete
.pytorch-backend
uv.lock
```

---

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `COMFYGIT_HOME` | Override workspace location |
| `CIVITAI_API_KEY` | CivitAI API token |
| `HF_TOKEN` | HuggingFace token |
| `GIT_AUTHOR_NAME` | Git commit author name |
| `GIT_AUTHOR_EMAIL` | Git commit author email |

---

## Schema Versions

### Workspace Schema (v2)

- **v1:** System nodes symlinked from `.metadata/system_nodes/`
- **v2:** Manager tracked per-environment in pyproject.toml

Check: `.metadata/version` file contains `2`

### Pyproject Schema (v2)

- **v1:** PyTorch config inline (indexes, sources, constraints)
- **v2:** PyTorch config in `.pytorch-backend`, injected at sync

Check: `[tool.comfygit].schema_version = 2`

---

## Common Operations

### View Configuration

```bash
cg -e prod manifest              # Raw TOML
cg -e prod manifest --pretty     # YAML format
cg -e prod manifest --section nodes
```

### Check Status

```bash
cg -e prod status                # Environment status
cg model index status            # Models directory status
cg registry status               # Registry cache status
```

### Update Configuration

```bash
# Set PyTorch backend
cg -e prod env-config torch-backend set cu121

# Set models directory
cg model index dir /path/to/models

# Set API key
cg config --civitai-key <token>
```
