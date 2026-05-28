# Environment Corruption

Most "corruption" is runtime drift: files under the ComfyUI checkout, virtualenv,
custom nodes, or symlinks no longer match the manifest.

Start with repair:

```bash
cg repair
cg status
```

## Common Causes

- manually deleting or moving custom node directories
- manually editing `.venv`
- interrupted sync or create
- branch switches with runtime state left behind
- broken model symlinks
- partial node downloads

## Rebuild Runtime State

```bash
cg sync --verbose
cg repair --models required
```

## Restore From Git History

Use Git commands when the tracked environment recipe changed and you want a
different commit:

```bash
cg log
cg checkout <commit>
cg switch main
cg revert <commit>
```

Use `reset --hard` only when you intentionally want to discard local changes:

```bash
cg reset HEAD --hard --yes
```

## Reimport As A Last Resort

If the runtime directory is badly damaged but the portable environment source is
available:

```bash
cg export backup.tar.gz --allow-issues
cg import backup.tar.gz --name recovered-env --use
```

For runtime/build use, prefer:

```bash
cg materialize backup.tar.gz --name recovered-runtime --replace
```
