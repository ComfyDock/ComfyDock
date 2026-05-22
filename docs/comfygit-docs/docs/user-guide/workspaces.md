# Workspaces

A workspace is the local home for ComfyGit on one machine. It contains your
environments, shared model index, registry cache, logs, and machine-specific
configuration.

Most users should keep one workspace per machine. Environments inside that
workspace are the portable units you commit, push, pull, import, export, and
materialize.


## Create A Workspace

Initialize the default workspace at `~/comfygit`:

```bash
cg init
```

If you already have a ComfyUI model directory, point ComfyGit at it during
initialization:

```bash
cg init --models-dir ~/ComfyUI/models --yes
```

You can also create a workspace at a custom path:

```bash
cg init /path/to/workspace --models-dir /path/to/models
```

When you use a custom path, set `COMFYGIT_HOME` before running other commands:

```bash
export COMFYGIT_HOME=/path/to/workspace
```

Add that export to your shell profile if this should be your normal workspace.

## What Lives There

A typical workspace looks like this:

```text
~/comfygit/
├── environments/
│   ├── deforum-testing/
│   └── production/
├── models/
│   ├── checkpoints/
│   ├── loras/
│   └── ...
├── comfygit_cache/
│   ├── model_index.db
│   ├── registry_cache.db
│   └── workflow_cache.db
├── logs/
└── .metadata/
```

The important distinction is portability:

- Environment repositories contain the tracked `pyproject.toml` manifest.
- Model bytes stay outside git and are resolved through hashes, sources, and
  paths.
- Workspace metadata, logs, caches, local source overrides, and virtual
  environments are local runtime state.

This is why you can push an environment repo without pushing your whole machine
state.

## Inspect Configuration

Use `cg config --show` to see which workspace and shared settings are active:

```bash
cg config --show
```

The config output includes the workspace path, Civitai API key state, GitHub
token state, and uv cache location.

Set optional credentials with:

```bash
cg config --civitai-key YOUR_API_KEY
cg config --github-token YOUR_GITHUB_TOKEN
```

Use an empty string to clear a value:

```bash
cg config --civitai-key ""
```

An external uv cache can reduce repeated downloads across environments:

```bash
cg config --uv-cache /path/to/uv-cache
```

## Model Index

The workspace has one shared model index. It scans the configured models
directory and records local paths, categories, filenames, sizes, and hashes.

Check the index:

```bash
cg model index status
cg model index list
```

Point the workspace at a different models directory:

```bash
cg model index dir /path/to/models
```

Rescan after adding files outside ComfyGit:

```bash
cg model index sync
```

The index is local. Workflow manifests decide which indexed models are required
for a particular environment or workflow.

## Registry Cache

ComfyGit uses the ComfyUI registry cache to resolve published custom nodes.

```bash
cg registry status
cg registry update
```

Update the registry when a recently published node cannot be found, or when you
are preparing an environment for someone else to materialize.

## Logs And Diagnostics

`cg debug` shows recent workspace or environment logs:

```bash
cg debug
cg debug -n 50
cg debug --level ERROR
cg debug --workspace
```

For orchestrator state and logs:

```bash
cg orch status
cg orch logs -n 100
```

Use these commands before deleting local state. Most sync, node install, model
index, and manager update problems leave useful context in the logs.

## Multiple Workspaces

Multiple workspaces are useful for hard isolation, but they add overhead. Prefer
one workspace unless you have a specific reason to separate model directories,
caches, or environment sets.

Switch workspaces by changing `COMFYGIT_HOME`:

```bash
export COMFYGIT_HOME=~/comfygit-work
cg list

export COMFYGIT_HOME=~/comfygit-personal
cg list
```

Each workspace has its own environment list, model index, cache, logs, and
configuration.

## Practical Rules

- Put large model files in the shared models directory, not in environment git
  repos.
- Commit environment changes from inside the environment with `cg commit`.
- Use `cg model index sync` after manually adding models to the filesystem.
- Use `cg registry update` when a node lookup looks stale.
- Avoid editing `.metadata` files directly; use CLI commands instead.

## Next Steps

- [Create an environment](environments/creating-environments.md)
- [Understand the model index](models/model-index.md)
- [Repair sync drift](environments/sync-and-repair.md)
