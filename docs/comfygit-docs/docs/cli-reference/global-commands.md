# Global Commands

> Workspace-level commands that operate on the entire ComfyGit workspace.


## `init`

**Usage:**

```bash
cg init [-h] [--models-dir MODELS_DIR] [--yes] [path]
```

**Arguments:**

- `path` - Workspace directory (default: ~/comfygit) (optional)

**Options:**

- `--models-dir` - Path to existing models directory to index
- `--yes, -y` - Use all defaults, no interactive prompts (default: `False`)


## `list`

**Usage:**

```bash
cg list [-h]
```


## `import`

**Usage:**

```bash
cg import [-h] [--name NAME] [--branch BRANCH]
                 [--torch-backend BACKEND] [--use]
                 [--models {all,required,skip}] [-y]
                 [path]
```

**Arguments:**

- `path` - Path to .tar.gz file or git repository URL (use #subdirectory for subdirectory imports) (optional)

**Options:**

- `--name` - Name for imported environment (skip prompt)
- `--branch, -b` - Git branch, tag, or commit to import (git imports only)
- `--torch-backend` - PyTorch backend. Examples: auto (detect GPU), cpu, cu128 (CUDA 12.8), cu126, cu124, rocm6.3 (AMD), xpu (Intel). Default: auto (default: `auto`)
- `--use` - Set imported environment as active (default: `False`)
- `--models` - Model download strategy: all (default with --yes), required only, or skip (choices: `all`, `required`, `skip`)
- `-y, --yes` - Skip confirmation prompts, use defaults for workspace initialization (default: `False`)


## `export`

**Usage:**

```bash
cg export [-h] [--allow-issues] [path]
```

**Arguments:**

- `path` - Path to output file (optional)

**Options:**

- `--allow-issues` - Export even with unresolved workflows or models without source URLs (default: `False`)


## `model`

**Usage:**

```bash
cg model [-h] {index,download,add-source} ...
```

### Subcommands


### `index`

**Usage:**

```bash
cg model index [-h] {find,list,show,status,sync,dir} ...
```

#### Subcommands


#### `find`

**Usage:**

```bash
cg model index find [-h] query
```

**Arguments:**

- `query` - Search query (hash prefix or filename)


#### `list`

**Usage:**

```bash
cg model index list [-h] [--duplicates]
```

**Options:**

- `--duplicates` - Show only models with multiple locations (default: `False`)


#### `show`

**Usage:**

```bash
cg model index show [-h] identifier
```

**Arguments:**

- `identifier` - Model hash, hash prefix, filename, or path


#### `status`

**Usage:**

```bash
cg model index status [-h]
```


#### `sync`

**Usage:**

```bash
cg model index sync [-h]
```


#### `dir`

**Usage:**

```bash
cg model index dir [-h] path
```

**Arguments:**

- `path` - Path to models directory


### `download`

**Usage:**

```bash
cg model download [-h] [--path PATH] [-c CATEGORY] [-y] url
```

**Arguments:**

- `url` - Model download URL (Civitai, HuggingFace, or direct)

**Options:**

- `--path` - Target path relative to models directory (e.g., checkpoints/model.safetensors)
- `-c, --category` - Model category for auto-path (e.g., checkpoints, loras, vae)
- `-y, --yes` - Skip path confirmation prompt (default: `False`)


### `add-source`

**Usage:**

```bash
cg model add-source [-h] [model] [url]
```

**Arguments:**

- `model` - Model filename or hash (omit for interactive mode) (optional)
- `url` - Download URL (optional)


## `registry`

**Usage:**

```bash
cg registry [-h] {status,update} ...
```

### Subcommands


### `status`

**Usage:**

```bash
cg registry status [-h]
```


### `update`

**Usage:**

```bash
cg registry update [-h]
```


## `config`

**Usage:**

```bash
cg config [-h] [--civitai-key CIVITAI_KEY] [--uv-cache UV_CACHE]
                 [--show]
                 {} ...
```

**Options:**

- `--civitai-key` - Set Civitai API key (use empty string to clear)
- `--uv-cache` - Set external UV cache path (use empty string to clear)
- `--show` - Show current configuration (default: `False`)


## `debug`

**Usage:**

```bash
cg debug [-h] [-n LINES] [--level {DEBUG,INFO,WARNING,ERROR}] [--full]
                [--workspace]
```

**Options:**

- `-n, --lines` - Number of lines to show (default: 200) (default: `200`)
- `--level` - Filter by log level (choices: `DEBUG`, `INFO`, `WARNING`, `ERROR`)
- `--full` - Show all logs (no line limit) (default: `False`)
- `--workspace` - Show workspace logs instead of environment logs (default: `False`)
