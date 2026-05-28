# Dependency Conflicts

Dependency conflicts happen when Python packages requested by ComfyUI, custom
nodes, or your own additions cannot be resolved together.

## Inspect The Failure

```bash
cg sync --verbose
cg debug -n 100 --level ERROR
```

If the failure came from adding a node, try strict mode to see the raw conflict:

```bash
cg node add my-node --strict
```

## Fix Options

### Update Or Remove A Node

```bash
cg node update my-node --yes
cg node remove my-node
```

### Add A Constraint

```bash
cg constraint add "package<2"
cg constraint list
cg sync
```

### Use A Local Overlay

Use overlays for local experiments or machine-specific package sources:

```bash
cg overlay create local-dev --local
cg overlay enable local-dev
cg sync --overlay local-dev
```

### Split Environments

If two workflows require incompatible node stacks, create separate environments:

```bash
cg create workflow-a --use
cg create workflow-b
```

## Avoid

Avoid manually installing packages into `.venv`. Sync may recreate it, and the
change will not be represented in the manifest.

Avoid destructive Git reset commands unless you intentionally want to discard
local changes.
