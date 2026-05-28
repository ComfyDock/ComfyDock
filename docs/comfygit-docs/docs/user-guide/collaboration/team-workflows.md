# Team Workflows

ComfyGit works best when the team agrees on what belongs in Git and what stays
local.

## Team Rules

Commit:

- manifest changes
- workflow JSON files
- workflow API prompt artifacts
- custom node metadata
- model metadata and source URLs
- shared overlays

Do not commit:

- model bytes
- local overlays
- virtualenvs
- caches
- logs
- local-only checkout paths

## Recommended Flow

One person creates or updates the environment:

```bash
cg status
cg workflow resolve my-workflow
cg commit -m "Update workflow dependencies"
cg push
```

Another person pulls and repairs as needed:

```bash
cg pull -r origin --models required
cg status
cg run
```

## Model Source Hygiene

Before pushing, fix required model source warnings. A workflow that only works
because your local disk has a file is not yet reproducible for the team.

```bash
cg model add-source model.safetensors URL
cg commit -m "Add model source"
```

## Development Nodes

Use `node dev-link` for local work, but make sure development nodes intended for
handoff have Git provenance and a pinned commit.

```bash
cg node dev-link my-node --path ~/dev/my-node --replace-existing
```

## Serving Team Workflows

When a workflow needs a shared UI/API, author a contract in Manager, commit the
workflow and `workflow_api/` artifact, then serve it:

```bash
cg serve --port 8190 --comfy-url http://127.0.0.1:8188
```

For hosted or container runtime flows, materialize from the committed
environment instead of copying a live runtime directory.
