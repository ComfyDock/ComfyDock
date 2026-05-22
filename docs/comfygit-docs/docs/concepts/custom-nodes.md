# Custom Nodes

Custom nodes extend ComfyUI with new node types, loaders, processors, and
interfaces. ComfyGit tracks custom node packages so an environment can be
recreated later.

For each tracked node package, ComfyGit records source metadata and dependency
metadata in the environment manifest. Sync then materializes those nodes into
the ComfyUI runtime.

## Registry, Git, And Development Nodes

Most users install published nodes through the ComfyUI registry:

```bash
cg node add comfygit-manager
```

When a node is not available through the registry, ComfyGit can track a Git
source. When you are developing a node locally, development-node linking can
replace the materialized runtime copy with your checkout while preserving the
manifest identity.

## Criticality

Required nodes are part of the runnable environment. Optional nodes may warn
without blocking every workflow. Missing criticality is treated conservatively as
required.

Read more: [Adding custom nodes](../user-guide/custom-nodes/adding-nodes.md)
and [development nodes](../user-guide/custom-nodes/development-nodes.md).
