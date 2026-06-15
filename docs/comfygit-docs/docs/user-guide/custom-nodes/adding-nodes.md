# Adding Custom Nodes

ComfyGit can add custom nodes from the ComfyUI Registry, Git repositories, and
local development checkouts.

Use registry IDs when possible. Use Git URLs when you need a fork, branch, tag,
or commit that is not available from the registry.

## Add From The Registry

```bash
cg node add rgthree-comfy
```

Install a specific version or ref when supported:

```bash
cg node add rgthree-comfy@1.0.0
```

## Add From Git

```bash
cg node add https://github.com/owner/custom-node.git
cg node add https://github.com/owner/custom-node.git@main
cg node add https://github.com/owner/custom-node.git@abc1234
```

Git URLs are useful for forks, unreleased nodes, or exact commits.

## Add Several Nodes

```bash
cg node add node-a node-b node-c
```

Batch operations are sequential. If one node fails, earlier successful nodes are
not automatically rolled back.

## Dependency Resolution Options

```bash
cg node add NODE --strict
cg node add NODE --no-test
cg node add NODE --extra cuda
cg node add NODE --all-extras
cg node add NODE --resolve-with-overlays
```

Use `--strict` when you want dependency conflicts to fail instead of being
auto-resolved. Use `--resolve-with-overlays` when active overlays should
participate in the install preflight.

If a node installs but fails to import after restart, see
[Custom node import failures](../../troubleshooting/custom-node-import-failures.md).

## Development Nodes

If you are replacing an existing tracked node with a local checkout, prefer:

```bash
cg node dev-link NODE --path ~/dev/NODE --replace-existing
```

If the local node only exists in `custom_nodes/` and you want to track it:

```bash
cg node add my-local-node --dev
```

Read more: [Development nodes](development-nodes.md).

## What Gets Tracked

The manifest records node identity, source, version/ref, dependency metadata,
and provenance when available.

Workflow dependencies should point to canonical manifest node IDs. Local aliases
such as directory names or repository URLs can help resolution, but they are not
the portable identity.

## ComfyGit Manager

ComfyGit installs `comfygit-manager` in normal authoring environments. Manage it
with:

```bash
cg manager status
cg manager update --yes
```

Do not confuse `comfygit-manager` with ComfyUI-Manager.
