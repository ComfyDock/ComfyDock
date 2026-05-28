# Development Nodes

Development nodes let you use a local custom-node checkout while keeping the
environment manifest understandable and portable.

There are two common cases:

- You already have a tracked registry or Git node and want to replace the
  materialized copy with your local checkout.
- You have a local custom node directory and want ComfyGit to track it as a
  development node.

## Prefer Dev Link For Existing Nodes

If the environment already tracks the node, use `node dev-link`:

```bash
cg node dev-link rgthree-comfy \
  --path ~/dev/rgthree-comfy \
  --replace-existing
```

This preserves the existing manifest node identifier. Workflow references keep
pointing at the same package, while your runtime uses the local checkout.

Use `--replace-existing` when ComfyGit should archive the materialized node copy
and replace it with a symlink.

## Track A Local Directory As Development

If the node only exists locally:

```bash
cg node add my-custom-node --dev
```

This records the node as a development node and installs its dependencies. The
local path itself is not portable to another machine.

## Make Development Nodes Portable

A development node becomes portable when ComfyGit can record Git provenance:

- repository URL
- pinned commit
- optional branch context

The pinned commit is what another machine should use for exact reconstruction.
The branch name is useful context, but it is not a stable version by itself.

Before sharing, check status and make sure development nodes have enough source
information for the intended handoff.

```bash
cg status
cg commit -m "Use local checkout for rgthree-comfy"
```

## Removing Development Nodes

Development node removal does not delete your developer-owned checkout.

```bash
cg node remove my-custom-node --dev
```

Use `--untrack` when you want to remove manifest tracking while leaving runtime
files alone:

```bash
cg node remove my-custom-node --untrack
```

## Do Not Just Delete The Symlink

Manual filesystem edits can leave the manifest and runtime out of sync. Use
ComfyGit commands first, then run:

```bash
cg repair
```

when the runtime needs to be reconciled.
