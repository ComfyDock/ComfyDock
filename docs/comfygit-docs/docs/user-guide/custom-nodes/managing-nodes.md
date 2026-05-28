# Managing Custom Nodes

Use node management commands to inspect, update, remove, and prune custom nodes
inside an environment.

## List Nodes

```bash
cg node list
```

Use `cg status --verbose` when you need broader environment detail.

## Update A Node

```bash
cg node update rgthree-comfy
cg node update rgthree-comfy --yes
cg node update rgthree-comfy --no-test
```

Update behavior depends on the source:

- registry nodes update through registry metadata
- Git nodes update through the recorded repository/ref behavior
- development nodes keep your local checkout under your control
- `comfygit-manager` should be updated with `cg manager update`

## Remove A Node

```bash
cg node remove rgthree-comfy
```

Untrack without deleting runtime files:

```bash
cg node remove rgthree-comfy --untrack
```

Remove a development node from tracking:

```bash
cg node remove my-local-node --dev
```

Development node removal does not delete your developer-owned checkout.

## Prune Unused Nodes

```bash
cg node prune
cg node prune --exclude keep-this-node
```

Prune only after reviewing what ComfyGit plans to remove. Custom nodes can have
runtime side effects outside visible workflow nodes.

## Required And Optional Nodes

Missing custom node criticality defaults to required. Optional nodes may remain
installed locally without being required for every reproducible handoff.

Only explicit user action should mark a node optional. Workflow graph usage is
advisory; ComfyGit should not silently downgrade a package because it looks
unused in one workflow.

## Recover After Manual Edits

If you changed `custom_nodes/` by hand:

```bash
cg repair
cg status
```

Prefer ComfyGit commands over deleting node folders or symlinks manually.
