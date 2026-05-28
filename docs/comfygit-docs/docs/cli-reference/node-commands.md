# Node Commands

Use node commands to add, update, link, remove, and inspect ComfyUI custom
nodes in the selected environment.

## Add Nodes

```bash
cg node add NODE [NODE...]
cg node add NODE@VERSION
cg node add https://github.com/owner/repo.git
cg node add https://github.com/owner/repo.git@main
```

Useful options:

```bash
cg node add NODE --strict
cg node add NODE --no-test
cg node add NODE --force
cg node add NODE --extra EXTRA
cg node add NODE --all-extras
cg node add NODE --resolve-with-overlays
```

Batch add operations are sequential. If one node fails, earlier successful nodes
are not automatically rolled back.

## Development Links

```bash
cg node dev-link NODE --path ~/dev/node-checkout --replace-existing
cg node dev-link NODE --path ~/dev/node-checkout --name custom_nodes_name
```

Use `dev-link` when an environment already tracks a node and you want the
runtime to use your local checkout while preserving the manifest identity.

## Remove Nodes

```bash
cg node remove NODE [NODE...]
cg node remove NODE --dev
cg node remove NODE --untrack
```

Development node removal and `--untrack` leave filesystem contents alone. Normal
tracked registry/Git node removal cleans manifest references and the materialized
node directory.

## Update, List, Prune

```bash
cg node list
cg node update NODE [--yes] [--no-test]
cg node prune [--exclude PACKAGE...] [--yes]
```

## Manager Node

`comfygit-manager` is managed through the dedicated manager commands:

```bash
cg manager status
cg manager update --yes
```

Do not confuse `comfygit-manager` with ComfyUI-Manager.
