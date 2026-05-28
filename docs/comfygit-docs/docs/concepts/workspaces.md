# Workspaces

A workspace is the local home for ComfyGit on one machine. It contains your
environment list, shared model index, registry cache, logs, and workspace
configuration.

```text
~/comfygit/
  environments/
  models/
  comfygit_cache/
  logs/
  .metadata/
```

Most users should have one workspace per machine. The workspace is not the
portable artifact you hand to another user. Each environment inside the
workspace has its own tracked repository.

## What The Workspace Owns

The workspace owns machine-local coordination state:

- where environments live
- which environment is active
- where the shared model directory is
- cached ComfyUI registry data
- cached model index data
- workspace and environment logs
- optional credentials such as Civitai and GitHub tokens

Credentials and caches should stay local. Environment manifests should hold the
portable recipe.

## Common Commands

```bash
cg init
cg init --models-dir ~/ComfyUI/models --yes
cg config --show
cg model index status
cg registry status
```

Use `COMFYGIT_HOME` only when you intentionally want to switch between multiple
workspaces.

Read more: [Workspaces guide](../user-guide/workspaces.md).
